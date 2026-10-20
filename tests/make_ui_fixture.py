"""Synthetic UI-only fixtures; never uploaded as league results."""
import itertools
import json
from pathlib import Path
from test_league import LeagueTests
from aggregate import summarize, standings
from common import now, seeds

root=Path(__file__).resolve().parents[1]
config=json.loads((root/"arena.json").read_text())
players=[{**p,"sha256":str(i)*64,"status":"ready","filename":"UI-TEST-ONLY.zip"} for i,p in enumerate(config["players"],1)]
pairs=[]
for a,b in itertools.combinations(players,2):
    job,raw=LeagueTests().fixture();job.update(a=a,b=b,key=a["id"]+"-"+b["id"])
    for i,r in enumerate(raw["games"]):
        r["id"]=f"{r['seed']}-{r['a_seat']}";r["assignment"]={s:a["id"] if pid=="a" else b["id"] for s,pid in r["assignment"].items()}
        r["winner"]=r["assignment"]["ship1"];r["metrics"]={a["id"]:r["metrics"]["a"],b["id"]:r["metrics"]["b"]}
        r["timeline"]=[{"tick":50,"kind":"eject","by":r["winner"],"target":r["assignment"]["ship2"]}]
        r["replay"]=f"replays/{r['id']}.json.gz";r["audit"]=f"audit/{r['id']}.npz"
    raw["model_info"]={a["id"]:{"parameters":589828},b["id"]:{"parameters":589828}}
    pairs.append(summarize(raw,job,{}))
state={**config,"players":players,"pairs":pairs,"standings":standings(players,pairs),"total_games":600,"complete_round_robin":True,"status":"complete","checked_at":now(),"updated_at":now(),"failures":[]}
record={"ticks":100,"assignment":pairs[0]["games"][0]["assignment"],"walls":[],"ship_polygon":[[0,-20],[-13,14],[13,14]],"pilot_polygon":[[0,-9],[-6,6],[6,6]],"frames":[{"t":t,"s":[[300+t,400,0,1,0,3,0,0,0],[900-t,400,3.14,1,0,3,0,0,0]],"a":[],"b":[],"p":[],"e":[]} for t in range(0,101,2)]}
(root/"runtime").mkdir(exist_ok=True)
(root/"runtime/ui-fixture.json").write_text(json.dumps({"state":state,"record":record},ensure_ascii=False))
