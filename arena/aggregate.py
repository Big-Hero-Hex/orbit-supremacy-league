"""Trusted validation/statistics, with paired-seed rather than IID intervals."""
import csv
import math
from pathlib import Path
import random
import statistics
from common import read, write

METRICS = ("gun_shots","laser_shots","weapon_hits","pilot_weapon_kills","fire_requests","ship_ticks","pilot_ticks","empty_ammo_ticks","pickups","respawns","ejects","kills","ram_kills")

def interval(games, player, draws_half=False):
    clusters = {}
    for row in games:
        clusters.setdefault(row["seed"],[]).append(.5 if draws_half and row["winner"] is None else float(row["winner"] == player))
    values = [statistics.mean(v) for v in clusters.values()]
    if not values: return [None,None]
    rng = random.Random(91753)
    samples = sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(2000))
    return [samples[49],samples[1949]]

def stats(games, player):
    wins = sum(r["winner"]==player for r in games); draws = sum(r["winner"] is None for r in games); n = len(games)
    metrics = {k:sum(r["metrics"][player][k] for r in games) for k in METRICS}
    metrics["inference_mean_ms"] = statistics.mean(r["metrics"][player]["inference_mean_ms"] for r in games)
    received_ejects = sum(e.get("kind")=="eject" and e.get("target")==player for r in games for e in r.get("timeline",[]))
    first_ejected = 0; comebacks = 0; simultaneous = 0
    for r in games:
        ejects = [e for e in r.get("timeline",[]) if e.get("kind")=="eject"]
        if not ejects: continue
        tick = min(e["tick"] for e in ejects)
        targets = {e.get("target") for e in ejects if e["tick"]==tick}
        if len(targets)>1: simultaneous += 1
        elif player in targets:
            first_ejected += 1
            comebacks += int(r["winner"]==player)
    metrics.update(received_ejects=received_ejects, first_ejected_games=first_ejected,
                   first_ejected_rate=first_ejected/n, comeback_wins=comebacks,
                   simultaneous_first_eject_games=simultaneous,
                   pilot_respawn_rate=metrics["respawns"]/received_ejects if received_ejects else None)
    return {"games":n,"wins":wins,"draws":draws,"losses":n-wins-draws,"win_rate":wins/n,
            "points":wins+.5*draws,"score_rate":(wins+.5*draws)/n,"win_rate_ci95":interval(games,player),
            "score_rate_ci95":interval(games,player,True),"metrics":metrics}

def summarize(raw, job, protocol):
    rows = raw["games"]
    expected = {(s,seat) for s in job["seeds"] for seat in ("ship1","ship2")}
    if len(rows)!=100 or {(r["seed"],r["a_seat"]) for r in rows} != expected: raise ValueError("100場/seed/交換座位契約不符")
    for r in rows:
        if r["winner"] not in (job["a"]["id"],job["b"]["id"],None): raise ValueError("Invalid winner")
        if not isinstance(r["ticks"],int) or not 1<=r["ticks"]<=1500: raise ValueError("Invalid game length")
        expected_id=f"{r['seed']}-{r['a_seat']}"
        if r.get("id",expected_id)!=expected_id: raise ValueError("Invalid recording ID")
        if "replay" in r and r["replay"]!=f"replays/{expected_id}.json.gz": raise ValueError("Invalid replay path")
        if "audit" in r and r["audit"]!=f"audit/{expected_id}.npz": raise ValueError("Invalid audit path")
        for pid in (job["a"]["id"],job["b"]["id"]):
            for key in METRICS:
                value = r["metrics"][pid][key]
                if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100000: raise ValueError("Invalid metric")
    result = {"key":job["key"],"a":job["a"]["id"],"b":job["b"]["id"],"complete":True,
              "hashes":{p["id"]:p["sha256"] for p in (job["a"],job["b"])},
              "games":rows,"videos":raw["videos"],"model_info":raw["model_info"],"stats":{},"seats":{},"matches":[],
              "duration":{"mean":statistics.mean(r["seconds"] for r in rows),"median":statistics.median(r["seconds"] for r in rows),"longest":max(r["seconds"] for r in rows)},
              "ci_method":"2000 paired-physical-seed cluster bootstrap resamples; descriptive, fixed public season seeds"}
    for p in (job["a"],job["b"]):
        pid = p["id"]; result["stats"][pid] = stats(rows,pid)
        result["seats"][pid] = {seat:stats([r for r in rows if r["assignment"][seat]==pid],pid) for seat in ("ship1","ship2")}
    for seat in ("ship1","ship2"):
        subset = sorted((r for r in rows if r["a_seat"]==seat),key=lambda r:r["seed"])
        for start in range(0,50,10):
            chunk = subset[start:start+10]; a = sum(r["winner"]==result["a"] for r in chunk); b = sum(r["winner"]==result["b"] for r in chunk)
            result["matches"].append({"a_seat":seat,"seeds":[r["seed"] for r in chunk],"a_wins":a,"b_wins":b,"draws":10-a-b,"winner":result["a"] if a>b else result["b"] if b>a else None})
    return result

def export_csv(path, pairs):
    fields = ["pair","seed","ship1","ship2","winner","ticks","seconds","timeline_json"]
    fields += [s+"_"+m for s in ("ship1","ship2") for m in (*METRICS,"inference_mean_ms","inference_p95_ms")]
    with Path(path).open("w",encoding="utf-8-sig",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
        for pair in pairs:
            for r in pair["games"]:
                import json
                row=dict(pair=pair["key"],seed=r["seed"],ship1=r["assignment"]["ship1"],ship2=r["assignment"]["ship2"],winner=r["winner"] or "draw",ticks=r["ticks"],seconds=r["seconds"],timeline_json=json.dumps(r.get("timeline",[]),ensure_ascii=False))
                for seat in ("ship1","ship2"):
                    row.update({seat+"_"+m:r["metrics"][r["assignment"][seat]].get(m) for m in (*METRICS,"inference_mean_ms","inference_p95_ms")})
                writer.writerow(row)

def standings(players, pairs):
    rows = []
    for player in players:
        games = [r for pair in pairs if player["id"] in (pair["a"],pair["b"]) for r in pair["games"]]
        if not games: continue
        row = stats(games,player["id"]); row["id"] = player["id"]
        row["opponents"] = len([p for p in pairs if player["id"] in (p["a"],p["b"])])
        rows.append(row)
    rows.sort(key=lambda r:(-r["score_rate"],r["id"]))
    for i,r in enumerate(rows):
        r["rank"] = rows[i-1]["rank"] if i and r["score_rate"]==rows[i-1]["score_rate"] else i+1
    return rows
