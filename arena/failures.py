"""Visible bounded retry state for failed pairs; never invent game outcomes."""
from datetime import datetime, timedelta, timezone
import re
import subprocess


def retry_deferred(failure, at=None):
    try:
        return datetime.fromisoformat(failure['retry_after']) > (at or datetime.now(timezone.utc))
    except (KeyError, TypeError, ValueError):
        return False


def failure_record(job, exc, previous=None, at=None):
    at = at or datetime.now(timezone.utc)
    detail = str(exc)
    if isinstance(exc, subprocess.CalledProcessError):
        log = exc.stderr or exc.output or ''
        if isinstance(log, bytes):
            log = log.decode('utf-8', errors='replace')
        lines = re.sub(r'\x1b\[[0-9;]*m', '', log).splitlines()
        errors = [line.strip() for line in lines if re.match(r'^[\w.]*Error:', line.strip())]
        detail = errors[-1] if errors else f'隔離執行結束碼 {exc.returncode}；請查看雲端執行紀錄'
    if isinstance(exc, subprocess.TimeoutExpired):
        detail = f'隔離比賽超過 {exc.timeout} 秒上限'
    return dict(a=job['a']['id'], b=job['b']['id'], key=job['key'],
                message=f'比賽未完成：{detail[:400]}。不判定勝負；30分鐘後重試，模型換版立即重新檢查。',
                failed_at=at.isoformat(), retry_after=(at + timedelta(minutes=30)).isoformat(),
                attempts=(previous or {}).get('attempts', 0) + 1)
