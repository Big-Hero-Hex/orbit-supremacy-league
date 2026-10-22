import csv
import gzip
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"arena"))
import diagnostics
import opening
from diagnostics import annotate, attach, export, findings, game_diagnostics, summary

def ship(x=300,y=400,angle=0,pilot=0,ammo=3,cooldown=0,laser=0,alive=1):
    return [x,y,angle,alive,pilot,ammo,cooldown,laser,0]

def metrics(**values):
    base={"gun_shots":0,"laser_shots":0,"weapon_hits":0,"pilot_weapon_kills":0,"ram_kills":0}
    return {**base,**values}

class DiagnosticsTests(unittest.TestCase):
    def game(self,rammed=True):
        # Blue (a) faces red at x=900 (angle pi/2 is +x) and fires once on
        # target; red (b) faces away, is shot empty-handed at tick 9, its pilot
        # stays 110-120px from blue and is rammed (or shot) at tick 15.
        east=math.pi/2
        blue=[ship(angle=east),ship(angle=east,ammo=2,cooldown=5),ship(x=310,angle=east,ammo=2,cooldown=3),ship(x=320,angle=east,ammo=2,cooldown=1),ship(x=330,angle=east,ammo=2),ship(x=340,angle=east,ammo=2),ship(x=350,angle=east,ammo=2)]
        red=[ship(x=900,angle=east,ammo=0)]*4+[ship(x=450,pilot=1,ammo=0)]*2+[ship(x=450,pilot=1,alive=0)]
        frames=[{"t":t,"s":[b,r]} for t,b,r in zip((1,2,4,6,10,12,16),blue,red)]
        row={"id":"5-ship1","seed":5,"a_seat":"ship1","assignment":{"ship1":"a","ship2":"b"},"winner":"a","ticks":16,
             "timeline":[{"tick":3,"kind":"asteroid_hit","by":"b","target":None},{"tick":9,"kind":"eject","by":"a","target":"b"},{"tick":15,"kind":"kill","by":"a","target":"b"}],
             "metrics":{"a":metrics(gun_shots=1,weapon_hits=2,pilot_weapon_kills=0 if rammed else 1,ram_kills=1 if rammed else 0),"b":metrics(gun_shots=1)},
             "replay":"replays/5-ship1.json.gz"}
        return row,{"frames":frames}
    def test_game_counts_shooting_losses_pilot_and_finish(self):
        row,record=self.game();d=game_diagnostics(row,record)["players"]
        a,b=d["a"],d["b"]
        self.assertEqual((a["shots_seen"],a["shots_aimed"],a["aim_on"],a["ship_samples"]),(1,1,5,5))
        self.assertEqual((a["finish_success"],a["finish_fail"],a["finish_ticks"],a["lost_first_ship_first"]),(1,0,[6],0))
        self.assertEqual((b["losses"],b["losses_empty"],b["losses_facing_away"],b["asteroid_hits"]),(1,1,1,1))
        self.assertEqual((b["pilot_rammed"],b["pilot_shot"],b["pilot_saved"],b["lost_first_ship_first"]),(1,0,0,1))
        self.assertEqual((b["pilot_samples"],b["pilot_distance_sum"]),(2,230.0))
        # Red has no ammo, so blue is never under aim from a loaded gun.
        self.assertEqual(a["exposed_samples"],0)
        self.assertEqual(a["spawn"],{"error_deg":0.0,"distance":600,"face_tick":1,"opening_pressure":None})
        self.assertEqual(b["spawn"],{"error_deg":180.0,"distance":600,"face_tick":None,"opening_pressure":1.0})
        self.assertEqual(b["moments"],{"empty_loss":[9],"away_loss":[9],"finish_fail":[],"rammed":15,"asteroid":3})
        row,record=self.game(rammed=False)
        self.assertEqual(game_diagnostics(row,record)["players"]["b"]["pilot_shot"],1)
    def test_summary_rates_situations_and_loss_paths(self):
        row,record=self.game();row["diagnostics"]=game_diagnostics(row,record)
        lost={**row,"id":"6-ship1","winner":"b","diagnostics":game_diagnostics(row,record)}
        s=summary([row,lost],"b")
        self.assertEqual(s["games"],2);self.assertEqual(s["score_rate"],.5)
        self.assertEqual(s["rates"]["loss_empty_share"],1);self.assertEqual(s["rates"]["pilot_rammed_share"],1)
        self.assertEqual(s["rates"]["asteroid_share"],1)
        # Situations present in every game have no comparison group.
        self.assertIsNone(s["situations"]["loss_while_empty"]["points_lost"])
        self.assertEqual(s["loss_paths"],{"lost_games":1,"pilot_rammed":1,"silent_first_loss":0,"led_then_lost":0,"pilot_shot":0})
    def test_findings_rank_against_references_and_sort_by_points(self):
        def own(**rates):
            return {"games":10,"rates":{k:None for k,*_ in diagnostics.SKILLS}|rates,"loss_paths":{},
                    "situations":{k:{"games":0,"points_lost":None} for k,*_ in diagnostics.SITUATIONS}}
        me=own(accuracy=.2,enemy_accuracy=.1,speed=500)
        me["situations"]["silent_first_loss"]={"games":5,"points_lost":4.0};me["situations"]["finish_failed"]={"games":3,"points_lost":9.0}
        me["situations"]["loss_while_empty"]={"games":2,"points_lost":7.0}
        f=findings(me,[own(accuracy=.4,enemy_accuracy=.3,speed=100),own(accuracy=.3,enemy_accuracy=.5),own(accuracy=.5)])
        self.assertEqual([s["situation"] for s in f["situations"]],["finish_failed","silent_first_loss"])
        acc=next(s for s in f["skills"] if s["metric"]=="accuracy")
        self.assertEqual((acc["rank"],acc["of"],acc["best"],acc["behind"]),(4,4,.5,True))
        self.assertFalse(next(s for s in f["skills"] if s["metric"]=="enemy_accuracy")["behind"])
        self.assertNotIn("speed",[s["metric"] for s in f["skills"]])
    def test_attach_annotate_and_export_from_recordings(self):
        row,record=self.game();row["opening"]=opening.game_opening(row,record)
        missing={**row,"id":"7-ship1","replay":"replays/7-ship1.json.gz"}
        pair={"key":"k","a":"a","b":"b","games":[row,missing]}
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"replays").mkdir()
            with gzip.open(Path(temp)/row["replay"],"wt") as f:json.dump(record,f)
            self.assertEqual(attach(pair,temp),1)
            state={"players":[{"id":"a","name":"甲"},{"id":"b","name":"乙"}],"pairs":[pair],"updated_at":"now","total_games":2,
                   "standings":[{"id":p,"rank":i+1,"score_rate":1-i,"diagnostics":summary(pair["games"],p)} for i,p in enumerate("ab")]}
            annotate(state);export(temp,state)
            self.assertEqual(set(state["weaknesses"]),{"a","b"});self.assertEqual(set(pair["weaknesses"]),{"a","b"})
            with (Path(temp)/"diagnostics_log.csv").open(encoding="utf-8-sig") as f:log=list(csv.DictReader(f))
            with (Path(temp)/"weakness_summary.csv").open(encoding="utf-8-sig") as f:table=list(csv.DictReader(f))
            report=json.loads((Path(temp)/"weakness_report.json").read_text(encoding="utf-8"))
            markdown=(Path(temp)/"weakness_report.md").read_text(encoding="utf-8")
        self.assertEqual(len(log),2);self.assertEqual(log[1]["pilot_rammed"],"1");self.assertEqual(log[0]["finish_ticks"],"6")
        self.assertEqual([(r["scope"],r["player_id"]) for r in table],[("all","a"),("all","b"),("pair","a"),("pair","b")])
        self.assertEqual(report["players"]["b"]["loss_paths"]["lost_games"],1)
        self.assertIn("## 甲（a）",markdown);self.assertIn("被撞死",markdown)

    def test_examples_link_failure_moments_lost_games_first(self):
        row,record=self.game();row["diagnostics"]=game_diagnostics(row,record);row["opening"]=opening.game_opening(row,record)
        won={**row,"id":"4-ship1","seed":4,"winner":"b"}
        self.assertEqual(diagnostics.examples([("k",won),("k",row)],"b","loss_while_empty"),
                         [{"pair":"k","game_id":"5-ship1","at":0},{"pair":"k","game_id":"4-ship1","at":0}])
        self.assertEqual(diagnostics.rammed_examples([("k",row)],"b"),[{"pair":"k","game_id":"5-ship1","at":0}])
    def test_versions_refresh_within_round_and_compare_against_previous_model(self):
        def state(sha,round_id,silent,score):
            diag={"games":100,"score_rate":score,"rates":{k:.5 for k,*_ in diagnostics.SKILLS}}
            return {"players":[{"id":"a","sha256":sha}],"seed_round":{"id":round_id},"updated_at":round_id,
                    "standings":[{"id":"a","games":100,"score_rate":score,"opening":{"silent_loss_rate":silent},"diagnostics":diag}],"pairs":[]}
        v=diagnostics.track_versions(None,state("old","r1",.6,.7))
        v=diagnostics.track_versions(v,state("old","r1",.5,.7))
        self.assertEqual([(e["sha256"],e["metrics"]["silent_loss_rate"]) for e in v["a"]],[("old",.5)])
        v=diagnostics.track_versions(v,state("old","r2",.55,.7));v=diagnostics.track_versions(v,state("new","r2",.2,.8))
        c=diagnostics.comparison(v["a"])
        self.assertEqual((c["previous_version"]["sha256"],c["previous_version"]["same_round"]),("old",True))
        silent=next(r for r in c["previous_version"]["rows"] if r["metric"]=="silent_loss_rate")
        self.assertAlmostEqual(silent["change"],-.35);self.assertTrue(silent["improved"])
        self.assertIsNone(c["same_model_earlier_round"])
        self.assertIsNone(diagnostics.comparison(diagnostics.track_versions(None,state("old","r1",.6,.7))["a"])["previous_version"])

if __name__=="__main__":unittest.main()
