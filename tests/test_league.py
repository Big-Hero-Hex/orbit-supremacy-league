import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"arena"))
from common import pair_key, seeds
from aggregate import METRICS, interval, standings, summarize
from drive import Links

class LeagueTests(unittest.TestCase):
    def fixture(self):
        a={"id":"a","sha256":"1"}; b={"id":"b","sha256":"2"}
        ss=seeds("test"); job={"a":a,"b":b,"seeds":ss,"key":"test-key"}; rows=[]
        for s in ss:
            for seat in ("ship1","ship2"):
                assignment={"ship1":"a" if seat=="ship1" else "b","ship2":"b" if seat=="ship1" else "a"}
                metrics={p:{**{k:0 for k in METRICS},"inference_mean_ms":.5,"inference_p95_ms":1} for p in ("a","b")}
                rows.append({"seed":s,"a_seat":seat,"assignment":assignment,"winner":assignment["ship1"],"ticks":100,"seconds":2,"metrics":metrics})
        raw={"games":rows,"videos":[],"model_info":{}}
        return job,raw
    def test_same_seeds_swapped_exactly_100(self):
        job,raw=self.fixture(); p=summarize(raw,job,{})
        self.assertEqual(p["stats"]["a"]["wins"],50)
        self.assertEqual(p["seats"]["a"]["ship1"]["win_rate"],1)
        self.assertEqual(p["seats"]["a"]["ship2"]["win_rate"],0)
        self.assertEqual(len(p["matches"]),10)
    def test_paired_interval_does_not_treat_seats_independently(self):
        job,raw=self.fixture()
        self.assertEqual(interval(raw["games"],"a"),[.5,.5])
    def test_duplicate_or_missing_game_rejected(self):
        job,raw=self.fixture(); raw["games"][-1]=raw["games"][0]
        with self.assertRaises(ValueError): summarize(raw,job,{})
    def test_draw_half_points_and_shared_rank(self):
        job,raw=self.fixture()
        for r in raw["games"]:r["winner"]=None
        p=summarize(raw,job,{}); rows=standings([job["a"],job["b"]],[p])
        self.assertEqual([r["rank"] for r in rows],[1,1])
        self.assertEqual(rows[0]["score_rate"],.5)
        self.assertEqual(rows[0]["win_rate"],0)
    def test_hash_and_protocol_changes_invalidate_cache(self):
        a={"id":"a","sha256":"1"};b={"id":"b","sha256":"2"};key=pair_key(a,b,{"v":1})
        self.assertNotEqual(key,pair_key({**a,"sha256":"3"},b,{"v":1}))
        self.assertNotEqual(key,pair_key(a,b,{"v":2}))
        self.assertEqual(key,pair_key(a,b,{"v":1}))
    def test_drive_names_are_data_not_markup(self):
        p=Links();p.feed('<a href="https://drive.google.com/file/d/abc_123/view"><b>model.zip</b></a>')
        self.assertEqual(p.items,[{"file_id":"abc_123","filename":"model.zip"}])
    def test_seeds_unique_reproducible_not_contiguous(self):
        a=seeds("OSL-S01");self.assertEqual(len(set(a)),50);self.assertEqual(a,seeds("OSL-S01"));self.assertTrue(any(abs(x-y)>100 for x,y in zip(a,a[1:])))

if __name__=="__main__":unittest.main()
