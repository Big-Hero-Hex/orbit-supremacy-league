import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'arena'))
from starred import load_starred,mark_replays,pair_keys,save_standings

class StarredTests(unittest.TestCase):
    def test_load_caps_at_two_dedupes_and_tolerates_bad_files(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'s.json';p.write_text(json.dumps({'snapshots':['a','a','b','c',3,'']}))
            self.assertEqual(load_starred(p),['a','b'])
            p.write_text('not json');self.assertEqual(load_starred(p),[])
            self.assertEqual(load_starred(Path(t)/'missing.json'),[])
    def test_only_starred_and_latest_are_replayable(self):
        entries=[dict(key=k,pairs=[dict(key='p'+k)]) for k in 'abc']
        with tempfile.TemporaryDirectory() as t:
            for k in 'abc':
                (Path(t)/('p'+k)).mkdir();(Path(t)/('p'+k)/'result.json').write_text('{}')
            sd=Path(t)/'starred';save_standings(entries,['b'],dict(players=[],standings=[1]),sd);self.assertFalse(sd.exists(),'only a starred latest is frozen')
            mark_replays(entries,['a'],t,sd);self.assertFalse(entries[0]['replay_available'],'starred needs its frozen standings')
            sd.mkdir();(sd/'a.json').write_text('{}');mark_replays(entries,['a'],t,sd)
            self.assertEqual([e['replay_available'] for e in entries],[True,False,True])
            self.assertEqual([e['starred'] for e in entries],[True,False,False])
            self.assertEqual(pair_keys(entries,['a']),{'pa'})
            save_standings(entries,['c'],dict(players=[1],standings=[2]),sd);self.assertTrue((sd/'c.json').is_file())
            (Path(t)/'pa'/'result.json').unlink();mark_replays(entries,['a'],t,sd)
            self.assertFalse(entries[0]['replay_available'])
if __name__=='__main__':unittest.main()
