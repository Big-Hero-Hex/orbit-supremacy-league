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

VERSION = 1
AIM = math.radians(opening.AIM_DEGREES)
EXPOSED = math.radians(10)
AWAY = math.radians(90)
SAMPLE_SECONDS = 2 / 50
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
                    c["losses"] += 1; c["losses_empty"] += me[5] == 0 and me[7] == 0
                    c["losses_facing_away"] += heading_error(me, them) > AWAY
            # A pilot either respawns or is killed (which ends the game); a
            # timeout in between counts as neither.
            end = next((x for x in timeline[k + 1:] if (x["kind"] == "kill" and x.get("target") == victim) or (x["kind"] == "respawn" and x["by"] == victim)), None)
            if end is None: continue
            if victim == opp:
                if end["kind"] == "kill": c["finish_success"] += 1; finish.append(end["tick"] - e["tick"])
                else: c["finish_fail"] += 1
            elif end["kind"] == "respawn": c["pilot_saved"] += 1
            else: c["pilot_rammed" if rammed else "pilot_shot"] += 1
        c["speed_sum"] = round(c["speed_sum"], 3); c["pilot_distance_sum"] = round(c["pilot_distance_sum"], 1)
        players[pid] = {**c, "finish_ticks": finish, "lost_first_ship_first": None if len(first) != 1 else int(pid in first)}
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
    return {"games": len(rows), "score_rate": score(rows), "rates": rates, "situations": situations, "loss_paths": paths, "counts": t}

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
            "behind": [s for s in skills if s["behind"]], "loss_paths": own["loss_paths"]}

def annotate(state):
    """Weakness findings for every player, overall and within each pair."""
    rows = {r["id"]: r.get("diagnostics") for r in state["standings"]}
    state["weaknesses"] = {pid: findings(own, [o for k, o in rows.items() if k != pid]) for pid, own in rows.items() if own and own["games"]}
    for pair in state["pairs"]:
        own = pair.get("diagnostics") or {}
        pair["weaknesses"] = {pid: findings(own[pid], [own[opp]]) for pid, opp in ((pair["a"], pair["b"]), (pair["b"], pair["a"]))
                              if own.get(pid, {}).get("games") and own.get(opp)}

def fmt(value, unit):
    if value is None: return "—"
    return f"{value * 100:.1f}%" if unit == "pct" else f"{value:.2f}s" if unit == "s" else f"{value:.1f}{' ' + unit if unit else ''}"

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
            lines += ["### 依估計失分排序的情境", "", "| 情境 | 發生局數 | 發生時積分率 | 未發生時積分率 | 估計失分 |", "|---|---:|---:|---:|---:|"]
            lines += [f"| {x['label']} | {x['games']} | {fmt(x['score_rate_when'], 'pct')} | {fmt(x['score_rate_otherwise'], 'pct')} | {x['points_lost']:.1f} |" for x in found["situations"]]
            lines.append("")
        lines += [f"### 輸掉的 {paths['lost_games']} 局怎麼輸", "",
                  f"- 最後飛行員被撞死 {paths['pilot_rammed']} 局、被射殺 {paths['pilot_shot']} 局",
                  f"- 開局未開火就先失船 {paths['silent_first_loss']} 局；先擊落對手卻仍輸 {paths['led_then_lost']} 局", ""]
        if found["behind"]:
            lines += ["### 明顯落後的技術指標", "", "| 指標 | 本人 | 聯賽最佳 | 其他人中位數 | 名次 |", "|---|---:|---:|---:|---:|"]
            lines += [f"| {x['label']} | {fmt(x['value'], x['unit'])} | {fmt(x['best'], x['unit'])} | {fmt(x['others_median'], x['unit'])} | {x['rank']}/{x['of']} |" for x in found["behind"]]
            lines.append("")
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
