import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'arena'))
from starred import effective_starred,load_starred,mark_replays,pair_keys,save_standings,starred_revision

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
            sd=Path(t)/'starred';save_standings(entries,['b'],dict(players=[],standings=[]),sd);self.assertFalse(sd.exists(),'nothing to freeze without standings')
            mark_replays(entries,['a'],t,sd);self.assertFalse(entries[0]['replay_available'],'starred needs its frozen standings')
            sd.mkdir();(sd/'a.json').write_text('{}');mark_replays(entries,['a'],t,sd)
            self.assertEqual([e['replay_available'] for e in entries],[True,False,True])
            self.assertEqual([e['starred'] for e in entries],[True,False,False])
            self.assertEqual(pair_keys(entries,['a']),{'pa'})
            save_standings(entries,['a'],dict(players=[1],standings=[2]),sd);self.assertTrue((sd/'c.json').is_file());self.assertFalse((sd/'b.json').exists(),'unretained snapshots are pruned')
            self.assertEqual(effective_starred(entries,['a','x','y']),['b','a'],'previous snapshot takes one slot');self.assertEqual(effective_starred(entries[:1],['a','x','y']),['a','x'])
            self.assertEqual(effective_starred(entries,['b']),['b'])
            (Path(t)/'pa'/'result.json').unlink();mark_replays(entries,['a'],t,sd)
            self.assertFalse(entries[0]['replay_available'])
    def test_star_files_newest_first_and_ignore_junk(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'starred';d.mkdir()
            (d/'aaaaaaaa.json').write_text(json.dumps({'starred_at':'2026-10-01T00:00:00Z'}))
            (d/'bbbbbbbb.json').write_text(json.dumps({'starred_at':'2026-10-02T00:00:00Z'}))
            (d/'README.txt').write_text('x');(d/'not-a-key.json').write_text('{}');(d/'cccccccc.json').write_text('garbage')
            legacy=Path(t)/'s.json';legacy.write_text(json.dumps({'snapshots':['dddddddd']}))
            self.assertEqual(load_starred(legacy,d),['bbbbbbbb','aaaaaaaa'])
            self.assertEqual(load_starred(legacy,Path(t)/'nope'),['dddddddd'])
    def test_revision_changes_with_star_list(self):
        self.assertNotEqual(starred_revision(['a']),starred_revision(['a','b']));self.assertEqual(starred_revision([]),starred_revision([]))
    def test_manual_flag(self):
        e=[dict(key='a',pairs=[]),dict(key='b',pairs=[])]
        with tempfile.TemporaryDirectory() as t:mark_replays(e,['a'],t,t,['a'])
        self.assertEqual([x['manual_starred'] for x in e],[True,False])
if __name__=='__main__':unittest.main()
