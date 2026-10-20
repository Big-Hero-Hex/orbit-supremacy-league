import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"arena"))
from common import pair_key, seeds
from aggregate import METRICS, export_tables, interval, standings, summarize
from drive import Links, parse_metadata

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
    def test_same_id_new_revision_invalidates_metadata_fingerprint(self):
        import json
        row=["file-id",["folder-id"],"model.zip","application/zip",0,None,0,0,0,1792500000000,1792500000000,None,None,7113857]
        def page(row):return "window['_DRIVE_ivd'] = '"+json.dumps([[row]])+"';"
        first=parse_metadata(page(row),"folder-id")[0]
        self.assertEqual(first["metadata_fingerprint"],parse_metadata(page(row),"folder-id")[0]["metadata_fingerprint"])
        row[10]+=1
        second=parse_metadata(page(row),"folder-id")[0]
        self.assertNotEqual(first["metadata_fingerprint"],second["metadata_fingerprint"])
    def test_unknown_revision_schema_falls_back_to_content_hash(self):
        import json
        row=["file-id",["folder-id"],"model.zip","application/zip",0,None,0,0,0,None,None,None,None,100]
        found=parse_metadata("window['_DRIVE_ivd'] = '"+json.dumps([[row]])+"';","folder-id")[0]
        self.assertNotIn("metadata_fingerprint",found)
    def test_downloadable_csv_tables_keep_numeric_values_and_utf8_bom(self):
        import tempfile,csv
        job,raw=self.fixture();p=summarize(raw,job,{})
        players=[{**job["a"],"name":"甲","status":"ready"},{**job["b"],"name":"乙","status":"ready"}]
        state={"players":players,"pairs":[p],"standings":standings(players,[p]),"complete_round_robin":False}
        with tempfile.TemporaryDirectory() as temp:
            export_tables(temp,state)
            self.assertTrue((Path(temp)/"standings.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            with (Path(temp)/"standings.csv").open(encoding="utf-8-sig") as f:rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]["name"],"甲");self.assertEqual(float(rows[0]["win_rate"]),.5)
            for filename in ("head_to_head.csv","seats.csv","matches.csv","combat_stats.csv","models.csv"):self.assertTrue((Path(temp)/filename).is_file())

if __name__=="__main__":unittest.main()
