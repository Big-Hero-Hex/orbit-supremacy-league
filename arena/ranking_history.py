"""Small score snapshots independent of replaceable game/video archives."""
import csv
import hashlib
import json
from pathlib import Path


def snapshot(state, recorded_at=None):
    if not state.get('standings'):
        return None
    people={p['id']:p for p in state['players']}
    rows=[]
    for row in state['standings']:
        person=people[row['id']]
        rows.append({**{k:row.get(k) for k in ('id','rank','games','wins','losses','draws','points','score_rate','win_rate','opponents')},
                     **{k:person.get(k) for k in ('name','code','color','sha256')}})
    pairs=sorted(({k:p.get(k) for k in ('key','a','b','hashes')} for p in state.get('pairs',[])),key=lambda p:p['key'])
    protocol=hashlib.sha256(json.dumps(state.get('protocol',{}),sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
    competitive={'players':[{k:r[k] for k in ('id','sha256','rank','games','wins','draws','points')} for r in sorted(rows,key=lambda r:r['id'])],
                 'pairs':pairs,'protocol':protocol}
    key=hashlib.sha256(json.dumps(competitive,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
    return dict(key=key,recorded_at=recorded_at or state.get('recorded_at') or state.get('updated_at'),players=rows,pairs=pairs,
                total_games=state.get('total_games') or sum(r['games'] for r in rows)//2,
                complete_round_robin=bool(state.get('complete_round_robin') or len(pairs)==6),protocol=protocol)


def update_history(previous, archived, state):
    # The light manifest preserves snapshots even if all old replay files vanish.
    entries=list(previous.get('ranking_history',[]))
    def add(point):
        if point and (not entries or entries[-1]['key']!=point['key']):entries.append(point)
    if not entries:
        for old in archived:add(snapshot(old))
    add(snapshot(previous))
    add(snapshot(state))
    return entries


def export_history(folder, entries):
    fields=['snapshot','recorded_at','player_id','name','rank','score_rate','points','games','wins','losses','draws','win_rate','opponents','model_sha256','complete_round_robin','protocol']
    with (Path(folder)/'ranking_history.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for index,point in enumerate(entries,1):
            for row in point['players']:
                writer.writerow(dict(snapshot=index,recorded_at=point['recorded_at'],player_id=row['id'],name=row['name'],
                    **{k:row.get(k) for k in ('rank','score_rate','points','games','wins','losses','draws','win_rate','opponents')},
                    model_sha256=row['sha256'],complete_round_robin=point['complete_round_robin'],protocol=point['protocol']))
