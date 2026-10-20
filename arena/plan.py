"""Resolve the current Drive roster and reuse only hash/protocol-matched pairs."""
import itertools
import os
from datetime import datetime, timezone
from pathlib import Path
from common import ROOT, digest, now, pair_key, read, seeds, write,engine_revision
from drive import model_metadata, download
from participants import builtin_identity

def main():
    config = read(ROOT / "arena.json")
    data = ROOT / "site/data"
    previous = read(data / "latest.json", {})
    models = ROOT / "runtime/models"; models.mkdir(parents=True, exist_ok=True)
    players = []
    old_players = {p["id"]:p for p in previous.get("players",[])}
    downloads = 0
    for player in config["players"]:
        p = dict(player)
        try:
            if p.get('kind')=='official_rulebot':
                signature=builtin_identity(p['bot'],read(ROOT/'fixture_manifest.json',{}))
                p.update(status='ready',sha256=signature,size_bytes=0,filename='老師原版 '+p['code']+' 規則程式',message='官方固定規則對手 · 不需上傳ZIP',source='official_assignment')
                players.append(p)
                continue
            files = model_metadata(p["folder"])
            if not files: p.update(status="waiting", message="等待上傳模型ZIP")
            elif len(files) != 1: p.update(status="ambiguous", message="有多個ZIP，請只保留一個最強模型；也可用Drive的管理版本功能取代檔案")
            else:
                target = models / (p["id"] + ".zip")
                file=files[0]; old=old_players.get(p["id"],{})
                verified=old.get("content_verified_at")
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(verified.replace("Z","+00:00"))).total_seconds() if verified else float("inf")
                if (file.get("metadata_fingerprint") and file["metadata_fingerprint"]==old.get("metadata_fingerprint")
                        and old.get("sha256") and old.get("status")=="ready" and age<86400):
                    p.update(file);p.update(status="ready",sha256=old["sha256"],size_bytes=old["size_bytes"],content_verified_at=verified)
                else:
                    download(file["file_id"], target);downloads+=1
                    p.update(file);p.update(status="ready",sha256=digest(target),size_bytes=target.stat().st_size,content_verified_at=now())
        except Exception as exc:
            p.update(status="error", message=str(exc)[:250])
        players.append(p)
    protocol = {"version": 1, "games_per_pair": 100, "seeds": seeds(config["seed_namespace"]),
                "deterministic": True, "seat_swap": True, "max_ticks": 1500, "fps": 50,
                "inference": "native SB3 policy.predict, CPU, one Torch thread",
                "ranking": "(wins + 0.5 draws) / games; equal scores share rank",
                "game_hash": read(ROOT / "fixture_manifest.json", {}).get("envs/game.py", "pending"),
                "engine_revision": engine_revision(ROOT)}
    jobs = []; active_pairs = []; old = {p["key"]: p for p in previous.get("pairs", [])}
    for a, b in itertools.combinations(players, 2):
        if a["status"] != "ready" or b["status"] != "ready": continue
        key = pair_key(a, b, protocol)
        cached = old.get(key)
        if cached and cached.get("complete") and cached.get("key") == key:
            active_pairs.append(cached)
        else:
            jobs.append({"key": key, "a": a, "b": b, "seeds": protocol["seeds"]})
    # When a changed player needs a match, retrieve the unchanged opponent only
    # then. Never mix a newly replaced file into a previously frozen match.
    required={p["id"]:p for job in jobs for p in (job["a"],job["b"])}
    for pid,p in required.items():
        if p.get('kind')=='official_rulebot':continue
        target=models/(pid+".zip")
        if not target.exists():
            download(p["file_id"],target);downloads+=1
            if digest(target)!=p["sha256"]:raise ValueError("模型在配對凍結後換版，保留上一份結果並等待下一次檢查")
    def comparable(ps):
        return [{k:p.get(k) for k in ("id","status","sha256","filename","message","metadata_fingerprint","content_verified_at")} for p in ps]
    publish=bool(jobs or comparable(players)!=comparable(previous.get("players",[])) or previous.get("protocol")!=protocol or os.getenv("GITHUB_EVENT_NAME")=="push")
    state = {"title": config["title"], "english_title": config["english_title"], "season": config["season"],
             "repository": config["repository"], "drive_folder": config["drive_folder"],
             "updated_at": now(), "checked_at": now(), "players": players, "pairs": active_pairs,
             "protocol": protocol, "queued_pairs": len(jobs), "standings": [], "total_games": 0,
             "status": "running" if jobs else "ready" if active_pairs else "waiting",
             "history_count": previous.get("history_count",0), "cloud_run": os.getenv("GITHUB_RUN_ID"),
             "expected_pairs":len(players)*(len(players)-1)//2,"expected_games":len(players)*(len(players)-1)//2*100,
             "worker_source_sha256":digest(ROOT/'arena/worker.py'),
             "controller_contracts":{"model":"native SB3 policy.predict, deterministic, raw84, CPU one thread","official_rulebot":"老師原版rusher_bot_action/sniper_bot_action，直接使用raw84，僅適配predict介面；非神經模型"},
             "notice": "每5分鐘輕量檢查Drive修訂資訊；只在換版時下載並比賽，沒有變更不重錄或重發網站。每天有一次SHA內容複核。排程可能延遲。"}
    write(data / "latest.json", state)
    write(ROOT / "runtime/planned_state.json",state)
    write(ROOT / "runtime/plan.json", {"jobs": jobs, "protocol": protocol})
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out: out.write(f"changed={'true' if jobs else 'false'}\npublish={'true' if publish else 'false'}\n")
    print(f"Roster: {sum(p['status']=='ready' for p in players)}/{len(players)} ready; {len(jobs)} changed pair(s); ZIP downloads={downloads}; publish={publish}.")

if __name__ == "__main__": main()
