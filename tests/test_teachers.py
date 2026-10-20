import contextlib,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'arena'))
import plan
from common import read,write,engine_revision,digest
from participants import builtin_identity
from highlights import viewing_guide
from ranking_history import snapshot

class TeacherTests(unittest.TestCase):
    def test_adding_bots_reuses_all_peer_pairs_and_never_downloads_bot_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'arena').mkdir();(root/'arena/worker.py').write_text('test-only-engine')
            config=dict(title='test',english_title='test',season=1,repository='test/test',drive_folder='test',seed_namespace='test',players=[dict(id=str(i),name=str(i),folder=str(i)) for i in range(4)])
            write(root/'arena.json',config);write(root/'fixture_manifest.json',{'models/rusher_bot.py':'a'*64,'models/sniper_bot.py':'b'*64})
            def meta(folder):return [dict(file_id=folder,filename='own.zip',metadata_fingerprint='revision0')]
            def get(pid,target):Path(target).write_bytes(('model'+pid).encode())
            with patch.object(plan,'ROOT',root),patch.object(plan,'model_metadata',side_effect=meta) as metadata,patch.object(plan,'download',side_effect=get) as download,patch.dict(os.environ,GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_OUTPUT=''):
                with contextlib.redirect_stdout(io.StringIO()):plan.main()
                old=read(root/'site/data/latest.json');old['pairs']=[dict(key=j['key'],a=j['a']['id'],b=j['b']['id'],complete=True) for j in read(root/'runtime/plan.json')['jobs']];write(root/'site/data/latest.json',old)
                config['players'] += [dict(id=k,name=k,code=k.upper(),kind='official_rulebot',bot=k) for k in ('rusher','sniper')];write(root/'arena.json',config)
                for p in (root/'runtime/models').iterdir():p.unlink()
                download.reset_mock();metadata.reset_mock()
                with contextlib.redirect_stdout(io.StringIO()):plan.main()
                jobs=read(root/'runtime/plan.json')['jobs'];new=read(root/'site/data/latest.json')
                self.assertEqual(len(jobs),9);self.assertTrue(all(any(p['id'] in ('rusher','sniper') for p in (j['a'],j['b'])) for j in jobs))
                self.assertEqual({p['key'] for p in new['pairs']},{p['key'] for p in old['pairs']});self.assertEqual(new['expected_games'],1500)
                self.assertEqual(metadata.call_count,4);self.assertEqual(download.call_count,4)
                self.assertTrue(all(call.args[0] not in ('rusher','sniper') for call in download.call_args_list))
                new['pairs'] += [dict(key=j['key'],a=j['a']['id'],b=j['b']['id'],complete=True) for j in jobs];write(root/'site/data/latest.json',new)
                download.reset_mock();capture=io.StringIO()
                with contextlib.redirect_stdout(capture):plan.main()
                self.assertEqual(read(root/'runtime/plan.json')['jobs'],[]);self.assertEqual(download.call_count,0);self.assertIn('publish=False',capture.getvalue())
                # Periodic polls must publish changed UI even if concurrency
                # coalesced/cancelled the push-triggered deployment.
                (root/'site/style.css').write_text('body{color:red}')
                capture=io.StringIO()
                with contextlib.redirect_stdout(capture):plan.main()
                self.assertEqual(read(root/'runtime/plan.json')['jobs'],[]);self.assertEqual(download.call_count,0);self.assertIn('publish=True',capture.getvalue())
    def test_rule_bot_dependencies_change_identity(self):
        hashes={'models/rusher_bot.py':'a','models/sniper_bot.py':'b'}
        first=builtin_identity('rusher',hashes);self.assertNotEqual(first,builtin_identity('sniper',hashes))
        self.assertNotEqual(first,builtin_identity('rusher',{**hashes,'models/sniper_bot.py':'changed'}))
        with self.assertRaises(ValueError):builtin_identity('madeup',hashes)
    def test_legacy_cache_requires_unchanged_policy_match_core(self):
        root=Path(__file__).resolve().parents[1];anchor=read(root/'arena/engine_compat.json')
        self.assertEqual(engine_revision(root),anchor['legacy_worker_sha256'])
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);(target/'arena').mkdir();write(target/'arena/engine_compat.json',anchor)
            worker=target/'arena/worker.py';worker.write_text((root/'arena/worker.py').read_text().replace('game.reset(seed)','game.reset(seed+1)'),encoding='utf-8')
            self.assertNotEqual(engine_revision(target),anchor['legacy_worker_sha256']);self.assertEqual(engine_revision(target),digest(worker))
    def test_six_pairs_is_not_a_complete_six_person_league(self):
        state=dict(players=[dict(id=str(i),sha256=str(i)) for i in range(6)],standings=[dict(id=str(i),rank=i+1,games=100,wins=50,draws=0,points=50) for i in range(6)],pairs=[dict(key=str(i),a='0',b='1',hashes={}) for i in range(6)],protocol={},total_games=600)
        self.assertFalse(snapshot(state)['complete_round_robin'])

class ViewingGuideTests(unittest.TestCase):
    def games(self):
        return [dict(id=f'{s}-{seat}',seed=s,a_seat=seat,winner='a',ticks=50+s,timeline=[],metrics={}) for s in range(50) for seat in ('ship1','ship2')]
    def test_guide_has20_balanced_seats_and_result_independent12(self):
        games=self.games();guide=viewing_guide(games,'a','b');self.assertEqual(len(guide['game_ids']),20);self.assertEqual(len(set(guide['game_ids'])),20);self.assertEqual(guide['seat_counts'],dict(ship1=10,ship2=10))
        self.assertEqual(len({r['seed'] for r in games if r['id'] in guide['game_ids'][:12]}),12)
        for row in games:row['winner']='b'
        self.assertEqual(guide['game_ids'][:12],viewing_guide(games,'a','b')['game_ids'][:12]);self.assertEqual(len(games),100)
    def test_rare_loss_and_draw_still_available_in_guide(self):
        games=self.games();games[-2]['winner']='b';games[-1]['winner']=None
        guide=viewing_guide(games,'a','b');self.assertIn(games[-2]['id'],guide['game_ids']);self.assertIn(games[-1]['id'],guide['game_ids'])

if __name__=='__main__':unittest.main()
