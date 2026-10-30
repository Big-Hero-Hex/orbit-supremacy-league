"""Up to two history snapshots may keep their full recordings; everything else is pruned."""
import json
from pathlib import Path

MAX_STARRED = 2


def load_starred(path):
    """Snapshot keys listed in the repo file, deduplicated and capped. Missing or malformed means none."""
    try:
        keys = json.loads(Path(path).read_text(encoding='utf-8')).get('snapshots', [])
    except (OSError, ValueError, AttributeError):
        return []
    unique = []
    for key in keys:
        if isinstance(key, str) and key and key not in unique:unique.append(key)
    return unique[:MAX_STARRED]


def pair_keys(entries, starred):
    return {p['key'] for e in entries if e.get('key') in starred for p in e.get('pairs', []) if p.get('key')}


def save_standings(entries, starred, state, folder):
    """The slim snapshot lacks per-weapon stats, so a starred latest snapshot also freezes its full standings."""
    if entries and entries[-1].get('key') in starred and state.get('standings'):
        target = Path(folder) / (entries[-1]['key'] + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'players': state['players'], 'standings': state['standings']}, ensure_ascii=False), encoding='utf-8')


def mark_replays(entries, starred, pairs_dir, starred_dir):
    """Flag each snapshot by whether its full recordings are still published (latest, or starred and intact)."""
    for index, point in enumerate(entries):
        last = index == len(entries) - 1
        point['starred'] = point.get('key') in starred
        keep = last or (point['starred'] and (Path(starred_dir) / (point['key'] + '.json')).is_file())
        point['replay_available'] = bool(keep and point.get('pairs') and all((Path(pairs_dir) / p['key'] / 'result.json').is_file() for p in point['pairs']))
    return entries
