"""Calendar, shared draw, retry and migration checks; no game/model execution."""
import copy,sys,unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'arena'))
from common import seeds
from seed_round import select_round

class SeedRoundTests(unittest.TestCase):
    config={'seed_namespace':'test','seed_rotation':{'first_rotation_at':'2026-10-22T04:00:00+08:00','interval_hours':24}}
    def draw(self,time,previous=None,persisted=None,nonce='test-entropy'):
        return select_round(self.config,previous or {},persisted,at=datetime.fromisoformat(time),entropy=lambda:nonce)
    def test_rollout_keeps_legacy_seeds_until_first_taipei_boundary(self):
        old=self.draw('2026-10-21T19:59:59+00:00')
        self.assertEqual(old['id'],'legacy-s01');self.assertEqual(old['seeds'],seeds('test'))
        self.assertEqual(old['next_rotation_at'],'2026-10-21T20:00:00+00:00')
        new=self.draw('2026-10-21T20:00:00+00:00',{'seed_round':old,'protocol':{'seeds':old['seeds']}})
        self.assertEqual(new['id'],'daily-20261022');self.assertEqual(new['next_rotation_at'],'2026-10-22T20:00:00+00:00')
        self.assertEqual(len(set(new['seeds'])),50);self.assertTrue(set(new['seeds']).isdisjoint(old['seeds']))
    def test_failed_publication_retry_reuses_persisted_draw(self):
        drawn=self.draw('2026-10-21T20:00:00+00:00')
        self.assertEqual(self.draw('2026-10-21T20:05:00+00:00',persisted=drawn,nonce='different'),drawn)
    def test_manifest_recovers_draw_when_release_asset_missing(self):
        drawn=self.draw('2026-10-21T20:00:00+00:00')
        self.assertEqual(self.draw('2026-10-22T03:00:00+00:00',previous={'seed_round':drawn},nonce='new'),drawn)
    def test_missed_days_draw_only_current_round_not_a_backlog(self):
        new=self.draw('2026-10-24T23:00:00+08:00')
        self.assertEqual(new['id'],'daily-20261024');self.assertEqual(new['next_rotation_at'],'2026-10-24T20:00:00+00:00')
    def test_next_day_gets_fresh_entropy(self):
        a=self.draw('2026-10-22T04:00:00+08:00')
        b=self.draw('2026-10-23T04:00:00+08:00',{'seed_round':a,'protocol':{'seeds':a['seeds']}},a,nonce='fresh')
        self.assertNotEqual(a['id'],b['id']);self.assertTrue(set(a['seeds']).isdisjoint(b['seeds']))
    def test_corrupt_same_round_and_clock_rollback_fail_closed(self):
        a=self.draw('2026-10-22T04:00:00+08:00');bad=copy.deepcopy(a);bad['seeds'][1]=bad['seeds'][0]
        with self.assertRaises(ValueError):self.draw('2026-10-22T04:05:00+08:00',persisted=bad)
        with self.assertRaises(ValueError):self.draw('2026-10-21T04:00:00+08:00',persisted=a)
    def test_unscheduled_projects_remain_compatible(self):
        self.assertIsNone(select_round({'seed_namespace':'legacy'},{}))

if __name__=='__main__':unittest.main()
