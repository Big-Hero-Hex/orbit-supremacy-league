"""Weakness diagnostics: shooting, exposure, pilot phase, finishing and turning.

Same boundary as opening.py: reads only stored frames, the event timeline and
the official counters on the trusted host, never a model or the engine, so the
locked worker core and every cached pair stay valid. All figures describe what
happened; a score-rate gap shows where points were lost, not proof of cause.
"""
import bisect
import csv
import json
import math
import statistics
from pathlib import Path
import opening
from opening import fired, heading_error, read_replay, wrap

VERSION = 2
AIM = math.radians(opening.AIM_DEGREES)
EXPOSED = math.radians(10)
AWAY = math.radians(90)
SAMPLE_SECONDS = 2 / 50
PRESSURE_TICKS = 75
COUNTERS = ("ship_samples", "aim_on", "speed_samples", "speed_sum", "turn_flips", "exposed_samples", "exposed_on",
            "shots_seen", "shots_aimed", "asteroid_hits", "losses", "losses_empty", "losses_facing_away",
            "pilot_saved", "pilot_shot", "pilot_rammed", "pilot_samples", "pilot_distance_sum", "finish_success", "finish_fail")

def game_diagnostics(row, record):
    frames = record["frames"]
    if not frames or any(len(f["s"]) != 2 or any(len(s) != 9 for s in f["s"]) for f in frames): raise ValueError("Unexpected frame layout")
    if any(b["t"] <= a["t"] for a, b in zip(frames, frames[1:])): raise ValueError("Frames out of order")
    times = [f["t"] for f in frames]; timeline = row["timeline"]; players = {}
    ejects = [e for e in timeline if e["kind"] == "eject"]
    first = {e.get("target") for e in ejects if e["tick"] == ejects[0]["tick"]} if ejects else set()
    for seat, sid in enumerate(("ship1", "ship2")):
        pid = row["assignment"][sid]; opp = row["assignment"]["ship2" if seat == 0 else "ship1"]
        c = dict.fromkeys(COUNTERS, 0); finish = []; last = 0
        # Ticks of each failure, so a report can link straight to the moment.
        moments = {"empty_loss": [], "away_loss": [], "finish_fail": [], "rammed": None,
                   "asteroid": next((e["tick"] for e in timeline if e["kind"] == "asteroid_hit" and e["by"] == pid), None)}
        me, them = frames[0]["s"][seat], frames[0]["s"][1 - seat]
        spawn = {"error_deg": round(math.degrees(heading_error(me, them)), 1), "distance": round(math.hypot(them[0] - me[0], them[1] - me[1]))}
        # Opening pressure: share of the first 1.5 s that a loaded enemy ship had
        # its nose on this player. A fixed window keeps it independent of when
        # the player fires or dies, so it can be compared with those outcomes.
        aimed = pressured = 0
        for f in frames:
            if f["t"] > PRESSURE_TICKS: break
            me, them = f["s"][seat], f["s"][1 - seat]
            if me[3] and not me[4] and them[3] and not them[4] and (them[5] or them[7]):
                pressured += 1; aimed += heading_error(them, me) <= EXPOSED
        spawn["face_tick"] = next((f["t"] for f in frames if f["s"][seat][3] and not f["s"][seat][4] and f["s"][1 - seat][3]
                                   and heading_error(f["s"][seat], f["s"][1 - seat]) <= AIM), None)
        spawn["opening_pressure"] = round(aimed / pressured, 3) if pressured else None
        for p, f in zip(frames, frames[1:]):
            prev, me, them = p["s"][seat], f["s"][seat], f["s"][1 - seat]
            if not (me[3] and them[3]): continue
            if me[4]:
                if not them[4]: c["pilot_samples"] += 1; c["pilot_distance_sum"] += math.hypot(them[0] - me[0], them[1] - me[1])
                continue
            c["ship_samples"] += 1; c["aim_on"] += heading_error(me, them) <= AIM
            if prev[3] and not prev[4]:
                # Ship in both frames, so no respawn jump in position or heading.
                ticks = f["t"] - p["t"]
                c["speed_samples"] += 1; c["speed_sum"] += math.hypot(me[0] - prev[0], me[1] - prev[1]) / ticks
                step = wrap(me[2] - prev[2]); direction = (step > .01) - (step < -.01)
                if direction:
                    c["turn_flips"] += bool(last) and direction != last; last = direction
                shots = fired(prev, me, ticks)
                if shots:
                    c["shots_seen"] += shots; c["shots_aimed"] += shots * (heading_error(prev, p["s"][1 - seat]) <= AIM)
            if not them[4] and (them[5] or them[7]):
                c["exposed_samples"] += 1; c["exposed_on"] += heading_error(them, me) <= EXPOSED
        c["asteroid_hits"] = sum(e["kind"] == "asteroid_hit" and e["by"] == pid for e in timeline)
        rammed = row["metrics"][opp]["ram_kills"] > 0
        for k, e in enumerate(timeline):
            if e["kind"] != "eject" or e.get("target") not in (pid, opp): continue
            victim = e["target"]
            if victim == pid:
                i = bisect.bisect_left(times, e["tick"]) - 1
                if i >= 0:
                    me, them = frames[i]["s"][seat], frames[i]["s"][1 - seat]
                    empty, away = me[5] == 0 and me[7] == 0, heading_error(me, them) > AWAY
                    c["losses"] += 1; c["losses_empty"] += empty; c["losses_facing_away"] += away
                    if empty: moments["empty_loss"].append(e["tick"])
                    if away: moments["away_loss"].append(e["tick"])
            # A pilot either respawns or is killed (which ends the game); a
            # timeout in between counts as neither.
            end = next((x for x in timeline[k + 1:] if (x["kind"] == "kill" and x.get("target") == victim) or (x["kind"] == "respawn" and x["by"] == victim)), None)
            if end is None: continue
            if victim == opp:
                if end["kind"] == "kill": c["finish_success"] += 1; finish.append(end["tick"] - e["tick"])
                else: c["finish_fail"] += 1; moments["finish_fail"].append(e["tick"])
            elif end["kind"] == "respawn": c["pilot_saved"] += 1
            else:
                c["pilot_rammed" if rammed else "pilot_shot"] += 1
                if rammed: moments["rammed"] = end["tick"]
        c["speed_sum"] = round(c["speed_sum"], 3); c["pilot_distance_sum"] = round(c["pilot_distance_sum"], 1)
        players[pid] = {**c, "finish_ticks": finish, "lost_first_ship_first": None if len(first) != 1 else int(pid in first),
                        "spawn": spawn, "moments": moments}
    return {"version": VERSION, "players": players}

def attach(pair, folder):
    """Fill missing per-game diagnostics from the pair's stored recordings."""
    folder = Path(folder); failed = 0
    for row in pair["games"]:
        if (row.get("diagnostics") or {}).get("version") == VERSION: continue
        try: row["diagnostics"] = game_diagnostics(row, read_replay(folder / row["replay"]))
        except Exception: row.pop("diagnostics", None); failed += 1
    pair["diagnostics"] = {pid: summary(pair["games"], pid) for pid in (pair["a"], pair["b"])}
    return failed

def ready(row):
    return (row.get("diagnostics") or {}).get("version") == VERSION

def first_loss(row, player):
    o = ((row.get("opening") or {}).get("players") or {}).get(player)
    return o["first_loss"] if o else None

def silent(row, player):
    o = ((row.get("opening") or {}).get("players") or {}).get(player)
    return bool(o and o["first_loss"] is not None and o["shots_before_loss"] == 0)

def opponent_first(row, player):
    return (row.get("opening") or {}).get("version") == opening.VERSION and opening.fired_first(row, player) == 0

# Turning points that happen before a game is decided. Terminal outcomes such
# as a rammed pilot always mean a loss, so they are reported as loss paths.
SITUATIONS = (
    ("silent_first_loss", "未開火就先失船", lambda r, p, d: silent(r, p)),
    ("opponent_fired_first", "被對手搶先開火", lambda r, p, d: opponent_first(r, p)),
    ("lost_first_ship_first", "先被擊落（對手還沒失船）", lambda r, p, d: d["lost_first_ship_first"] == 1),
    ("finish_failed", "擊落對手後沒補刀（對手復活）", lambda r, p, d: d["finish_fail"] > 0),
    ("loss_while_empty", "空彈且無雷射時被擊落", lambda r, p, d: d["losses_empty"] > 0),
    ("loss_facing_away", "背對敵人時被擊落", lambda r, p, d: d["losses_facing_away"] > 0),
    ("shot_into_asteroid", "子彈打到小行星", lambda r, p, d: d["asteroid_hits"] > 0))

# Tick a situation's replay link jumps to (two seconds earlier is shown).
MOMENTS = {
    "silent_first_loss": lambda r, p, d: first_loss(r, p),
    "opponent_fired_first": lambda r, p, d: next(v["first_shot"] for k, v in r["opening"]["players"].items() if k != p),
    "lost_first_ship_first": lambda r, p, d: first_loss(r, p),
    "finish_failed": lambda r, p, d: d["moments"]["finish_fail"][0],
    "loss_while_empty": lambda r, p, d: d["moments"]["empty_loss"][0],
    "loss_facing_away": lambda r, p, d: d["moments"]["away_loss"][0],
    "shot_into_asteroid": lambda r, p, d: d["moments"]["asteroid"]}
SPAWN_BUCKETS = ((0, 45), (45, 90), (90, 135), (135, 181))
PRESSURE_BUCKETS = ((0, .2, "低（<20%）"), (.2, .5, "中（20–50%）"), (.5, 1.01, "高（≥50%）"))

# (key, label, which direction is better, unit). Speed and turning style are
# shown for context without ranking: neither direction is better by itself.
SKILLS = (
    ("accuracy", "命中率（武器命中玩家／實際發射）", "high", "pct"),
    ("enemy_accuracy", "被命中率（對手命中自己／對手發射）", "low", "pct"),
    ("shot_discipline", "開火時機頭對準敵人（±15°）", "high", "pct"),
    ("asteroid_share", "子彈打到小行星比例", "low", "pct"),
    ("aim_share", "船型時機頭對準敵人（±15°）", "high", "pct"),
    ("exposed_share", "被持彈敵人瞄準（±10°）的時間", "low", "pct"),
    ("loss_empty_share", "失船時空彈且無雷射", "low", "pct"),
    ("loss_facing_away_share", "失船時背對敵人（>90°）", "low", "pct"),
    ("pilot_survival", "飛行員存活到復活", "high", "pct"),
    ("pilot_rammed_share", "飛行員死亡中被撞死", "low", "pct"),
    ("pilot_distance", "飛行員與敵船平均距離", "high", "px"),
    ("finish_rate", "擊落對手後補刀成功", "high", "pct"),
    ("finish_time_s", "補刀時間（中位數）", "low", "s"),
    ("speed", "船型平均速度", None, "px/s"),
    ("turn_flips_per_s", "轉向來回切換（每秒）", None, "/s"))

def summary(games, player):
    rows = [r for r in games if ready(r) and player in r["diagnostics"]["players"]]
    mine = [r["diagnostics"]["players"][player] for r in rows]
    t = {k: sum(o[k] for o in mine) for k in COUNTERS}
    def ratio(a, b): return a / b if b else None
    def shots(r, pid): return r["metrics"][pid]["gun_shots"] + r["metrics"][pid]["laser_shots"]
    def other(r): return next(v for v in r["assignment"].values() if v != player)
    def score(rs): return sum(1 if r["winner"] == player else .5 if r["winner"] is None else 0 for r in rs) / len(rs) if rs else None
    finish = [x for o in mine for x in o["finish_ticks"]]
    deaths = t["pilot_shot"] + t["pilot_rammed"]
    rates = {"accuracy": ratio(sum(r["metrics"][player]["weapon_hits"] for r in rows), sum(shots(r, player) for r in rows)),
             "enemy_accuracy": ratio(sum(r["metrics"][other(r)]["weapon_hits"] for r in rows), sum(shots(r, other(r)) for r in rows)),
             "shot_discipline": ratio(t["shots_aimed"], t["shots_seen"]),
             "asteroid_share": ratio(t["asteroid_hits"], sum(r["metrics"][player]["gun_shots"] for r in rows)),
             "aim_share": ratio(t["aim_on"], t["ship_samples"]), "exposed_share": ratio(t["exposed_on"], t["exposed_samples"]),
             "loss_empty_share": ratio(t["losses_empty"], t["losses"]), "loss_facing_away_share": ratio(t["losses_facing_away"], t["losses"]),
             "pilot_survival": ratio(t["pilot_saved"], t["pilot_saved"] + deaths), "pilot_rammed_share": ratio(t["pilot_rammed"], deaths),
             "pilot_distance": ratio(t["pilot_distance_sum"], t["pilot_samples"]),
             "finish_rate": ratio(t["finish_success"], t["finish_success"] + t["finish_fail"]),
             "finish_time_s": statistics.median(finish) / 50 if finish else None,
             "speed": ratio(t["speed_sum"] * 50, t["speed_samples"]), "turn_flips_per_s": ratio(t["turn_flips"], t["speed_samples"] * SAMPLE_SECONDS)}
    situations = {}
    for key, label, happened in SITUATIONS:
        flags = [happened(r, player, r["diagnostics"]["players"][player]) for r in rows]
        hit = [r for r, f in zip(rows, flags) if f]; rest = [r for r, f in zip(rows, flags) if not f]
        with_, without = score(hit), score(rest)
        situations[key] = {"games": len(hit), "score_rate_when": with_, "score_rate_otherwise": without,
                           "points_lost": len(hit) * (without - with_) if hit and rest else None}
    lost = [r for r in rows if r["winner"] not in (player, None)]
    paths = {"lost_games": len(lost), "pilot_rammed": sum(r["metrics"][other(r)]["ram_kills"] > 0 for r in lost),
             "silent_first_loss": sum(silent(r, player) for r in lost),
             "led_then_lost": sum(r["diagnostics"]["players"][player]["lost_first_ship_first"] == 0 for r in lost)}
    paths["pilot_shot"] = len(lost) - paths["pilot_rammed"]
    def group(rs, label):
        ships = [r for r in rs if first_loss(r, player) is not None]; face = [r["diagnostics"]["players"][player]["spawn"]["face_tick"] for r in rs]
        return {"label": label, "games": len(rs), "score_rate": score(rs), "lost_first_ship": len(ships),
                "silent_loss_rate": ratio(sum(silent(r, player) for r in ships), len(ships)),
                "face_median_s": statistics.median(x / 50 for x in face if x is not None) if any(x is not None for x in face) else None}
    spawn = lambda r: r["diagnostics"]["players"][player]["spawn"]
    conditions = {"spawn": [group([r for r in rows if lo <= spawn(r)["error_deg"] < hi], f"{lo}–{min(hi, 180)}°") for lo, hi in SPAWN_BUCKETS],
                  "pressure": [group([r for r in rows if spawn(r)["opening_pressure"] is not None and lo <= spawn(r)["opening_pressure"] < hi], label) for lo, hi, label in PRESSURE_BUCKETS]}
    return {"games": len(rows), "score_rate": score(rows), "rates": rates, "situations": situations, "loss_paths": paths,
            "opening_conditions": conditions, "counts": t}

def findings(own, references):
    """Rank one player's situations by points lost and skills against references."""
    skills = []
    for key, label, better, unit in SKILLS:
        value = own["rates"].get(key); others = [r["rates"][key] for r in references if r and r["rates"].get(key) is not None]
        if value is None or not others or better is None: continue
        sign = 1 if better == "high" else -1; everyone = others + [value]
        rank = 1 + sum(sign * o > sign * value for o in others)
        skills.append({"metric": key, "label": label, "unit": unit, "value": value, "best": max(everyone, key=lambda x: sign * x),
                       "others_median": statistics.median(others), "rank": rank, "of": len(everyone),
                       "behind": rank == len(everyone) or (len(everyone) >= 4 and rank == len(everyone) - 1)})
    situations = sorted(({"situation": key, "label": label, **own["situations"][key]} for key, label, _ in SITUATIONS
                         if (own["situations"][key]["points_lost"] or 0) > 0 and own["situations"][key]["games"] >= 3),
                        key=lambda s: -s["points_lost"])
    return {"games": own["games"], "situations": situations, "skills": skills,
            "behind": [s for s in skills if s["behind"]], "loss_paths": own["loss_paths"], "opening_conditions": own.get("opening_conditions")}

def examples(games, player, key, limit=3):
    """Replays where a situation happened, lost games first: (pair, game, seconds)."""
    happened = dict((k, f) for k, _, f in SITUATIONS)[key]
    hits = [(pair, r) for pair, r in games if ready(r) and happened(r, player, r["diagnostics"]["players"][player])]
    hits.sort(key=lambda x: (x[1]["winner"] == player, x[1]["seed"], x[1]["a_seat"]))
    out = []
    for pair, r in hits[:limit]:
        tick = MOMENTS[key](r, player, r["diagnostics"]["players"][player])
        out.append({"pair": pair, "game_id": r["id"], "at": max(0, round((tick or 0) / 50 - 2, 1))})
    return out

def rammed_examples(games, player, limit=3):
    hits = [(pair, r) for pair, r in games if ready(r) and r["diagnostics"]["players"][player]["moments"]["rammed"]]
    hits.sort(key=lambda x: (x[1]["seed"], x[1]["a_seat"]))
    return [{"pair": pair, "game_id": r["id"], "at": max(0, round(r["diagnostics"]["players"][player]["moments"]["rammed"] / 50 - 2, 1))} for pair, r in hits[:limit]]

def with_examples(found, games, player):
    for s in found["situations"]: s["examples"] = examples(games, player, s["situation"])
    found["loss_paths"] = {**found["loss_paths"], "rammed_examples": rammed_examples(games, player)}
    return found

# Tracked across model versions: (key, label, which direction is better).
TRACKED = (("score_rate", "積分率", "high"), ("silent_loss_rate", "未開火先失船", "low"), ("fired_first_rate", "搶先開火率", "high"),
           ("aim_share", "船型時對準敵人", "high"), ("accuracy", "命中率", "high"), ("enemy_accuracy", "被命中率", "low"),
           ("exposed_share", "被持彈敵人瞄準的時間", "low"), ("loss_facing_away_share", "失船時背對敵人", "low"),
           ("loss_empty_share", "失船時空彈", "low"), ("asteroid_share", "子彈打到小行星", "low"),
           ("pilot_survival", "飛行員存活到復活", "high"), ("pilot_rammed_share", "飛行員死亡中被撞死", "low"), ("finish_rate", "擊落後補刀成功", "high"))
KEEP_VERSIONS = 12

def tracked(score_rate, opening_summary, diag):
    values = {"score_rate": score_rate, "silent_loss_rate": (opening_summary or {}).get("silent_loss_rate"),
              "fired_first_rate": (opening_summary or {}).get("fired_first_rate")}
    return {k: values.get(k, diag["rates"].get(k)) for k, *_ in TRACKED}

def track_versions(previous, state):
    """One entry per player model per seed round; a repeat publish refreshes it."""
    versions = {pid: list(v) for pid, v in (previous or {}).items()}
    sha = {p["id"]: p.get("sha256") for p in state["players"]}; round_id = (state.get("seed_round") or {}).get("id")
    for r in state["standings"]:
        if not (r.get("diagnostics") or {}).get("games"): continue
        pid = r["id"]; opponents = {}
        for pair in state["pairs"]:
            if pid not in (pair["a"], pair["b"]) or not (pair.get("diagnostics") or {}).get(pid, {}).get("games"): continue
            opp = pair["b"] if pair["a"] == pid else pair["a"]
            own = pair["diagnostics"][pid]
            opponents[opp] = {"sha256": (pair.get("hashes") or {}).get(opp), "games": own["games"],
                              "metrics": tracked(own["score_rate"], (pair.get("opening") or {}).get(pid), own)}
        entry = {"sha256": sha.get(pid), "seed_round": round_id, "first_seen": state.get("updated_at"), "updated_at": state.get("updated_at"),
                 "games": r["diagnostics"]["games"], "metrics": tracked(r["diagnostics"]["score_rate"], r.get("opening"), r["diagnostics"]), "opponents": opponents}
        history = versions.setdefault(pid, [])
        if history and history[-1]["sha256"] == entry["sha256"] and history[-1]["seed_round"] == entry["seed_round"]:
            entry["first_seen"] = history[-1]["first_seen"]; history[-1] = entry
        else: history.append(entry)
        del history[:-KEEP_VERSIONS]
    return versions

def compare(before, after):
    rows = []
    for key, label, better in TRACKED:
        a, b = before.get(key), after.get(key)
        change = None if a is None or b is None else b - a
        rows.append({"metric": key, "label": label, "before": a, "after": b, "change": change,
                     "improved": None if not change else (change > 0) == (better == "high")})
    return rows

def comparison(history):
    """Latest version against the previous different model, plus same-model noise."""
    if not history: return None
    now = history[-1]; meta = lambda h: {k: h[k] for k in ("sha256", "seed_round", "games", "first_seen")}
    before = next((h for h in reversed(history[:-1]) if h["sha256"] != now["sha256"]), None)
    same = next((h for h in reversed(history[:-1]) if h["sha256"] == now["sha256"]), None)
    out = {"current": meta(now), "previous_version": None, "same_model_earlier_round": None}
    if before:
        out["previous_version"] = {**meta(before), "same_round": before["seed_round"] == now["seed_round"], "rows": compare(before["metrics"], now["metrics"]),
                                   "opponents": {opp: {"same_opponent_version": before["opponents"][opp]["sha256"] == o["sha256"],
                                                       "rows": compare(before["opponents"][opp]["metrics"], o["metrics"])}
                                                 for opp, o in now["opponents"].items() if opp in before["opponents"]}}
    if same: out["same_model_earlier_round"] = {**meta(same), "rows": compare(same["metrics"], now["metrics"])}
    return out

def annotate(state, previous=None):
    """Weakness findings for every player, overall and within each pair, with
    replay examples and the comparison against the player's previous model."""
    rows = {r["id"]: r.get("diagnostics") for r in state["standings"]}
    games = {pid: [(p["key"], r) for p in state["pairs"] if pid in (p["a"], p["b"]) for r in p["games"]] for pid in rows}
    state["diagnostic_versions"] = track_versions((previous or {}).get("diagnostic_versions"), state)
    state["weaknesses"] = {pid: {**with_examples(findings(own, [o for k, o in rows.items() if k != pid]), games[pid], pid),
                                 "version_comparison": comparison(state["diagnostic_versions"].get(pid, []))}
                           for pid, own in rows.items() if own and own["games"]}
    for pair in state["pairs"]:
        own = pair.get("diagnostics") or {}
        pair["weaknesses"] = {pid: with_examples(findings(own[pid], [own[opp]]), [(pair["key"], r) for r in pair["games"]], pid)
                              for pid, opp in ((pair["a"], pair["b"]), (pair["b"], pair["a"])) if own.get(pid, {}).get("games") and own.get(opp)}

def fmt(value, unit):
    if value is None: return "—"
    return f"{value * 100:.1f}%" if unit == "pct" else f"{value:.2f}s" if unit == "s" else f"{value:.1f}{' ' + unit if unit else ''}"

def site_url(state):
    owner, repo = state.get("repository", "/").split("/", 1)
    return f"https://{owner.lower()}.github.io/{repo}/"

def links(state, items):
    return " ".join(f"[▶{i}]({site_url(state)}#game={x['pair']}/{x['game_id']}@{x['at']})" for i, x in enumerate(items, 1)) or "—"

def change_text(row):
    if row["change"] is None: return "—"
    verdict = {True: " 改善", False: " 退步"}.get(row["improved"], "")
    return f"{row['change'] * 100:+.1f} 個百分點{verdict}"

def report_markdown(state):
    people = {p["id"]: p for p in state["players"]}; standing = {r["id"]: r for r in state["standings"]}
    lines = ["# OSL 弱點診斷報告（自動產生）", "",
             f"資料：{state.get('total_games', 0)} 場已完成對局 · 發布 {state.get('updated_at', '')} · 開局輪 {(state.get('seed_round') or {}).get('id', '—')}", "",
             "由已錄製的狀態重播與官方計數推得，不重跑比賽、不載入模型。「估計失分」＝該情境發生局數 ×（未發生時積分率 − 發生時積分率），"
             "只描述分數在哪裡流失，不是因果證明；情境之間會重疊，不能相加。技術指標的名次是與其他參賽者（含老師規則對手）比較。", ""]
    for pid, found in sorted(state.get("weaknesses", {}).items(), key=lambda kv: standing[kv[0]]["rank"]):
        s = standing[pid]; paths = found["loss_paths"]
        lines += [f"## {people[pid]['name']}（{pid}）· 第 {s['rank']} 名 · 積分率 {s['score_rate'] * 100:.1f}% · {found['games']} 局", ""]
        if found["situations"]:
            lines += ["### 依估計失分排序的情境", "", "| 情境 | 發生局數 | 發生時積分率 | 未發生時積分率 | 估計失分 | 重播（失誤前2秒） |", "|---|---:|---:|---:|---:|---|"]
            lines += [f"| {x['label']} | {x['games']} | {fmt(x['score_rate_when'], 'pct')} | {fmt(x['score_rate_otherwise'], 'pct')} | {x['points_lost']:.1f} | {links(state, x.get('examples', []))} |" for x in found["situations"]]
            lines.append("")
        lines += [f"### 輸掉的 {paths['lost_games']} 局怎麼輸", "",
                  f"- 最後飛行員被撞死 {paths['pilot_rammed']} 局、被射殺 {paths['pilot_shot']} 局（被撞重播：{links(state, paths.get('rammed_examples', []))}）",
                  f"- 開局未開火就先失船 {paths['silent_first_loss']} 局；先擊落對手卻仍輸 {paths['led_then_lost']} 局", ""]
        if found["behind"]:
            lines += ["### 明顯落後的技術指標", "", "| 指標 | 本人 | 聯賽最佳 | 其他人中位數 | 名次 |", "|---|---:|---:|---:|---:|"]
            lines += [f"| {x['label']} | {fmt(x['value'], x['unit'])} | {fmt(x['best'], x['unit'])} | {fmt(x['others_median'], x['unit'])} | {x['rank']}/{x['of']} |" for x in found["behind"]]
            lines.append("")
        conditions = found.get("opening_conditions")
        if conditions:
            lines += ["### 開局條件", "", "出生朝向＝出生時機頭偏離對手的角度；開局被瞄準＝開賽頭 1.5 秒內，被持彈敵人瞄準（±10°）的時間比例。", "",
                      "| 分組 | 局數 | 未開火先失船 | 對準所需時間（中位） | 積分率 |", "|---|---:|---:|---:|---:|"]
            lines += [f"| {kind} {g['label']} | {g['games']} | {fmt(g['silent_loss_rate'], 'pct')} | {fmt(g['face_median_s'], 's')} | {fmt(g['score_rate'], 'pct')} |"
                      for kind, groups in (("出生朝向", conditions["spawn"]), ("開局被瞄準", conditions["pressure"])) for g in groups if g["games"]]
            lines.append("")
        versions = found.get("version_comparison") or {}
        before = versions.get("previous_version")
        if before:
            lines += [f"### 與上一版比較（上一版 {before['sha256'][:12]} · 開局輪 {before['seed_round']} → 目前 {versions['current']['sha256'][:12]} · {versions['current']['seed_round']}）", "",
                      "不同開局輪或對手也換版時，變化不能全歸因於模型。" if not before["same_round"] else "同一開局輪。", "",
                      "| 指標 | 上一版 | 目前 | 變化 |", "|---|---:|---:|---|"]
            lines += [f"| {x['label']} | {fmt(x['before'], 'pct')} | {fmt(x['after'], 'pct')} | {change_text(x)} |" for x in before["rows"]]
            lines.append("")
        elif versions:
            lines += ["### 與上一版比較", "", "尚無上一版的診斷紀錄；下一次換版後會自動比較。", ""]
    lines += ["## 資料檔", "", "- `data/diagnostics_log.csv`：逐局×選手原始計數", "- `data/weakness_summary.csv`：各範圍比例與情境失分",
              "- `data/opening_log.csv`、`data/opening_summary.csv`：開局失船前火力", "- `data/weakness_report.json`：本報告的機器可讀版本", ""]
    return "\n".join(lines)

LOG_FIELDS = ["pair", "game_id", "seed", "player_id", "name", "opponent_id", "seat", "result", *COUNTERS, "finish_ticks", "lost_first_ship_first"]

def export(folder, state):
    """UTF-8 BOM per-game log and summary, plus the readable weakness report."""
    folder = Path(folder); people = {p["id"]: p for p in state["players"]}; log = []; table = []
    for pair in state["pairs"]:
        for r in pair["games"]:
            if not ready(r): continue
            for seat, pid in r["assignment"].items():
                d = r["diagnostics"]["players"][pid]
                log.append({"pair": pair["key"], "game_id": r["id"], "seed": r["seed"], "player_id": pid, "name": people[pid]["name"],
                            "opponent_id": next(v for v in r["assignment"].values() if v != pid), "seat": seat,
                            "result": "draw" if r["winner"] is None else "win" if r["winner"] == pid else "loss",
                            **{k: d[k] for k in COUNTERS}, "finish_ticks": ";".join(map(str, d["finish_ticks"])), "lost_first_ship_first": d["lost_first_ship_first"]})
    def flat(scope, key, pid, s):
        row = {"scope": scope, "pair": key, "player_id": pid, "name": people[pid]["name"], "games": s["games"], "score_rate": s["score_rate"], **s["rates"]}
        for name, x in s["situations"].items(): row.update({f"{name}_games": x["games"], f"{name}_points_lost": x["points_lost"]})
        return row
    table += [flat("all", "", r["id"], r["diagnostics"]) for r in state["standings"] if r.get("diagnostics")]
    table += [flat("pair", p["key"], pid, p["diagnostics"][pid]) for p in state["pairs"] for pid in (p["a"], p["b"]) if (p.get("diagnostics") or {}).get(pid)]
    fields = ["scope", "pair", "player_id", "name", "games", "score_rate", *(k for k, *_ in SKILLS)]
    fields += [f"{k}_{x}" for k, *_ in SITUATIONS for x in ("games", "points_lost")]
    for name, rows, columns in (("diagnostics_log.csv", log, LOG_FIELDS), ("weakness_summary.csv", table, fields)):
        with (folder / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
    report = {"generated_at": state.get("updated_at"), "total_games": state.get("total_games"), "seed_round": (state.get("seed_round") or {}).get("id"),
              "method": "Descriptive. points_lost = games_with_situation x (score_rate_otherwise - score_rate_when); situations overlap, do not add them.",
              "players": {pid: {"name": people[pid]["name"], **found} for pid, found in state.get("weaknesses", {}).items()}}
    (folder / "weakness_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    (folder / "weakness_report.md").write_text(report_markdown(state), encoding="utf-8")
