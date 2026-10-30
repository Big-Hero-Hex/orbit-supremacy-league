"""Cloud-only execution and allow-listed publication; never a self-hosted runner."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from aggregate import export_csv, export_tables, standings, summarize
from ranking_history import update_history, export_history
from common import ROOT, next_check, now, read, write
from highlights import viewing_guide
import diagnostics
import mistakes
import opening
from failures import failure_record
from starred import backfill_standings, effective_starred, load_starred, mark_replays, pair_keys, save_standings

def main():
    plan = read(ROOT/"runtime/plan.json")
    state = read(ROOT/"site/data/latest.json")
    previous=read(ROOT/"runtime/previous_manifest.json",{})
    history=read(ROOT/"site/data/history.json",[])
    oldhashes={p["id"]:p.get("sha256") for p in previous.get("players",[])}
    hashes={p["id"]:p.get("sha256") for p in state["players"]}
    if previous.get("pairs") and (hashes!=oldhashes or previous.get("protocol")!=state.get("protocol")):
        history.append({"recorded_at":previous.get("updated_at"),"players":previous["players"],
                        "standings":previous.get("standings",[]),"protocol":previous.get('protocol',{}),"seed_round":previous.get('seed_round'),
                        "pairs":[{k:v for k,v in p.items() if k not in ("games","videos")} for p in previous["pairs"]]})
    write(ROOT/"site/data/history.json",history);state["history_count"]=len(history)
    failures = list(plan.get('deferred_failures', []))
    old_failures = {f['key']: f for f in previous.get('failures', [])}
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
            # Keep model output in a file, and expose a bounded diagnostic tail.
            with tempfile.TemporaryFile() as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
                log.seek(0, 2); log.seek(max(0, log.tell() - 16384))
                tail = log.read().decode('utf-8', errors='replace')
                print(tail, flush=True)
                if result.returncode:
                    raise subprocess.CalledProcessError(result.returncode, command, output=tail)
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
            failures.append(failure_record(job, exc, old_failures.get(job['key'])))
        finally:
            state["queued_pairs"] -= 1
    state["failures"] = failures
    # Opening diagnostics only read stored recordings, so cached pairs are
    # back-filled without replaying a game or touching the locked match core.
    missing = sum(opening.attach(pair,ROOT/"site/data/pairs"/pair["key"]) for pair in state["pairs"])
    missing += sum(diagnostics.attach(pair,ROOT/"site/data/pairs"/pair["key"]) for pair in state["pairs"])
    # Tick-level records are heavy, so they live in their own cache file
    # rather than latest.json; only changed pairs read their audit logs.
    cached = read(ROOT/"site/data/mistakes_games.json",{}) or {}
    cached = cached.get("pairs",{}) if cached.get("version")==mistakes.VERSION else {}
    records = {}
    for pair in state["pairs"]:
        records[pair["key"]],failed = mistakes.attach(pair,ROOT/"site/data/pairs"/pair["key"],cached); missing += failed
    state["standings"] = standings(state["players"],state["pairs"])
    diagnostics.annotate(state,previous)
    mistakes.annotate(state,records)
    state["total_games"] = sum(len(p["games"]) for p in state["pairs"])
    expected=len(state['players'])*(len(state['players'])-1)//2
    state['expected_pairs']=expected;state['expected_games']=expected*100
    state["complete_round_robin"] = len(state["pairs"])==expected and state["total_games"]==expected*100
    for pair in state['pairs']:
        pair['viewing_guide']=viewing_guide(pair['games'],pair['a'],pair['b'])
        write(ROOT/'site/data/pairs'/pair['key']/'result.json',pair)
    state["status"] = "complete" if state["complete_round_robin"] else "partial" if state["pairs"] else "waiting"
    state["updated_at"] = now()
    state["next_scheduled_check"] = next_check()
    state['ranking_history']=update_history(previous,history,state)
    manual=load_starred(ROOT/'starred_snapshots.json',ROOT/'starred')
    starred=effective_starred(state['ranking_history'],manual)
    save_standings(state['ranking_history'],starred,state,ROOT/'site/data/starred')
    rebuilt=backfill_standings(state['ranking_history'],starred,ROOT/'site/data/pairs',ROOT/'site/data/starred',standings)
    if rebuilt:print(f'Rebuilt frozen standings for {len(rebuilt)} kept snapshot(s) from retained pair results.')
    mark_replays(state['ranking_history'],starred,ROOT/'site/data/pairs',ROOT/'site/data/starred',manual)
    write(ROOT/'site/data/ranking_history.json',state['ranking_history'])
    export_history(ROOT/'site/data',state['ranking_history'])
    export_csv(ROOT/"site/data/results.csv",state["pairs"])
    export_tables(ROOT/"site/data",state)
    mistakes.export(ROOT/"site/data",state,records)
    write(ROOT/"site/data/latest.json",state)
    # Current broadcast only, with all historical tables kept in history.json.
    # Old binaries are not silently accumulated in Git history or Actions cache.
    keep = {p["key"] for p in state["pairs"]} | pair_keys(state['ranking_history'],starred)
    base = ROOT/"site/data/pairs"
    if base.exists():
        for path in base.iterdir():
            if path.is_dir() and path.name not in keep: shutil.rmtree(path)
    print(f"Published {state['total_games']} completed games. Failed pairs: {len(failures)}. Game records without opening/weakness diagnostics: {missing}")

if __name__ == "__main__": main()
