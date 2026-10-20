"""Cloud-only execution and allow-listed publication; never a self-hosted runner."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from aggregate import export_csv, export_tables, standings, summarize
from common import ROOT, next_check, now, read, write

def main():
    plan = read(ROOT/"runtime/plan.json")
    state = read(ROOT/"site/data/latest.json")
    failures = []
    for job in plan["jobs"]:
        temporary = ROOT/"runtime"/job["key"]
        temporary.mkdir(exist_ok=True)
        temporary.chmod(0o777)
        write(ROOT/"runtime/job.json",job)
        command = ["docker","run","--rm","--network=none","--read-only","--cap-drop=ALL",
                   "--security-opt=no-new-privileges","--pids-limit=128","--memory=4g","--cpus=2",
                   "--tmpfs","/tmp:rw,noexec,nosuid,size=512m",
                   "-v",f"{ROOT/'runtime/official'}:/official:ro",
                   "-v",f"{ROOT/'runtime/models'}:/models:ro",
                   "-v",f"{ROOT/'runtime/job.json'}:/job.json:ro",
                   "-v",f"{temporary}:/out:rw","osl-worker","--job","/job.json"]
        try:
            subprocess.run(command,check=True,timeout=1800)
            raw = read(temporary/"raw.json")
            result = summarize(raw,job,plan["protocol"])
            target = ROOT/"site/data/pairs"/job["key"]
            target.mkdir(parents=True,exist_ok=True)
            # A loaded ZIP may execute arbitrary Python: expose no host keys,
            # network, docker socket or source repository mount to that process.
            # Only exact expected recordings are copied out of its writable area.
            files = [r[k] for r in result["games"] for k in ("replay","audit")]
            files += [v["path"] for v in result["videos"]]
            for name in files:
                source = temporary/name
                if source.is_symlink() or not source.resolve().is_relative_to(temporary.resolve()): raise ValueError("Invalid asset path")
                if not source.is_file() or source.stat().st_size>32*1024*1024: raise ValueError("Invalid recording size")
                dest = target/name; dest.parent.mkdir(exist_ok=True,parents=True); shutil.copyfile(source,dest)
            write(target/"result.json",result)
            export_csv(target/"results.csv",[result])
            state["pairs"].append(result)
        except Exception as exc:
            failures.append({"a":job["a"]["id"],"b":job["b"]["id"],"key":job["key"],
                             "message":f"比賽未完成：{type(exc).__name__}。不以未完成對局判定勝負。請檢查模型可攜性或雲端執行紀錄。"})
        finally:
            state["queued_pairs"] -= 1
    state["failures"] = failures
    state["standings"] = standings(state["players"],state["pairs"])
    state["total_games"] = sum(len(p["games"]) for p in state["pairs"])
    state["complete_round_robin"] = len(state["pairs"])==6 and state["total_games"]==600
    state["status"] = "complete" if state["complete_round_robin"] else "partial" if state["pairs"] else "waiting"
    state["updated_at"] = now()
    state["next_scheduled_check"] = next_check()
    export_csv(ROOT/"site/data/results.csv",state["pairs"])
    export_tables(ROOT/"site/data",state)
    write(ROOT/"site/data/latest.json",state)
    # Current broadcast only, with all historical tables kept in history.json.
    # Old binaries are not silently accumulated in Git history or Actions cache.
    keep = {p["key"] for p in state["pairs"]}
    base = ROOT/"site/data/pairs"
    if base.exists():
        for path in base.iterdir():
            if path.is_dir() and path.name not in keep: shutil.rmtree(path)
    print(f"Published {state['total_games']} completed games. Failed pairs: {len(failures)}")

if __name__ == "__main__": main()
