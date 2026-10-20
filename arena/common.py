"""Trusted league orchestration. No policy loading in this process."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def now():
    return datetime.now(timezone.utc).isoformat()

def next_check():
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    while t.minute % 10 != 3: t += timedelta(minutes=1)
    return t.isoformat()

def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    temp.replace(path)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def seeds(namespace, count=50):
    result = []
    i = 0
    while len(result) < count:
        candidate = 10_000_000 + int(hashlib.sha256(f"{namespace}:{i}".encode()).hexdigest()[:10], 16) % 1_990_000_000
        if candidate not in result:
            result.append(candidate)
        i += 1
    return result

def pair_key(a, b, protocol):
    raw = json.dumps([a["id"], a["sha256"], b["id"], b["sha256"], protocol], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:28]
