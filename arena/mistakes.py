"""Conceptual mistakes: tick-level decisions a human player would avoid.

Reads each game's audit log (raw84 observations and actions for both seats,
every tick) and the replay's wall layout on the trusted host. It never loads a
model or runs the engine, so the locked worker core and cached pairs stay
valid. Everything is descriptive: a share of the ticks where a condition
applied, split by opponent and by won or lost games.

raw84 per seat (as envs/game.py observe): own[0:14] = (x-600)/600, (y-400)/400,
vx/260, vy/260, cos a, sin a, planet dist, wall dist, ammo/MAX, reload, laser,
gun ready, is pilot, respawn; enemy[14:26] = dx/600, dy/400, dvx/260, dvy/260,
cos/sin relative angle, alive, pilot, ammo/MAX, reload, laser, gun ready;
asteroids[26:38] = 4 x (dx/600, dy/400, r/600). Nose = (sin a, -cos a); a
positive turn action increases a, i.e. turns toward right = (cos a, sin a).
"""
import array
import ast
import csv
import json
import math
import statistics
import struct
import sys
import zipfile
from pathlib import Path
from opening import read_replay

VERSION = 1
AUDIT_LIMIT = 4 * 1024 * 1024
BULLET_SPEED, MUZZLE, BULLET_R, SHIP_R, PILOT_R = 620.0, 20.0, 4.0, 16.0, 9.0
PLANET = (600.0, 400.0, 100.0)
HIT_HORIZON = 1.2
BANDS = ((0, 250, "near"), (250, 500, "mid"), (500, 1e9, "far"))
# (key, label, mistake meaning). Each game stores [mistake ticks, applicable ticks].
METRICS = (
    ("open_not_turning", "開局沒轉向對手", "開局頭1秒、雙方都是船且敵人偏離機頭>15°時，沒有以|turn|>0.2朝提前量方向轉"),
    ("missed_shot", "能命中卻不開火", "雙方都是船、槍已就緒有彈、射線無阻擋、直射此刻會命中，卻沒有開火"),
    ("blocked_fire", "射線被擋仍開火", "實際能射出的扣扳機中，往提前量方向的射線被星球、牆或小行星擋住"),
    ("exposed_unarmed", "被瞄準時沒面向敵人", "持彈敵船直射此刻會命中自己，而自己的機頭偏離敵人>30°"),
    ("thrust_away_close", "近距離背對推進", "敵船在250px內，自己推進(>0.3)時機頭偏離敵人>90°"),
    ("pilot_exposed", "飛行員暴露在敵船視線", "自己是飛行員、敵船在300px內，且兩者之間沒有任何遮蔽"),
    ("finish_passive", "不追擊近處敵方飛行員", "敵方飛行員在250px內、自己是船時，沒有面向它（<20°）推進"),
    ("empty_charge", "空彈還衝向敵人", "自己沒彈沒雷射、敵船有彈，自己朝敵人方向速度>30px/s"))

def read_audit(path):
    """Stdlib reader for both float32 arrays of an audit NPZ."""
    out = {}
    with zipfile.ZipFile(path) as archive:
        for name, width in (("observations", 84), ("actions", 3)):
            info = archive.getinfo(name + ".npy")
            if info.file_size > AUDIT_LIMIT: raise ValueError("Audit array too large")
            raw = archive.read(info)
            if raw[:6] != b"\x93NUMPY": raise ValueError("Not an npy array")
            size, start = (struct.unpack("<H", raw[8:10])[0], 10) if raw[6] == 1 else (struct.unpack("<I", raw[8:12])[0], 12)
            header = ast.literal_eval(raw[start:start + size].decode("latin1")); shape = tuple(header["shape"])
            if header["descr"] != "<f4" or header["fortran_order"] or shape[1:] != (2, width): raise ValueError("Unexpected audit array")
            values = array.array("f"); values.frombytes(raw[start + size:])
            if sys.byteorder == "big": values.byteswap()
            if len(values) != shape[0] * 2 * width: raise ValueError("Truncated audit array")
            out[name] = (values, shape[0])
    if out["observations"][1] != out["actions"][1]: raise ValueError("Audit arrays differ in length")
    return out

def segment_hits_circle(p, q, c, r):
    dx, dy = q[0] - p[0], q[1] - p[1]; fx, fy = p[0] - c[0], p[1] - c[1]
    length = dx * dx + dy * dy
    t = 0 if not length else max(0, min(1, -(fx * dx + fy * dy) / length))
    return (fx + t * dx) ** 2 + (fy + t * dy) ** 2 < r * r

def segment_hits_rect(p, q, cx, cy, hw, hh):
    lo, hi = 0.0, 1.0
    for a, d, c, h in ((p[0], q[0] - p[0], cx, hw), (p[1], q[1] - p[1], cy, hh)):
        if abs(d) < 1e-9:
            if abs(a - c) > h: return False
            continue
        t1, t2 = (c - h - a) / d, (c + h - a) / d
        lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
        if lo > hi: return False
    return True

class View:
    """World-frame view of one seat's observation at one tick."""
    def __init__(self, o, base):
        self.pos = (o[base] * 600 + 600, o[base + 1] * 400 + 400); self.vel = (o[base + 2] * 260, o[base + 3] * 260)
        c, s = o[base + 4], o[base + 5]; self.nose = (s, -c); self.right = (c, s)
        self.ammo, self.laser, self.ready, self.pilot = o[base + 8], o[base + 10], o[base + 11] > .5, o[base + 12] > .5
        self.enemy_rel = (o[base + 14] * 600, o[base + 15] * 400)
        self.enemy_vel = (self.vel[0] + o[base + 16] * 260, self.vel[1] + o[base + 17] * 260)
        self.enemy_alive, self.enemy_pilot, self.enemy_ammo, self.enemy_laser = o[base + 20] > .5, o[base + 21] > .5, o[base + 22], o[base + 24]
        self.asteroids = [(self.pos[0] + o[base + 26 + 3 * i] * 600, self.pos[1] + o[base + 27 + 3 * i] * 400, o[base + 28 + 3 * i] * 600) for i in range(4) if o[base + 28 + 3 * i] > 0]
    def angle(self, v):
        """Signed radians from the nose to v; positive = to the right."""
        return math.atan2(v[0] * self.right[0] + v[1] * self.right[1], v[0] * self.nose[0] + v[1] * self.nose[1])
    def lead(self):
        """Intercept of the enemy at its current velocity, relative to us."""
        d, v = self.enemy_rel, self.enemy_vel
        a = v[0] ** 2 + v[1] ** 2 - BULLET_SPEED ** 2; b = 2 * (d[0] * v[0] + d[1] * v[1]); c = d[0] ** 2 + d[1] ** 2
        disc = b * b - 4 * a * c
        if a >= 0 or disc < 0: return d
        t = (-b - math.sqrt(disc)) / (2 * a)
        return (d[0] + v[0] * t, d[1] + v[1] * t) if t > 0 else d
    def would_hit(self):
        """Closest approach of a straight-ahead bullet to the moving enemy."""
        n = self.nose; target = PILOT_R if self.enemy_pilot else SHIP_R
        r0 = (self.enemy_rel[0] - MUZZLE * n[0], self.enemy_rel[1] - MUZZLE * n[1])
        rv = (self.enemy_vel[0] - BULLET_SPEED * n[0], self.enemy_vel[1] - BULLET_SPEED * n[1])
        vv = rv[0] ** 2 + rv[1] ** 2
        t = max(0, min(HIT_HORIZON, -(r0[0] * rv[0] + r0[1] * rv[1]) / vv)) if vv else 0
        miss = math.hypot(r0[0] + rv[0] * t, r0[1] + rv[1] * t)
        return miss < target + BULLET_R, BULLET_SPEED * t + MUZZLE

def blocked(p, q, walls, asteroids, pad=BULLET_R):
    if segment_hits_circle(p, q, PLANET[:2], PLANET[2] + pad): return True
    if any(segment_hits_circle(p, q, (x, y), r + pad) for x, y, r in asteroids): return True
    return any(segment_hits_rect(p, q, cx, cy, hw + pad, hh + pad) for cx, cy, hw, hh in walls)

def game_mistakes(row, walls, audit):
    obs, steps = audit["observations"]; act, _ = audit["actions"]
    timeline = row["timeline"]; players = {}
    for seat, sid in enumerate(("ship1", "ship2")):
        pid = row["assignment"][sid]
        c = {k: [0, 0] for k, *_ in METRICS}; bands = {name: [0, 0] for *_, name in BANDS}
        runs = {}; current = {}; angle_1s = None; flee = [0.0, 0]
        def mark(key, tick, happened, applies=True):
            if not applies: return
            c[key][1] += 1
            if happened:
                c[key][0] += 1
                start, end = current.get(key, (tick, tick - 1))
                current[key] = (start, tick) if end == tick - 1 else (tick, tick)
                best = runs.get(key)
                if best is None or current[key][1] - current[key][0] > best[1] - best[0]: runs[key] = current[key]
        for j in range(steps):
            o = obs[(j * 2 + seat) * 84:(j * 2 + seat + 1) * 84]; e = obs[(j * 2 + 1 - seat) * 84:(j * 2 + 2 - seat) * 84]
            turn, thrust, fire = act[(j * 2 + seat) * 3], act[(j * 2 + seat) * 3 + 1], act[(j * 2 + seat) * 3 + 2] > 0
            me, them, tick = View(o, 0), View(e, 0), j + 1
            if not me.enemy_alive: continue
            rel = me.enemy_rel; distance = math.hypot(*rel)
            to_enemy = abs(me.angle(rel)); ships = not me.pilot and not me.enemy_pilot
            if j == 50 and ships: angle_1s = abs(math.degrees(me.angle(me.lead())))
            if ships and j < 50 and to_enemy > math.radians(15):
                lead = me.angle(me.lead())
                mark("open_not_turning", tick, not (abs(turn) > .2 and (turn > 0) == (lead > 0)))
            armed = me.ready and (me.ammo > 0 or me.laser > 0)
            if ships and armed:
                hit, reach = me.would_hit()
                end = (me.pos[0] + me.nose[0] * reach, me.pos[1] + me.nose[1] * reach)
                muzzle = (me.pos[0] + me.nose[0] * MUZZLE, me.pos[1] + me.nose[1] * MUZZLE)
                if hit and not blocked(muzzle, end, walls, me.asteroids):
                    mark("missed_shot", tick, not fire)
                    band = next(name for lo, hi, name in BANDS if lo <= distance < hi)
                    bands[band][1] += 1; bands[band][0] += not fire
                if fire:
                    lead = me.lead(); length = math.hypot(*lead)
                    aim = (me.pos[0] + me.nose[0] * length, me.pos[1] + me.nose[1] * length)
                    mark("blocked_fire", tick, blocked(muzzle, aim, walls, me.asteroids))
            if ships and (them.ammo > 0 or them.laser > 0):
                mark("exposed_unarmed", tick, them.would_hit()[0] and to_enemy > math.radians(30))
            if ships and distance < 250 and thrust > .3:
                mark("thrust_away_close", tick, to_enemy > math.radians(90))
            if me.pilot and not me.enemy_pilot and distance < 300:
                enemy = (me.pos[0] + rel[0], me.pos[1] + rel[1])
                mark("pilot_exposed", tick, not blocked(me.pos, enemy, walls, me.asteroids, pad=0))
                speed = math.hypot(*me.vel)
                if speed > 10: flee[0] += -(me.vel[0] * rel[0] + me.vel[1] * rel[1]) / (speed * distance or 1); flee[1] += 1
            if not me.pilot and me.enemy_pilot and distance < 250:
                mark("finish_passive", tick, not (thrust > .3 and to_enemy < math.radians(20)))
            if ships and me.ammo <= 0 and me.laser <= 0 and (them.ammo > 0 or them.laser > 0):
                closing = (me.vel[0] * rel[0] + me.vel[1] * rel[1]) / (distance or 1)
                mark("empty_charge", tick, closing > 30)
        players[pid] = {**c, "missed_shot_bands": bands, "angle_1s": None if angle_1s is None else round(angle_1s, 1), "pilot_flee": [round(flee[0], 3), flee[1]],
                        "runs": {k: list(v) for k, v in runs.items()}}
    return {"version": VERSION, "players": players}

def led_then_lost(row, player):
    """After ejecting the enemy first, how a lost game slipped away."""
    ejects = [e for e in row["timeline"] if e["kind"] == "eject"]
    if not ejects or row["winner"] in (player, None): return None
    first = {e["target"] for e in ejects if e["tick"] == ejects[0]["tick"]}
    if first != {next(v for v in row["assignment"].values() if v != player)}: return None
    respawned = any(e["kind"] == "respawn" and e["by"] != player for e in row["timeline"])
    rammed = row["metrics"][row["winner"]]["ram_kills"] > 0
    return ("enemy_respawned_" if respawned else "enemy_never_respawned_") + ("then_rammed" if rammed else "then_shot")

def attach(pair, folder, cache):
    """One pair's per-game records, from the cache or its audit files."""
    folder = Path(folder); known = cache.get(pair["key"], {}); records = {}; failed = 0
    for row in pair["games"]:
        record = known.get(row["id"])
        if not record or record.get("version") != VERSION:
            try:
                record = game_mistakes(row, read_replay(folder / row["replay"])["walls"], read_audit(folder / row["audit"]))
            except Exception:
                record = None; failed += 1
        if record: records[row["id"]] = record
    pair["mistakes"] = {pid: summary(items(pair, records, pid), pid) for pid in (pair["a"], pair["b"])}
    return records, failed

def items(pair, records, player):
    return [(pair["key"], r, records[r["id"]]["players"][player]) for r in pair["games"] if r["id"] in records and player in records[r["id"]]["players"]]

def player_items(state, records, player):
    return [x for p in state["pairs"] if player in (p["a"], p["b"]) for x in items(p, records.get(p["key"], {}), player)]

def summary(entries, player, split=True):
    """entries: [(pair key, game row, this player's record)]."""
    def total(es):
        out = {k: [0, 0] for k, *_ in METRICS}; bands = {name: [0, 0] for *_, name in BANDS}; flee = [0.0, 0]
        for _, r, m in es:
            for k in out: out[k][0] += m[k][0]; out[k][1] += m[k][1]
            for b in bands: bands[b][0] += m["missed_shot_bands"][b][0]; bands[b][1] += m["missed_shot_bands"][b][1]
            flee[0] += m["pilot_flee"][0]; flee[1] += m["pilot_flee"][1]
        angles = [m["angle_1s"] for _, r, m in es if m["angle_1s"] is not None]
        return {"games": len(es), "rates": {k: (v[0] / v[1] if v[1] else None) for k, v in out.items()}, "ticks": out,
                "missed_shot_by_distance": {b: (v[0] / v[1] if v[1] else None) for b, v in bands.items()},
                "angle_1s_median": statistics.median(angles) if angles else None, "pilot_flee_cos": flee[0] / flee[1] if flee[1] else None}
    result = total(entries)
    if split:
        result["won"] = total([x for x in entries if x[1]["winner"] == player])
        result["lost"] = total([x for x in entries if x[1]["winner"] not in (player, None)])
        paths = [led_then_lost(r, player) for _, r, _ in entries]
        result["led_then_lost"] = {k: paths.count(k) for k in sorted(set(paths) - {None})}
    return result

def examples(entries, player, key, limit=5):
    hits = [x for x in entries if key in x[2]["runs"]]
    hits.sort(key=lambda x: (x[1]["winner"] == player, x[2]["runs"][key][0] - x[2]["runs"][key][1], x[1]["seed"], x[1]["a_seat"]))
    return [{"pair": pair, "game_id": r["id"], "ticks": m["runs"][key], "at": max(0, round(m["runs"][key][0] / 50 - 1, 1))} for pair, r, m in hits[:limit]]

def report(state, records):
    """Per player: overall, per opponent and won/lost rates, ranked against the league."""
    people = {p["id"]: p for p in state["players"]}; players = {}
    overall = {r["id"]: r.get("mistakes") for r in state["standings"] if (r.get("mistakes") or {}).get("games")}
    for pid, own in overall.items():
        entries = player_items(state, records, pid); ranked = []
        for key, label, meaning in METRICS:
            value = own["rates"][key]; others = [o["rates"][key] for k, o in overall.items() if k != pid and o["rates"][key] is not None]
            if value is None: continue
            ranked.append({"metric": key, "label": label, "meaning": meaning, "value": value, "ticks": own["ticks"][key],
                           "won": own["won"]["rates"][key], "lost": own["lost"]["rates"][key],
                           "others_median": statistics.median(others) if others else None,
                           "rank": 1 + sum(o < value for o in others), "of": len(others) + 1,
                           "by_opponent": {(p["b"] if p["a"] == pid else p["a"]): p["mistakes"][pid]["rates"][key]
                                           for p in state["pairs"] if pid in (p["a"], p["b"]) and (p.get("mistakes") or {}).get(pid)},
                           "examples": examples(entries, pid, key)})
        ranked.sort(key=lambda m: -(m["value"] - (m["others_median"] or 0)))
        players[pid] = {"name": people[pid]["name"], "games": own["games"], "angle_1s_median": own["angle_1s_median"], "pilot_flee_cos": own["pilot_flee_cos"],
                        "missed_shot_by_distance": own["missed_shot_by_distance"], "led_then_lost": own["led_then_lost"], "mistakes": ranked}
    return players

LED_THEN_LOST = {"enemy_respawned_then_shot": "對手復活後自己最後被射殺", "enemy_respawned_then_rammed": "對手復活後自己飛行員被撞死",
                 "enemy_never_respawned_then_shot": "對手未復活、自己最後被射殺", "enemy_never_respawned_then_rammed": "對手未復活、自己飛行員被撞死"}

def site_url(state):
    owner, repo = state.get("repository", "/").split("/", 1)
    return f"https://{owner.lower()}.github.io/{repo}/"

def markdown(state, players):
    pct = lambda v: "—" if v is None else f"{v * 100:.1f}%"
    names = {p["id"]: p["name"] for p in state["players"]}
    lines = ["# OSL 概念性失誤報告（自動產生）", "", f"資料：{state.get('total_games', 0)} 場 · 發布 {state.get('updated_at', '')} · 開局輪 {(state.get('seed_round') or {}).get('id', '—')}", "",
             "由每局動作／觀測紀錄（每 tick）推得，只描述行為，不載入模型、不重賽。比例＝發生失誤的 tick ÷ 該條件適用的 tick；依「高於其他人中位數多少」排序。"
             "名次 1 表示最少犯此失誤。範例連結從失誤片段前 1 秒開始播放，ticks 為 50/秒。", ""]
    for pid, p in players.items():
        lines += [f"## {p['name']}（{pid}）· {p['games']} 局", "",
                  f"開局 1 秒時機頭偏離提前量方向中位數 {p['angle_1s_median']:.0f}°；飛行員逃離方向 cos 平均 {p['pilot_flee_cos'] if p['pilot_flee_cos'] is None else round(p['pilot_flee_cos'], 2)}；能命中卻不開火依距離：近 {pct(p['missed_shot_by_distance']['near'])}、中 {pct(p['missed_shot_by_distance']['mid'])}、遠 {pct(p['missed_shot_by_distance']['far'])}。" if p["angle_1s_median"] is not None else "", ""]
        if p["led_then_lost"]:
            lines += ["先擊落對手卻輸掉的局：" + "、".join(f"{LED_THEN_LOST.get(k, k)} {v} 局" for k, v in p["led_then_lost"].items()), ""]
        lines += ["| 失誤 | 本人 | 贏的局 | 輸的局 | 其他人中位數 | 名次 | 依對手 | 範例（game · ticks） |", "|---|---:|---:|---:|---:|---:|---|---|"]
        for m in p["mistakes"]:
            opp = "；".join(f"{names.get(k, k)} {pct(v)}" for k, v in m["by_opponent"].items())
            ex = " ".join(f"[{x['game_id']} · {x['ticks'][0]}–{x['ticks'][1]}]({site_url(state)}#game={x['pair']}/{x['game_id']}@{x['at']})" for x in m["examples"]) or "—"
            lines.append(f"| {m['label']} | {pct(m['value'])} | {pct(m['won'])} | {pct(m['lost'])} | {pct(m['others_median'])} | {m['rank']}/{m['of']} | {opp} | {ex} |")
        lines += ["", "定義：" + "；".join(f"{m['label']}＝{m['meaning']}" for m in p["mistakes"]), ""]
    return "\n".join(lines)

def annotate(state, records):
    """Overall per-player summaries across every pair the player played."""
    for row in state["standings"]: row["mistakes"] = summary(player_items(state, records, row["id"]), row["id"])

def export(folder, state, records):
    """records: {pair key: {game id: record}}; also the cache the next run reads."""
    folder = Path(folder); players = report(state, records); names = {p["id"]: p["name"] for p in state["players"]}
    (folder / "mistakes_games.json").write_text(json.dumps({"version": VERSION, "pairs": {p["key"]: records.get(p["key"], {}) for p in state["pairs"]}},
                                                           separators=(",", ":"), allow_nan=False), encoding="utf-8")
    (folder / "conceptual_mistakes.json").write_text(json.dumps({"generated_at": state.get("updated_at"), "seed_round": (state.get("seed_round") or {}).get("id"),
                                                                 "metrics": {k: {"label": l, "meaning": m} for k, l, m in METRICS}, "players": players},
                                                                ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    (folder / "conceptual_mistakes.md").write_text(markdown(state, players), encoding="utf-8")
    rows = []
    def add(scope, pair, opponent, pid, s, games="all"):
        rows.append({"scope": scope, "pair": pair, "player_id": pid, "name": names[pid], "opponent_id": opponent, "games_subset": games, "games": s["games"],
                     **s["rates"], **{f"{k}_ticks": s["ticks"][k][0] for k, *_ in METRICS}, **{f"{k}_applicable_ticks": s["ticks"][k][1] for k, *_ in METRICS},
                     **{f"missed_shot_{b}": v for b, v in s["missed_shot_by_distance"].items()}, "angle_1s_median": s["angle_1s_median"], "pilot_flee_cos": s["pilot_flee_cos"]})
    for r in state["standings"]:
        if r.get("mistakes"):
            for subset in ("all", "won", "lost"): add("all", "", "", r["id"], r["mistakes"] if subset == "all" else r["mistakes"][subset], subset)
    for p in state["pairs"]:
        for pid in (p["a"], p["b"]):
            if (p.get("mistakes") or {}).get(pid):
                for subset in ("all", "won", "lost"):
                    add("pair", p["key"], p["b"] if pid == p["a"] else p["a"], pid, p["mistakes"][pid] if subset == "all" else p["mistakes"][pid][subset], subset)
    fields = ["scope", "pair", "player_id", "name", "opponent_id", "games_subset", "games", *(k for k, *_ in METRICS), *(f"{k}_ticks" for k, *_ in METRICS),
              *(f"{k}_applicable_ticks" for k, *_ in METRICS), *(f"missed_shot_{name}" for *_, name in BANDS), "angle_1s_median", "pilot_flee_cos"]
    with (folder / "conceptual_mistakes.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
