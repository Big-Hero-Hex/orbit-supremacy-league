import copy,csv,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'arena'))
from ranking_history import snapshot,update_history,export_history

class RankingHistoryTests(unittest.TestCase):
    def state(self):
        return dict(updated_at='2026-10-20T12:00:00Z',players=[dict(id='a',name='甲',sha256='aaa',color='#fff')],
                    standings=[dict(id='a',rank=1,games=100,wins=81,losses=19,draws=0,points=81.,score_rate=.81,win_rate=.81,opponents=1)],
                    pairs=[dict(key='ab',a='a',b='b',hashes={'a':'aaa','b':'bbb'})],protocol={'version':1},total_games=100)
    def test_first_real_result_only_no_fabricated_predecessor(self):
        s=self.state();h=update_history({},[],s);self.assertEqual(len(h),1);self.assertEqual(h[0]['players'][0]['score_rate'],.81)
        self.assertEqual(update_history({},[],dict(players=[],standings=[])),[])
    def test_time_only_publish_is_not_a_new_point(self):
        s=self.state();s['ranking_history']=update_history({},[],s);new=copy.deepcopy(s);new['updated_at']='2026-10-21T12:00:00Z'
        self.assertEqual(len(update_history(s,[],new)),1)
    def test_change_and_revert_are_distinct_events(self):
        a=self.state();a['ranking_history']=update_history({},[],a);b=copy.deepcopy(a);b['players'][0]['sha256']='new';b['standings'][0]['wins']=90;b['standings'][0]['points']=90
        b['ranking_history']=update_history(a,[],b);self.assertEqual(len(b['ranking_history']),2)
        c=copy.deepcopy(a);self.assertEqual(len(update_history(b,[],c)),3)
    def test_survives_deleted_old_games_and_preserves_scope(self):
        a=self.state();a['ranking_history']=update_history({},[],a);b=copy.deepcopy(a);b['standings'][0]['rank']=2
        h=update_history(a,[],b);self.assertEqual(h[0]['players'][0]['rank'],1);self.assertEqual(h[1]['players'][0]['rank'],2)
        self.assertNotIn('games',h[0]);self.assertFalse(h[0]['complete_round_robin'])
    def test_missing_player_not_zero_and_csv_values_numeric(self):
        a=self.state();point=snapshot(a);self.assertEqual([p['id'] for p in point['players']],['a'])
        with tempfile.TemporaryDirectory() as t:
            export_history(t,[point]);p=Path(t)/'ranking_history.csv';self.assertTrue(p.read_bytes().startswith(b'\xef\xbb\xbf'))
            with p.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual(float(rows[0]['score_rate']),.81);self.assertEqual(rows[0]['name'],'甲');self.assertEqual(rows[0]['rank'],'1')
    def test_legacy_scores_migrate_without_games_or_videos(self):
        a=self.state();a['recorded_at']=a.pop('updated_at');b=self.state();b['players'][0]['sha256']='new'
        self.assertEqual(len(update_history({},[a],b)),2)

if __name__=='__main__':unittest.main()
