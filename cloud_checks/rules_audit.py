"""Cloud-only replay audit against the unmodified official evaluation wrapper.

No model inference, no training, no new ranked games. Reads current recordings.
"""
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, '/app')
from worker import AuditGame, counters, decode_action, visual
from envs.eval_astro_party_env import AstroPartyEvalEnv


def main():
    manifest = json.loads(Path('/manifest.json').read_text())
    hashes = {}
    for name, expected in manifest.items():
        actual = hashlib.sha256((Path('/official') / name).read_bytes()).hexdigest()
        assert actual == expected, f'Official fixture hash mismatch: {name}'
        hashes[name] = actual
    state = json.loads(Path('/data/latest.json').read_text())
    assert state['protocol']['game_hash'] == hashes['envs/game.py']
    assert state['protocol']['deterministic'] and state['protocol']['seat_swap']
    assert state['protocol']['max_ticks'] == 1500
    checked = []
    for pair in state['pairs']:
        games = pair['games']
        assert len(games) == 100 and len({r['seed'] for r in games}) == 50
        assert all(sum(r['a_seat'] == s for r in games) == 50 for s in ('ship1', 'ship2'))
        assert len(pair['videos']) <= 4
        assert len(pair['viewing_guide']['game_ids']) == 20
        for player in (pair['a'], pair['b']):
            wins = sum(r['winner'] == player for r in games)
            draws = sum(r['winner'] is None for r in games)
            assert pair['stats'][player]['wins'] == wins
            assert pair['stats'][player]['draws'] == draws
            assert pair['stats'][player]['score_rate'] == (wins + .5 * draws) / 100
        # One fixed game and the longest game, without loading either model.
        selected = {games[0]['id']: games[0]}
        longest = max(games, key=lambda r: r['ticks'])
        selected[longest['id']] = longest
        base = Path('/data/pairs') / pair['key']
        for row in selected.values():
            arrays = np.load(base / row['audit'], allow_pickle=False)
            with gzip.open(base / row['replay'], 'rt', encoding='utf-8') as f:
                record = json.load(f)
            recorded = {f['t']: f for f in record['frames']}
            env = AstroPartyEvalEnv()
            obs, _ = env.reset(seed=row['seed'])
            audit = AuditGame()
            audit.reset(row['seed'])
            audit.audit = counters()
            audit.laser_active = False
            steps = 0
            try:
                assert visual(env.game) == recorded[env.game.t]
                for actions, saved_obs in zip(arrays['actions'], arrays['observations']):
                    for i, seat in enumerate(('ship1', 'ship2')):
                        assert np.array_equal(obs[seat], saved_obs[i]), (pair['key'], row['id'], steps, 'saved_obs')
                        assert np.array_equal(obs[seat], audit.observe(seat))
                    decoded = {s: decode_action(actions[i]) for i, s in enumerate(('ship1', 'ship2'))}
                    obs, rewards, terms, truncs, _ = env.step(decoded)
                    audit.step(decoded)
                    steps += 1
                    assert env.game.t == audit.t
                    assert env.game.done == audit.done and env.game.truncated == audit.truncated
                    assert visual(env.game) == visual(audit)
                    if env.game.t in recorded:
                        assert visual(env.game) == recorded[env.game.t]
                assert steps == len(arrays['actions']) == len(arrays['observations'])
                assert env.game.done or env.game.truncated
                assert env.game.t == row['ticks'] <= 1500
                alive = [s for s in ('ship1', 'ship2') if env.ships[s].alive]
                winner = row['assignment'][alive[0]] if len(alive) == 1 else None
                assert winner == row['winner'] == record['winner']
                checked.append({'pair':pair['key'],'game':row['id'],'steps':steps,'winner':winner,
                                'saved_observations_exact':True,'all_recorded_frames_exact':True,
                                'official_wrapper_vs_audited_game_exact':True})
            finally:
                env.close()
    out = {'passed':True,'new_ranked_games':0,'model_inferences':0,'training_updates':0,
           'official_source_hashes':hashes,'all_pairs_statistics_checked':len(state['pairs']),
           'current_games':state['total_games'],'replayed_games':len(checked),'checks':checked,
           'ranking_difference':'OSL game-score rate includes teachers; TA private round robin ranks match win rate among peers. OSL seeds and seat schedule are not the private TA schedule.',
           'cloud_only':True}
    Path('/out/rules_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k not in ('checks','official_source_hashes')},ensure_ascii=False))


if __name__ == '__main__':
    main()
