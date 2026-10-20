"""Resolve the current Drive roster and reuse only hash/protocol-matched pairs."""
import itertools
import os
from pathlib import Path
from common import ROOT, digest, now, pair_key, read, seeds, write
from drive import list_models, download

def main():
    config = read(ROOT / "arena.json")
    data = ROOT / "site/data"
    previous = read(data / "latest.json", {})
    models = ROOT / "runtime/models"; models.mkdir(parents=True, exist_ok=True)
    players = []
    for player in config["players"]:
        p = dict(player)
        try:
            files = list_models(p["folder"])
            if not files: p.update(status="waiting", message="等待上傳模型ZIP")
            elif len(files) != 1: p.update(status="ambiguous", message="有多個ZIP，請只保留一個最強模型；也可用Drive的管理版本功能取代檔案")
            else:
                target = models / (p["id"] + ".zip")
                download(files[0]["file_id"], target)
                p.update(files[0]); p.update(status="ready", sha256=digest(target), size_bytes=target.stat().st_size)
        except Exception as exc:
            p.update(status="error", message=str(exc)[:250])
        players.append(p)
    protocol = {"version": 1, "games_per_pair": 100, "seeds": seeds(config["seed_namespace"]),
                "deterministic": True, "seat_swap": True, "max_ticks": 1500, "fps": 50,
                "inference": "native SB3 policy.predict, CPU, one Torch thread",
                "ranking": "(wins + 0.5 draws) / games; equal scores share rank",
                "game_hash": read(ROOT / "fixture_manifest.json", {}).get("envs/game.py", "pending"),
                "engine_revision": digest(ROOT / "arena/worker.py")}
    jobs = []; active_pairs = []; old = {p["key"]: p for p in previous.get("pairs", [])}
    for a, b in itertools.combinations(players, 2):
        if a["status"] != "ready" or b["status"] != "ready": continue
        key = pair_key(a, b, protocol)
        cached = read(data / "pairs" / key / "result.json")
        if cached and cached.get("complete") and cached.get("key") == key:
            active_pairs.append(cached)
        else:
            jobs.append({"key": key, "a": a, "b": b, "seeds": protocol["seeds"]})
    history = read(data / "history.json", [])
    hashes = {p["id"]: p.get("sha256") for p in players}
    oldhashes = {p["id"]: p.get("sha256") for p in previous.get("players", [])}
    if previous.get("pairs") and hashes != oldhashes:
        history.append({"recorded_at": previous.get("updated_at"), "players": previous["players"],
                        "standings": previous.get("standings", []),
                        "pairs": [{k:v for k,v in p.items() if k not in ("games", "videos")} for p in previous["pairs"]]})
    write(data / "history.json", history)
    state = {"title": config["title"], "english_title": config["english_title"], "season": config["season"],
             "repository": config["repository"], "drive_folder": config["drive_folder"],
             "updated_at": now(), "checked_at": now(), "players": players, "pairs": active_pairs,
             "protocol": protocol, "queued_pairs": len(jobs), "standings": [], "total_games": 0,
             "status": "running" if jobs else "ready" if active_pairs else "waiting",
             "history_count": len(history), "cloud_run": os.getenv("GITHUB_RUN_ID"),
             "notice": "每10分鐘由GitHub雲端檢查模型；刷新讀取最新已發布結果，並非立即執行新比賽。排程可能延遲。"}
    write(data / "latest.json", state)
    write(ROOT / "runtime/plan.json", {"jobs": jobs, "protocol": protocol})
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out: out.write(f"changed={'true' if jobs else 'false'}\n")
    print(f"Roster: {sum(p['status']=='ready' for p in players)}/4 ready; {len(jobs)} changed pair(s).")

if __name__ == "__main__": main()
