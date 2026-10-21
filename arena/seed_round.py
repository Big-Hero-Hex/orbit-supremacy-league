"""One shared seed draw per cloud round; retries reuse the persisted draw."""
import secrets
from datetime import datetime, timedelta, timezone
from common import seeds


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Seed rotation timestamps must include a timezone')
    return result.astimezone(timezone.utc)


def select_round(config, previous, persisted=None, at=None, entropy=None):
    schedule = config.get('seed_rotation')
    if not schedule:
        return None
    first = timestamp(schedule['first_rotation_at'])
    interval = timedelta(hours=int(schedule['interval_hours']))
    if interval.total_seconds() <= 0:
        raise ValueError('Seed rotation interval must be positive')
    current = at or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('Seed rotation clock must include a timezone')
    index = int((current - first) // interval)
    round_id = 'legacy-s01' if index < 0 else 'daily-' + (first + index * interval).astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    start = None if index < 0 else (first + index * interval).isoformat()
    end = first.isoformat() if index < 0 else (first + (index + 1) * interval).isoformat()
    # Freeze before any games. A failed worker/publish never redraws the round.
    for saved in (persisted, previous.get('seed_round')):
        if not saved:
            continue
        if timestamp(saved['next_rotation_at']) > timestamp(end):
            raise ValueError('Refusing to roll seed state backwards')
        if saved.get('id') == round_id:
            values = saved.get('seeds', [])
            if len(values) != 50 or len(set(values)) != 50 or any(type(s) is not int or not 10_000_000 <= s < 2_000_000_000 for s in values):
                raise ValueError('Corrupt shared seed draw; refusing to redraw silently')
            if saved['next_rotation_at'] != end or saved.get('starts_at') != start:
                raise ValueError('Existing seed round schedule changed; explicit migration required')
            return saved
    values = seeds(config['seed_namespace'])
    nonce = None
    if index >= 0:
        nonce = (entropy or (lambda: secrets.token_hex(32)))()
        # No next-round seeds are announced before its cloud draw. Exclude the
        # preceding published set so even an unlikely collision cannot persist.
        excluded = set(previous.get('protocol', {}).get('seeds', []))
        values = [s for s in seeds(f"{config['seed_namespace']}:{round_id}:{nonce}", 100) if s not in excluded][:50]
    return dict(id=round_id, starts_at=start, next_rotation_at=end,
                interval_hours=int(schedule['interval_hours']), timezone='Asia/Taipei',
                seeds=values, draw_nonce=nonce,
                draw_method='legacy-fixed' if index < 0 else 'cloud-csprng-sha256',
                seed_count=50, games_per_pair=100)
