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
import mistakes
from mistakes import View, blocked, game_mistakes, read_audit

def observe(x,y,a,ex,ey,ammo=1,ready=1,pilot=0,enemy_pilot=0,enemy_ammo=1,vx=0,vy=0,evx=0,evy=0):
    own=[(x-600)/600,(y-400)/400,vx/260,vy/260,math.cos(a),math.sin(a),0,0,ammo,0,0,ready,pilot,0]
    rel=[(ex-x)/600,(ey-y)/400,(evx-vx)/260,(evy-vy)/260,0,0,1,enemy_pilot,enemy_ammo,0,0,1]
    return own+rel+[0]*58

def npy(values,shape):
    header=repr({"descr":"<f4","fortran_order":False,"shape":shape}).encode()
    header+=b" "*(63-(len(header)+10)%64)+b"\n"
    return b"\x93NUMPY\x01\x00"+struct.pack("<H",len(header))+header+struct.pack(f"<{len(values)}f",*values)

def audit(path,ticks):
    """ticks: [((obs seat1, obs seat2), (action seat1, action seat2))]."""
    obs=[v for (o,_) in ticks for seat in o for v in seat];act=[v for (_,a) in ticks for seat in a for v in seat]
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("observations.npy",npy(obs,(len(ticks),2,84)));z.writestr("actions.npy",npy(act,(len(ticks),2,3)))

EAST=math.pi/2  # nose (sin a, -cos a) points to +x

class MistakeTests(unittest.TestCase):
    def duel(self):
        # Blue at (300,150) faces red 200px east, loaded but holding fire. Red
        # faces away east, thrusting and not turning.
        blue=observe(300,150,EAST,500,150);red=observe(500,150,EAST,300,150)
        return [((blue,red),((0,0,-1),(0,.5,-1)))]*3
    def test_geometry_angle_lead_hit_and_cover(self):
        me=View(observe(300,150,EAST,500,150),0)
        self.assertAlmostEqual(me.angle((0,100)),math.pi/2)   # +y is to the right of an east-facing nose
        self.assertTrue(me.would_hit()[0]);self.assertEqual(me.lead(),me.enemy_rel)
        moving=View(observe(300,150,EAST,500,150,evy=200),0)
        self.assertGreater(moving.lead()[1],0);self.assertFalse(moving.would_hit()[0])
        self.assertTrue(blocked((450,400),(750,400),[],[]))                       # planet
        self.assertTrue(blocked((0,50),(200,50),[(100,50,5,5)],[]))               # wall bar
        self.assertTrue(blocked((0,0),(100,0),[],[(50,6,5)]))                     # asteroid + bullet radius
        self.assertFalse(blocked((0,0),(100,0),[],[(50,20,5)]))
    def test_game_counts_and_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            audit(Path(temp)/"g.npz",self.duel());record=game_mistakes(self.row(),[],read_audit(Path(temp)/"g.npz"))["players"]
        a,b=record["a"],record["b"]
        self.assertEqual((a["missed_shot"],a["open_not_turning"],a["exposed_unarmed"],a["thrust_away_close"]),([3,3],[0,0],[0,3],[0,0]))
        self.assertEqual((b["open_not_turning"],b["exposed_unarmed"],b["thrust_away_close"],b["missed_shot"]),([3,3],[3,3],[3,3],[0,0]))
        self.assertEqual(a["missed_shot_bands"]["near"],[3,3]);self.assertEqual(a["runs"]["missed_shot"],[1,3]);self.assertIsNone(a["angle_1s"])
    def row(self,winner="a"):
        return {"id":"9-ship1","seed":9,"a_seat":"ship1","assignment":{"ship1":"a","ship2":"b"},"winner":winner,"ticks":4,
                "timeline":[],"metrics":{"a":{"ram_kills":0},"b":{"ram_kills":0}},"replay":"replays/9-ship1.json.gz","audit":"audit/9-ship1.npz"}
    def test_led_then_lost_paths(self):
        row=self.row(winner="b");row["timeline"]=[{"tick":5,"kind":"eject","by":"a","target":"b"},{"tick":30,"kind":"respawn","by":"b","target":None},
                                                  {"tick":60,"kind":"eject","by":"b","target":"a"},{"tick":70,"kind":"kill","by":"b","target":"a"}]
        row["metrics"]["b"]["ram_kills"]=1
        self.assertEqual(mistakes.led_then_lost(row,"a"),"enemy_respawned_then_rammed");self.assertIsNone(mistakes.led_then_lost(row,"b"))
    def test_attach_cache_annotate_and_export(self):
        row=self.row();pair={"key":"k","a":"a","b":"b","games":[row]}
        state={"players":[{"id":"a","name":"甲"},{"id":"b","name":"乙"}],"pairs":[pair],"repository":"Org/league",
               "standings":[{"id":"a"},{"id":"b"}],"total_games":1}
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"replays").mkdir();(Path(temp)/"audit").mkdir()
            with gzip.open(Path(temp)/row["replay"],"wt") as f:json.dump({"walls":[],"frames":[]},f)
            audit(Path(temp)/row["audit"],self.duel())
            records,failed=mistakes.attach(pair,temp,{});self.assertEqual(failed,0)
            # A cached record is reused without reading the audit file again.
            (Path(temp)/row["audit"]).unlink();again,failed=mistakes.attach(pair,temp,{"k":records});self.assertEqual((again,failed),(records,0))
            mistakes.annotate(state,{"k":records});mistakes.export(temp,state,{"k":records})
            with (Path(temp)/"conceptual_mistakes.csv").open(encoding="utf-8-sig") as f:table=list(csv.DictReader(f))
            report=json.loads((Path(temp)/"conceptual_mistakes.json").read_text(encoding="utf-8"))
            cache=json.loads((Path(temp)/"mistakes_games.json").read_text(encoding="utf-8"))
            markdown=(Path(temp)/"conceptual_mistakes.md").read_text(encoding="utf-8")
        self.assertEqual(len(table),12);self.assertEqual(float(table[0]["missed_shot"]),1.0)
        self.assertEqual(state["standings"][1]["mistakes"]["won"]["games"],0);self.assertEqual(state["standings"][0]["mistakes"]["won"]["games"],1)
        top=report["players"]["b"]["mistakes"][0];self.assertEqual(top["examples"][0]["ticks"],[1,3])
        self.assertEqual(cache["pairs"]["k"]["9-ship1"]["players"]["a"]["missed_shot"],[3,3])
        self.assertIn("## 乙（b）",markdown);self.assertIn("https://org.github.io/league/#game=k/9-ship1@0",markdown)

if __name__=="__main__":unittest.main()
