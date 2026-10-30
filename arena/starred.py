"""Up to two history snapshots may keep their full recordings; everything else is pruned."""
import hashlib
import json
import re
from pathlib import Path

MAX_STARRED = 2


def load_starred(path, folder=None):
    """Manually starred snapshot keys, newest star first, capped.

    Sources: starred/<key>.json files (one click from the page, optional "starred_at" ISO time so the newest
    star wins) and the legacy starred_snapshots.json list. Missing or malformed input means none."""
    stamped = []
    if folder and Path(folder).is_dir():
        for file in Path(folder).glob('*.json'):
            if not re.fullmatch(r'[0-9a-f]{8,64}', file.stem):continue
            try:
                when = json.loads(file.read_text(encoding='utf-8')).get('starred_at') or ''
            except (OSError, ValueError, AttributeError):
                when = ''
            stamped.append((str(when), file.stem))
    keys = [key for _, key in sorted(stamped, reverse=True)]
    try:
        keys += json.loads(Path(path).read_text(encoding='utf-8')).get('snapshots', [])
    except (OSError, ValueError, AttributeError):
        pass
    unique = []
    for key in keys:
        if isinstance(key, str) and key and key not in unique:unique.append(key)
    return unique[:MAX_STARRED]


def starred_revision(keys):
    """Lets the planner notice a changed star list even when a push is coalesced into a scheduled run."""
    return hashlib.sha256(json.dumps(list(keys)).encode()).hexdigest()[:16]


def effective_starred(entries, manual):
    """The previous snapshot is always kept automatically; the manual list fills what is left of the two slots."""
    keys = []
    if len(entries) > 1 and entries[-2].get('key'):keys.append(entries[-2]['key'])
    for key in manual:
        if key not in keys:keys.append(key)
    return keys[:MAX_STARRED]


def pair_keys(entries, starred):
    return {p['key'] for e in entries if e.get('key') in starred for p in e.get('pairs', []) if p.get('key')}


def save_standings(entries, starred, state, folder):
    """The slim snapshot lacks per-weapon stats, so the latest snapshot always freezes its full standings
    (it becomes the automatic previous one next time); files no longer retained are removed."""
    folder = Path(folder)
    if entries and state.get('standings'):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (entries[-1]['key'] + '.json')).write_text(json.dumps({'players': state['players'], 'standings': state['standings'], 'weaknesses': state.get('weaknesses')}, ensure_ascii=False), encoding='utf-8')
    keep = set(starred) | ({entries[-1]['key']} if entries else set())
    if folder.is_dir():
        for old in folder.glob('*.json'):
            if old.stem not in keep:old.unlink()


def mark_replays(entries, starred, pairs_dir, starred_dir, manual=()):
    """Flag each snapshot by whether its full recordings are still published (latest, or starred and intact)."""
    for index, point in enumerate(entries):
        last = index == len(entries) - 1
        point['starred'] = point.get('key') in starred
        point['manual_starred'] = point.get('key') in manual
        point['auto_starred'] = bool(index == len(entries) - 2)
        keep = last or (point['starred'] and (Path(starred_dir) / (point['key'] + '.json')).is_file())
        point['replay_available'] = bool(keep and point.get('pairs') and all((Path(pairs_dir) / p['key'] / 'result.json').is_file() for p in point['pairs']))
    return entries
