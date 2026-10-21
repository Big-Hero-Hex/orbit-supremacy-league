import csv
import gzip
import json
import math
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"arena"))
import opening
from opening import attach, discharges, export, fired_first, game_opening, read_actions, summary

def ship(x=300,y=400,angle=0,pilot=0,ammo=3,cooldown=0,laser=0,alive=1):
    return [x,y,angle,alive,pilot,ammo,cooldown,laser,0]

def npz(path,steps):
    """Hand-built savez_compressed layout; CI has no numpy on the host."""
    header=repr({"descr":"<f4","fortran_order":False,"shape":(len(steps),2,3)}).encode()
    header+=b" "*(63-(len(header)+10)%64)+b"\n"
    body=b"\x93NUMPY\x01\x00"+struct.pack("<H",len(header))+header+struct.pack(f"<{len(steps)*6}f",*[v for step in steps for v in step])
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:z.writestr("actions.npy",body)

class OpeningTests(unittest.TestCase):
    def game(self):
        # Blue fires at tick 4 (ammo drop) and tick 8 (reload hides the drop,
        # cooldown re-arms), then is never hit. Red points away, never fires and
        # loses its ship at tick 10.
        blue=[ship(ammo=3),ship(ammo=3),ship(ammo=2,cooldown=5),ship(ammo=2,cooldown=3),ship(ammo=2,cooldown=5),ship(ammo=2,cooldown=3),ship(ammo=2,cooldown=1)]
        red=[ship(x=900,angle=0)]*5+[ship(x=900,pilot=1),ship(x=900,pilot=1)]
        frames=[{"t":t,"s":[b,r]} for t,b,r in zip((1,2,4,6,8,10,12),blue,red)]
        row={"id":"7-ship1","seed":7,"a_seat":"ship1","assignment":{"ship1":"a","ship2":"b"},"winner":"a","ticks":12,
             "timeline":[{"tick":10,"kind":"eject","by":"a","target":"b"}],
             "metrics":{"a":{"gun_shots":2,"laser_shots":0},"b":{"gun_shots":0,"laser_shots":0}},
             "replay":"replays/7-ship1.json.gz","audit":"audit/7-ship1.npz"}
        steps=[[0,1,1 if i in (2,6) else -1,0,1,-1] for i in range(11)]
        return row,{"frames":frames},steps
    def test_shots_seen_through_reload_and_laser(self):
        frames=[{"t":t,"s":[s,ship()]} for t,s in [(1,ship(ammo=1)),(2,ship(ammo=0,cooldown=5)),(4,ship(ammo=0,cooldown=3)),(6,ship(ammo=0,cooldown=1)),(8,ship(ammo=0,cooldown=5)),(10,ship(ammo=0,laser=1)),(12,ship(ammo=0,laser=0,cooldown=5))]]
        self.assertEqual(discharges(frames,0),[2,8,12])
        self.assertEqual(discharges(frames,1),[])
    def test_silent_loss_trigger_and_aim(self):
        row,record,steps=self.game()
        with tempfile.TemporaryDirectory() as temp:
            npz(Path(temp)/"a.npz",steps);result=game_opening(row,record,read_actions(Path(temp)/"a.npz"))["players"]
        self.assertEqual(result["a"],{"first_shot":4,"first_loss":None,"shots_before_loss":2,"trigger_before_loss":2,"aim_before_loss":0.0,"exact":True})
        self.assertEqual(result["b"],{"first_shot":None,"first_loss":10,"shots_before_loss":0,"trigger_before_loss":0,"aim_before_loss":0.0,"exact":True})
        # Nose is local (0,-20): angle pi/2 faces +x, toward the red ship.
        for f in record["frames"]:f["s"][0][2]=math.pi/2
        self.assertEqual(game_opening(row,record)["players"]["a"]["aim_before_loss"],1.0)
        row["metrics"]["a"]["gun_shots"]=3
        self.assertFalse(game_opening(row,record)["players"]["a"]["exact"])
    def test_attach_backfills_from_recordings_and_tolerates_missing_files(self):
        row,record,steps=self.game();missing={**row,"id":"8-ship1","replay":"replays/8-ship1.json.gz","audit":"audit/8-ship1.npz"}
        pair={"key":"k","a":"a","b":"b","games":[row,missing]}
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"replays").mkdir();(Path(temp)/"audit").mkdir()
            with gzip.open(Path(temp)/row["replay"],"wt") as f:json.dump(record,f)
            npz(Path(temp)/row["audit"],steps)
            self.assertEqual(attach(pair,temp),1)
        self.assertEqual(row["opening"]["version"],opening.VERSION);self.assertNotIn("opening",missing)
        self.assertEqual(pair["opening"]["b"]["silent_losses"],1);self.assertEqual(pair["opening"]["b"]["silent_without_trigger"],1)
        self.assertEqual(pair["opening"]["a"]["games"],1)
    def test_oversized_replay_is_rejected_before_parsing(self):
        row,record,steps=self.game();old=opening.REPLAY_LIMIT;opening.REPLAY_LIMIT=10
        try:
            with tempfile.TemporaryDirectory() as temp:
                (Path(temp)/"replays").mkdir()
                with gzip.open(Path(temp)/row["replay"],"wt") as f:json.dump(record,f)
                self.assertEqual(attach({"key":"k","a":"a","b":"b","games":[row]},temp),1)
        finally:opening.REPLAY_LIMIT=old
    def test_summary_first_fire_and_conditional_win_rates(self):
        def row(first_a,first_b,winner,loss_b=None,shots_b=0):
            return {"winner":winner,"opening":{"version":opening.VERSION,"players":{
                "a":{"first_shot":first_a,"first_loss":None,"shots_before_loss":3,"trigger_before_loss":5,"aim_before_loss":.5,"exact":True},
                "b":{"first_shot":first_b,"first_loss":loss_b,"shots_before_loss":shots_b,"trigger_before_loss":0,"aim_before_loss":.1,"exact":False}}}}
        games=[row(10,20,"a"),row(30,20,"b"),row(10,10,None),row(None,None,None,loss_b=50),{"winner":"a"}]
        self.assertEqual([fired_first(r,"a") for r in games[:4]],[1,0,.5,None])
        s=summary(games,"a")
        self.assertEqual(s["games"],4);self.assertEqual(s["fired_first_rate"],.5)
        self.assertEqual(s["win_rate_fired_first"],1);self.assertEqual(s["win_rate_opponent_fired_first"],0)
        b=summary(games,"b")
        self.assertEqual((b["lost_first_ship"],b["silent_losses"],b["silent_loss_rate"],b["silent_without_trigger"]),(1,1,1,1))
        self.assertEqual(b["never_fired"],1);self.assertEqual(b["exact_games"],0);self.assertEqual(b["first_loss_median_s"],1)
        self.assertIsNone(summary([],"a")["silent_loss_rate"])
    def test_csv_log_marks_not_applicable_as_blank(self):
        row,record,steps=self.game();row["opening"]=game_opening(row,record)
        pair={"key":"k","a":"a","b":"b","games":[row]};pair["opening"]={p:summary([row],p) for p in "ab"}
        state={"players":[{"id":"a","name":"甲"},{"id":"b","name":"乙"}],"pairs":[pair],"standings":[{"id":p,"opening":summary([row],p)} for p in "ab"]}
        with tempfile.TemporaryDirectory() as temp:
            export(temp,state)
            self.assertTrue((Path(temp)/"opening_log.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            with (Path(temp)/"opening_log.csv").open(encoding="utf-8-sig") as f:log={r["player_id"]:r for r in csv.DictReader(f)}
            with (Path(temp)/"opening_summary.csv").open(encoding="utf-8-sig") as f:table=list(csv.DictReader(f))
        self.assertEqual((log["b"]["silent_loss"],log["b"]["first_loss_s"],log["b"]["trigger_ticks_before_loss"]),("1","0.2",""))
        self.assertEqual((log["a"]["silent_loss"],log["a"]["first_shot_tick"],log["a"]["fired_first"]),("","4","1"))
        self.assertEqual([(r["scope"],r["name"]) for r in table],[("all","甲"),("all","乙"),("pair","甲"),("pair","乙")])

if __name__=="__main__":unittest.main()
