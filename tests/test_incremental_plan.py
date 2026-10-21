"""Prove unchanged games/videos are reused; no model loading or matches."""
import contextlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'arena'))
import plan
from seed_round import select_round
from datetime import datetime
from common import read,write

class IncrementalPlanTests(unittest.TestCase):
    def scenario(self,changed=False,rotate=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'arena').mkdir();(root/'arena/worker.py').write_bytes(b'test-only-engine')
            players=[dict(id=str(i),name=f'player{i}',folder=f'folder{i}') for i in range(4)]
            write(root/'arena.json',dict(title='test',english_title='test',season=1,repository='test/test',drive_folder='test',seed_namespace='test',players=players))
            if rotate:
                config=read(root/'arena.json');config['seed_rotation']={'first_rotation_at':'2026-10-22T04:00:00+08:00','interval_hours':24};write(root/'arena.json',config)
            times=iter(['2026-10-22T03:50:00+08:00','2026-10-22T03:55:00+08:00' if rotate=='same' else '2026-10-22T04:00:00+08:00'])
            def draw(config,previous,persisted):
                return select_round(config,previous,persisted,at=datetime.fromisoformat(next(times)),entropy=lambda:'test')
            revisions={p['folder']:'r0' for p in players};payload={str(i):f'test-model{i}'.encode() for i in range(4)}
            def metadata(folder):return [dict(file_id=folder[-1],filename='model.zip',metadata_fingerprint=revisions[folder])]
            def download(file_id,target):Path(target).write_bytes(payload[file_id])
            with patch.object(plan,'ROOT',root),patch.object(plan,'select_round',side_effect=draw),patch.object(plan,'model_metadata',side_effect=metadata),patch.object(plan,'download',side_effect=download) as get,patch.dict(os.environ,{'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_OUTPUT':''}):
                # Freeze a complete previous roster, with six successful pair caches.
                with contextlib.redirect_stdout(io.StringIO()):plan.main()
                first=read(root/'site/data/latest.json');jobs=read(root/'runtime/plan.json')['jobs'];first['pairs']=[dict(key=j['key'],complete=True,a=j['a']['id'],b=j['b']['id'],hashes={j['a']['id']:j['a']['sha256'],j['b']['id']:j['b']['sha256']}) for j in jobs]
                write(root/'site/data/latest.json',first)
                for f in (root/'runtime/models').iterdir():f.unlink()
                get.reset_mock()
                if changed:revisions['folder0']='r1';payload['0']=b'changed-test-model'
                capture=io.StringIO()
                with contextlib.redirect_stdout(capture):plan.main()
                return first,read(root/'runtime/plan.json'),read(root/'runtime/planned_state.json'),get.call_count,capture.getvalue()
    def test_no_changes_downloads_no_models_and_reuses_all_six(self):
        old,plan_,new,downloads,log=self.scenario()
        self.assertEqual(plan_['jobs'],[]);self.assertEqual(downloads,0);self.assertEqual(len(new['pairs']),6)
        self.assertIn('publish=False',log);self.assertEqual({p['key'] for p in old['pairs']},{p['key'] for p in new['pairs']})
    def test_one_model_changes_only_three_affected_pairs(self):
        old,plan_,new,downloads,log=self.scenario(True)
        self.assertEqual(len(plan_['jobs']),3);self.assertTrue(all('0' in (j['a']['id'],j['b']['id']) for j in plan_['jobs']))
        self.assertEqual(len(new['pairs']),3);self.assertTrue(all('0' not in (p['a'],p['b']) for p in new['pairs']))
        self.assertTrue({p['key'] for p in new['pairs']}.issubset({p['key'] for p in old['pairs']}));self.assertEqual(downloads,4)
    def test_new_round_rebuilds_all_pairs_with_one_shared_fifty_seed_draw(self):
        old,plan_,new,downloads,log=self.scenario(rotate=True)
        self.assertEqual(len(plan_['jobs']),6);self.assertEqual(new['pairs'],[])
        self.assertTrue(all(job['seeds']==new['seed_round']['seeds'] for job in plan_['jobs']))
        self.assertEqual(len(set(new['seed_round']['seeds'])),50)
        self.assertTrue(set(old['protocol']['seeds']).isdisjoint(new['protocol']['seeds']))
        self.assertTrue({p['key'] for p in old['pairs']}.isdisjoint(j['key'] for j in plan_['jobs']))
        self.assertEqual(downloads,4)
    def test_scheduled_same_round_reuses_every_pair_without_model_download(self):
        old,plan_,new,downloads,log=self.scenario(rotate='same')
        self.assertEqual(plan_['jobs'],[]);self.assertEqual(downloads,0)
        self.assertEqual(old['seed_round'],new['seed_round']);self.assertIn('publish=False',log)

if __name__=='__main__':unittest.main()
