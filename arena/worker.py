"""Runs ONLY inside a networkless, credential-free GitHub-hosted container."""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time

sys.path.insert(0, "/official")
import numpy as np
import torch
import train_astro_party  # resolves the participant's portable extractor names
from eval_astro_party import load_model, decode_action
from envs.game import AstroPartyGame, WALLS, SHIP_POLY_LOCAL, ASTRONAUT_POLY_LOCAL
from envs.render import Renderer
from participants import BUILTINS,builtin_identity,OfficialRulePolicy

torch.set_num_threads(1)

def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")

class AuditGame(AstroPartyGame):
    """Passive weapon counters; each operation still calls the original method."""
    def _fire_gun(self, ship_id, ship):
        before = ship.ammo
        result = super()._fire_gun(ship_id, ship)
        if ship.ammo < before: self.audit[ship_id]["gun_shots"] += 1
        return result
    def _fire_laser(self, ship_id, ship, events):
        before = ship.laser_charges
        self.laser_active = True
        try: result = super()._fire_laser(ship_id, ship, events)
        finally: self.laser_active = False
        if ship.laser_charges < before: self.audit[ship_id]["laser_shots"] += 1
        return result
    def _hit(self, shooter_id, target_id, events):
        prior = self.ships[target_id].mode
        before = len(events)
        result = super()._hit(shooter_id, target_id, events)
        new = events[before:]
        if any(e.kind in ("eject", "kill") and e.target == target_id for e in new):
            self.audit[shooter_id]["weapon_hits"] += 1
            if prior == "astronaut": self.audit[shooter_id]["pilot_weapon_kills"] += 1
        return result

def counters():
    return {s:dict(gun_shots=0, laser_shots=0, weapon_hits=0, pilot_weapon_kills=0,
                   fire_requests=0, ship_ticks=0, pilot_ticks=0, empty_ammo_ticks=0,
                   pickups=0, respawns=0, ejects=0, kills=0, ram_kills=0) for s in ("ship1", "ship2")}

def visual(game):
    def f(v): return round(float(v), 2)
    ships = []
    for sid in ("ship1", "ship2"):
        s = game.ships[sid]
        ships.append([f(s.pos[0]), f(s.pos[1]), round(float(s.angle), 4), int(s.alive),
                      int(s.mode == "astronaut"), s.ammo, s.cooldown, s.laser_charges, s.respawn_timer])
    return {"t":game.t, "s":ships,
            "a":[[f(a.pos[0]),f(a.pos[1]),f(a.radius),a.hp] for a in game.asteroids],
            "b":[[f(b.pos[0]),f(b.pos[1]),int(b.owner == "ship2")] for b in game.bullets],
            "p":[[f(p.pos[0]),f(p.pos[1]),int(p.active)] for p in game.pickups],
            "e":[[e.kind, [f(x) for x in e.pos], [f(x) for x in e.end] if e.end is not None else None, f(e.radius), e.timer] for e in game.effects]}

def load(path):
    import zipfile
    if not zipfile.is_zipfile(path): raise ValueError("檔案不是模型ZIP")
    model = load_model(str(path))
    count = sum(p.numel() for p in model.policy.parameters())
    if count > 2_000_000: raise ValueError(f"模型{count}參數，超過作業2M上限")
    if tuple(model.observation_space.shape) != (84,) or tuple(model.action_space.shape) != (3,):
        raise ValueError("模型必須使用原始Box(84)觀測與Box(3)動作")
    model.policy.set_training_mode(False)
    return model, {"algorithm_loaded_as":type(model).__name__, "policy":type(model.policy).__name__, "parameters":count,
                   "note":"載入器選用的類別不等於原始訓練算法證明；競賽使用原生predict"}

def contract_check():
    base = AstroPartyGame(); audited = AuditGame()
    base.reset(906731); audited.reset(906731); audited.audit = counters(); audited.laser_active = False
    for i in range(32):
        acts = {s:decode_action(np.array([.3 if s == "ship1" else -.2,.8,1.], dtype=np.float32)) for s in ("ship1", "ship2")}
        a = base.step(acts); b = audited.step(acts)
        assert a == b
        for sid in acts: assert np.array_equal(base.observe(sid), audited.observe(sid))

def play(models, job, seed, a_seat, output):
    game = AuditGame(); game.reset(seed); game.audit = counters(); game.laser_active = False
    assignment = {"ship1":job["a"]["id"] if a_seat == "ship1" else job["b"]["id"],
                  "ship2":job["b"]["id"] if a_seat == "ship1" else job["a"]["id"]}
    # Independent, identical per-player streams make a stateful/random fallback
    # visible; official comparisons require deterministic predict.
    np.random.seed(seed); random.seed(seed); torch.manual_seed(seed)
    frames = [visual(game)]; timeline = []; actions = []; observations = []; latency = {s:[] for s in assignment}
    started = time.perf_counter()
    while not (game.done or game.truncated):
        obs = {s:game.observe(s) for s in assignment}; pair = []
        for sid in ("ship1", "ship2"):
            t = time.perf_counter()
            with torch.inference_mode(): action = np.asarray(models[assignment[sid]].predict(obs[sid], deterministic=True)[0], dtype=np.float32)
            latency[sid].append((time.perf_counter()-t)*1000)
            if action.shape != (3,) or not np.isfinite(action).all(): raise ValueError("模型輸出非有限Box(3)動作")
            pair.append(action)
            s = game.ships[sid]; c = game.audit[sid]
            if s.alive:
                c["pilot_ticks" if s.mode == "astronaut" else "ship_ticks"] += 1
                c["empty_ammo_ticks"] += int(s.mode == "ship" and s.ammo == 0 and s.laser_charges == 0)
                c["fire_requests"] += int(action[2] > 0)
        actions.append(pair); observations.append([obs["ship1"],obs["ship2"]])
        events = game.step({sid:decode_action(pair[i]) for i,sid in enumerate(("ship1", "ship2"))})
        for event in events:
            timeline.append({"tick":game.t,"kind":event.kind,"by":assignment[event.by],"target":assignment.get(event.target)})
            metric = {"pickup":"pickups","respawn":"respawns","eject":"ejects","kill":"kills"}.get(event.kind)
            if metric: game.audit[event.by][metric] += 1
        if game.t % 2 == 0 or game.done or game.truncated: frames.append(visual(game))
    a_alive = game.ships[a_seat].alive
    b_alive = game.ships["ship2" if a_seat == "ship1" else "ship1"].alive
    winner = job["a"]["id"] if a_alive and not b_alive else job["b"]["id"] if b_alive and not a_alive else None
    name = f"{seed}-{a_seat}"
    metrics = {}
    for sid,pid in assignment.items():
        c = game.audit[sid]
        c["ram_kills"] = max(0,c["kills"]-c["pilot_weapon_kills"])
        c["inference_mean_ms"] = float(np.mean(latency[sid])); c["inference_p95_ms"] = float(np.quantile(latency[sid], .95))
        metrics[pid] = c
    row = {"id":name,"seed":seed,"a_seat":a_seat,"assignment":assignment,"winner":winner,"ticks":game.t,
           "seconds":game.t/50,"compute_seconds":time.perf_counter()-started,"timeline":timeline,"metrics":metrics,
           "replay":f"replays/{name}.json.gz","audit":f"audit/{name}.npz"}
    record = {"version":1,"seed":seed,"assignment":assignment,"winner":winner,"ticks":game.t,
              "walls":WALLS,"ship_polygon":SHIP_POLY_LOCAL.tolist(),"pilot_polygon":ASTRONAUT_POLY_LOCAL.tolist(),
              "timeline":timeline,"frames":frames,"display_fps":25,"physics_fps":50,
              "recording":"Rendered from captured original game state; no browser physics or model inference"}
    with gzip.open(output / row["replay"], "wt", encoding="utf-8") as stream: json.dump(record,stream,separators=(",",":"),ensure_ascii=False)
    np.savez_compressed(output / row["audit"], actions=np.asarray(actions), observations=np.asarray(observations))
    return row

def render_selected(row, output):
    import imageio.v2 as imageio
    game = AstroPartyGame(); game.reset(row["seed"]); renderer = Renderer("rgb_array")
    actions = np.load(output / row["audit"])["actions"]
    name = row["id"] + ".mp4"
    with imageio.get_writer(str(output / "videos" / name), fps=25, codec="libx264", quality=6, macro_block_size=2) as writer:
        writer.append_data(renderer.draw(game))
        for i,pair in enumerate(actions,1):
            game.step({sid:decode_action(pair[j]) for j,sid in enumerate(("ship1","ship2"))})
            if i%2 == 0 or i == len(actions): writer.append_data(renderer.draw(game))
    alive = [sid for sid in ("ship1","ship2") if game.ships[sid].alive]
    winner = row["assignment"][alive[0]] if len(alive)==1 else None
    if game.t != row["ticks"] or winner != row["winner"]: raise ValueError("影片重播與原始結果不一致")
    renderer.close()
    return {"game_id":row["id"],"path":"videos/"+name,"replay_matches_original":True}

def load_builtin(player):
    kind=player['bot']
    hashes={name:hashlib.sha256((Path('/official')/name).read_bytes()).hexdigest() for name in BUILTINS[kind]}
    if builtin_identity(kind,hashes)!=player['sha256']:raise ValueError('Official bot source SHA mismatch')
    return OfficialRulePolicy(kind),dict(algorithm_loaded_as='Official RuleBot',policy='Original official rule bot',parameters=0,kind='official_rulebot',source_hashes=hashes,note='固定規則程式，非神經網路或新訓練模型')

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--job"); parser.add_argument("--self-test",action="store_true"); args = parser.parse_args()
    if args.self_test:
        from stable_baselines3 import PPO
        import gymnasium as gym
        contract_check()
        class ContractEnv(gym.Env):
            observation_space = gym.spaces.Box(-10.,10.,(84,),dtype=np.float32)
            action_space = gym.spaces.Box(-1.,1.,(3,),dtype=np.float32)
        models = {pid:PPO("MlpPolicy",ContractEnv(),n_steps=8,batch_size=8,policy_kwargs={"net_arch":[8,8]},seed=i,device="cpu") for i,pid in enumerate(("test_a","test_b"))}
        for model in models.values():
            with torch.no_grad(): model.policy.action_net.bias.copy_(torch.tensor([.4,.8,1.]))
        output = Path("/out")
        for d in ("audit","replays","videos"): (output/d).mkdir(parents=True,exist_ok=True)
        job={"a":{"id":"test_a"},"b":{"id":"test_b"}}
        rows = [play(models,job,907331,seat,output) for seat in ("ship1","ship2")]
        videos = [render_selected(row,output) for row in rows]
        assert all(v["replay_matches_original"] for v in videos)
        from models.rusher_bot import rusher_bot_action
        from models.sniper_bot import sniper_bot_action
        bots={k:OfficialRulePolicy(k) for k in ('rusher','sniper')}
        game=AstroPartyGame();game.reset(907331)
        for k,original in [('rusher',rusher_bot_action),('sniper',sniper_bot_action)]:
            for sid in ('ship1','ship2'):assert np.array_equal(bots[k].predict(game.observe(sid))[0],original(game.observe(sid)))
        bot_job={'a':{'id':'rusher'},'b':{'id':'sniper'}}
        bot_rows=[play(bots,bot_job,907332,seat,output) for seat in ('ship1','ship2')]
        assert all(render_selected(row,output)['replay_matches_original'] for row in bot_rows)
        print(json.dumps({"cloud_self_test":"passed","diagnostic_games":4,"ranking_games":0,"training_updates":0,"official_bots_exact_actions":True,"swapped_seats":True,"official_mp4_replay_matches":True}))
        return
    if not args.job: parser.error("--job is required for league matches")
    job = json.loads(Path(args.job).read_text()); output = Path("/out")
    for name in ("audit","replays","videos"): (output/name).mkdir(exist_ok=True)
    contract_check()
    models = {}; identities = {}
    for player in (job["a"],job["b"]):
        if player.get('kind')=='official_rulebot':
            models[player['id']],identities[player['id']]=load_builtin(player)
            continue
        path = Path("/models") / (player["id"]+".zip")
        if hashlib.sha256(path.read_bytes()).hexdigest() != player["sha256"]: raise ValueError("模型SHA在比賽前改變")
        models[player["id"]], identities[player["id"]] = load(path)
    rows = []
    for seed in job["seeds"]:
        for seat in ("ship1", "ship2"):
            rows.append(play(models,job,seed,seat,output))
    chosen = []
    for winner in (job["a"]["id"], job["b"]["id"], None):
        eligible = [r for r in rows if r["winner"] == winner]
        if eligible: chosen.append(min(eligible,key=lambda r:(r["seed"],r["a_seat"])))
    longest = max(rows,key=lambda r:r["ticks"])
    if longest not in chosen: chosen.append(longest)
    videos = [render_selected(row,output) for row in chosen[:4]]
    write(output / "raw.json", {"key":job["key"],"a":job["a"]["id"],"b":job["b"]["id"],"games":rows,"videos":videos,"model_info":identities})
    print(f"Finished {len(rows)} original games with swapped seats; all replays available.")

if __name__ == "__main__": main()
