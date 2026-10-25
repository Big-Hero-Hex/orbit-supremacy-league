"""Invalid uploads and retry handling without loading code or playing games."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'arena'))
import plan
from common import read, write, pair_key, engine_revision
from model_archive import validate_archive
from failures import failure_record, retry_deferred


def archive_bytes(valid=True):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        if valid:
            z.writestr('data', json.dumps({'fixture': True}))
            z.writestr('policy.pth', b'not-executed-test-tensor')
        else:
            z.writestr('main.tex', 'report template')
    return out.getvalue()


class ReadinessTests(unittest.TestCase):
    def test_report_zip_is_not_marked_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'model.zip'; p.write_bytes(archive_bytes(False))
            r = validate_archive(p)
            self.assertEqual(r['status'], 'invalid')
            self.assertIn('policy.pth', r['message'])
            p.write_bytes(archive_bytes())
            self.assertEqual(validate_archive(p)['status'], 'valid')

    def test_non_zip_and_bad_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'model.zip'; p.write_bytes(b'not a zip')
            self.assertEqual(validate_archive(p)['status'], 'invalid')
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('data', 'not json'); z.writestr('policy.pth', b'fixture')
            self.assertEqual(validate_archive(p)['status'], 'invalid')

    def test_invalid_cached_without_download_repair_same_file_id_reschedules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'arena').mkdir(); (root / 'arena/worker.py').write_text('# fixture')
            players = [dict(id=str(i), name=str(i), folder=str(i)) for i in range(3)]
            write(root / 'arena.json', dict(title='t', english_title='t', season=1, repository='t/t', drive_folder='t', seed_namespace='t', players=players))
            revision = {'0': 'r0', '1': 'r0', '2': 'r0'}
            payload = {'0': archive_bytes(), '1': archive_bytes(), '2': archive_bytes(False)}
            def meta(folder):return [dict(file_id=folder, filename='model.zip', metadata_fingerprint=revision[folder])]
            def get(fid, target):Path(target).write_bytes(payload[fid])
            with patch.object(plan, 'ROOT', root), patch.object(plan, 'model_metadata', side_effect=meta), patch.object(plan, 'download', side_effect=get) as download, patch.dict(os.environ, {'GITHUB_OUTPUT':'', 'GITHUB_EVENT_NAME':'workflow_dispatch'}), contextlib.redirect_stdout(io.StringIO()):
                plan.main(); state = read(root / 'site/data/latest.json'); job = read(root / 'runtime/plan.json')['jobs'][0]
                self.assertEqual([p['status'] for p in state['players']], ['ready', 'ready', 'invalid'])
                state['pairs'] = [dict(key=job['key'], complete=True, a='0', b='1')]
                write(root / 'site/data/latest.json', state)
                for f in (root / 'runtime/models').iterdir():f.unlink()
                download.reset_mock(); plan.main()
                self.assertEqual(read(root / 'runtime/plan.json')['jobs'], [])
                self.assertEqual(download.call_count, 0)
                payload['2'] = archive_bytes(); revision['2'] = 'r1'; plan.main()
                jobs = read(root / 'runtime/plan.json')['jobs']
                self.assertEqual(len(jobs), 2)
                self.assertTrue(all('2' in (j['a']['id'], j['b']['id']) for j in jobs))
                self.assertEqual(len(read(root / 'site/data/latest.json')['pairs']), 1)
                # One failed pair waits; its unrelated pair can still start.
                state = read(root / 'site/data/latest.json')
                state['failures'] = [failure_record(jobs[0], ValueError('fixture failed'))]
                write(root / 'site/data/latest.json', state); plan.main()
                pending = read(root / 'runtime/plan.json')
                self.assertEqual(len(pending['jobs']), 1)
                self.assertEqual(len(pending['deferred_failures']), 1)
                # A genuine replacement bypasses this old hash-bound cooldown.
                revision['2'] = 'r2'
                payload['2'] = payload['2'] + b'new-revision'
                plan.main()
                self.assertEqual(len(read(root / 'runtime/plan.json')['jobs']), 2)

    def test_runtime_failure_has_reason_and_bounded_retry(self):
        at = datetime(2026,10,25,14,tzinfo=timezone.utc)
        job = dict(a={'id':'a'}, b={'id':'b'}, key='key')
        exc = subprocess.CalledProcessError(1, ['docker'], output='Traceback...\nValueError: missing custom extractor\n')
        record = failure_record(job, exc, at=at)
        self.assertIn('missing custom extractor', record['message'])
        self.assertTrue(retry_deferred(record, at + timedelta(minutes=5)))
        self.assertFalse(retry_deferred(record, at + timedelta(minutes=30)))
        self.assertNotIn('winner', record)
        self.assertEqual(failure_record(job, exc, record, at)['attempts'], 2)

    def test_worker_engine_identity_did_not_change(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(engine_revision(root), read(root/'arena/engine_compat.json')['legacy_worker_sha256'])


if __name__ == '__main__':unittest.main()
