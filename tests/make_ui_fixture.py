"""Synthetic UI-only fixtures; never uploaded as league results."""
import itertools
import json
import copy
from pathlib import Path
from test_league import LeagueTests
from aggregate import summarize, standings
from common import now, seeds
from ranking_history import snapshot, annotate_history
from highlights import viewing_guide
import opening
import diagnostics
import mistakes

root=Path(__file__).resolve().parents[1]
config=json.loads((root/"arena.json").read_text())
record={"ticks":100,"walls":[],"ship_polygon":[[0,-20],[-13,14],[13,14]],"pilot_polygon":[[0,-9],[-6,6],[6,6]],"frames":[{"t":t,"s":[[300+t,400,0,1,0,3,0,0,0],[900-t,400,3.14,1,0,3,0,0,0]],"a":[],"b":[],"p":[],"e":[]} for t in range(0,101,2)]}
players=[{**p,"sha256":str(i)*64,"status":"ready","filename":"UI-TEST-ONLY.zip"} for i,p in enumerate(config["players"],1)]
pairs=[]
for a,b in itertools.combinations(players,2):
    job,raw=LeagueTests().fixture();job.update(a=a,b=b,key=a["id"]+"-"+b["id"])
    for i,r in enumerate(raw["games"]):
        r["id"]=f"{r['seed']}-{r['a_seat']}";r["assignment"]={s:a["id"] if pid=="a" else b["id"] for s,pid in r["assignment"].items()}
        r["winner"]=r["assignment"]["ship1"];r["metrics"]={a["id"]:r["metrics"]["a"],b["id"]:r["metrics"]["b"]}
        r["timeline"]=[{"tick":50,"kind":"eject","by":r["winner"],"target":r["assignment"]["ship2"]}]
        r["replay"]=f"replays/{r['id']}.json.gz";r["audit"]=f"audit/{r['id']}.npz"
        # Every fourth loser never fires before its ship is lost at tick 50.
        loser=r["assignment"]["ship2"];silent=i%4==0
        r["opening"]={"version":opening.VERSION,"players":{r["winner"]:{"first_shot":30,"first_loss":None,"shots_before_loss":3,"trigger_before_loss":12,"aim_before_loss":.6,"exact":True},
            loser:{"first_shot":None if silent else 40,"first_loss":50,"shots_before_loss":0 if silent else 1,"trigger_before_loss":0 if silent else 4,"aim_before_loss":.1 if silent else .4,"exact":True}}}
        r["diagnostics"]=diagnostics.game_diagnostics(r,record)
    raw["model_info"]={a["id"]:{"parameters":589828},b["id"]:{"parameters":589828}}
    pairs.append(summarize(raw,job,{}))
for pair in pairs:pair['viewing_guide']=viewing_guide(pair['games'],pair['a'],pair['b']);pair['opening']={p:opening.summary(pair['games'],p) for p in (pair['a'],pair['b'])};pair['diagnostics']={p:diagnostics.summary(pair['games'],p) for p in (pair['a'],pair['b'])}
state={**config,"players":players,"pairs":pairs,"standings":standings(players,pairs),"total_games":len(pairs)*100,"expected_pairs":len(pairs),"expected_games":len(pairs)*100,"complete_round_robin":True,"status":"complete","checked_at":now(),"updated_at":now(),"failures":[]}
# Synthetic tick counts only; real records come from each game's audit log.
def fake(i):return {**{k:[(i*(n+3))%7,10] for n,(k,*_) in enumerate(mistakes.METRICS)},'missed_shot_bands':{b:[1,3] for *_,b in mistakes.BANDS},'angle_1s':float(i%90),'pilot_flee':[.5,2],'runs':{}}
records={p['key']:{r['id']:{'version':mistakes.VERSION,'players':{pid:fake(i+j) for j,pid in enumerate(r['assignment'].values())}} for i,r in enumerate(p['games'])} for p in pairs}
for p in pairs:p['mistakes']={pid:mistakes.summary(mistakes.items(p,records[p['key']],pid),pid) for pid in (p['a'],p['b'])}
mistakes.annotate(state,records)
# A synthetic earlier model per player, so the version comparison renders.
diagnostics.annotate(state)
older={pid:[{**v[-1],'sha256':'old-'+pid,'metrics':{k:(x*.8 if isinstance(x,float) else x) for k,x in v[-1]['metrics'].items()}}] for pid,v in state['diagnostic_versions'].items()}
diagnostics.annotate(state,{'diagnostic_versions':older})
state['ranking_history']=[]
for i in range(3):
    earlier=copy.deepcopy(state);earlier['updated_at']=f'2026-10-20T{10+i}:00:00Z'
    earlier['seed_round']=dict(id='legacy-s01' if i<2 else 'daily-20261022',starts_at=None if i<2 else '2026-10-21T20:00:00Z',next_rotation_at='2026-10-21T20:00:00Z' if i<2 else '2026-10-22T20:00:00Z')
    earlier['protocol']={'version':1,'seeds':seeds('fixture-old' if i<2 else 'fixture-new')}
    if i>=1:
        for person in earlier['players'][:2]: person['sha256']='changed-'+person['id']
    for j,row in enumerate(earlier['standings']):
        rank=(j+i)%len(players)+1;games=(len(players)-1)*100;wins=games-rank*20
        row.update(rank=rank,wins=wins,losses=games-wins,games=games,points=wins,score_rate=wins/games,win_rate=wins/games)
    state['ranking_history'].append(snapshot(earlier))
state['ranking_history']=annotate_history(state['ranking_history'])
state['seed_round']=earlier['seed_round'];state['protocol']=earlier['protocol']
record["assignment"]=pairs[0]["games"][0]["assignment"]
(root/"runtime").mkdir(exist_ok=True)
(root/"runtime/ui-fixture.json").write_text(json.dumps({"state":state,"record":record},ensure_ascii=False))
