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
                     **{k:person.get(k) for k in ('name','code','color','sha256','kind')}})
    pairs=sorted(({k:p.get(k) for k in ('key','a','b','hashes')} for p in state.get('pairs',[])),key=lambda p:p['key'])
    protocol=hashlib.sha256(json.dumps(state.get('protocol',{}),sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
    competitive={'players':[{k:r[k] for k in ('id','sha256','rank','games','wins','draws','points')} for r in sorted(rows,key=lambda r:r['id'])],
                 'pairs':pairs,'protocol':protocol}
    key=hashlib.sha256(json.dumps(competitive,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
    return dict(key=key,recorded_at=recorded_at or state.get('recorded_at') or state.get('updated_at'),players=rows,pairs=pairs,
                total_games=state.get('total_games') or sum(r['games'] for r in rows)//2,
                complete_round_robin=bool(state.get('complete_round_robin',len(pairs)==len(people)*(len(people)-1)//2)),protocol=protocol)


def annotate_history(entries):
    """Derive every participant change, including old snapshots, without new points."""
    annotated=[]
    previous=None
    for original in entries:
        point=dict(original)
        current={p['id']:p for p in point['players']}
        old={p['id']:p for p in previous['players']} if previous else {}
        updates=[];added=[];removed=[];notes=[];kinds=[]
        if previous is None:
            notes.append('首次建榜：'+'、'.join(p['name'] for p in current.values()))
            kinds.append('baseline')
        else:
            for pid,p in current.items():
                if pid not in old:
                    added.append(dict(id=pid,name=p['name'],sha256=p.get('sha256'),kind=p.get('kind')))
                elif old[pid].get('sha256') and p.get('sha256') and old[pid]['sha256']!=p['sha256']:
                    updates.append(dict(id=pid,name=p['name'],old_sha256=old[pid]['sha256'],new_sha256=p['sha256'],kind=p.get('kind')))
            removed=[dict(id=pid,name=p['name']) for pid,p in old.items() if pid not in current]
            if updates:
                kinds.append('model_update');notes.append('模型換版：'+'、'.join(p['name'] for p in updates))
            if added:
                kinds.append('participant_added');notes.append('新增對手：'+'、'.join(p['name'] for p in added))
            if removed:
                kinds.append('participant_removed');notes.append('移出對手：'+'、'.join(p['name'] for p in removed))
            if previous.get('protocol')!=point.get('protocol'):
                kinds.append('protocol_change');notes.append('賽制／評估版本變更')
            if not notes:
                kinds.append('results_update');notes.append('戰績補齊／結果更新（未偵測到模型換版）')
        point.update(model_updates=updates,participants_added=added,participants_removed=removed,
                     change_kinds=kinds,change_summary='；'.join(notes))
        annotated.append(point)
        previous=point
    return annotated


def update_history(previous, archived, state):
    # The light manifest preserves snapshots even if all old replay files vanish.
    entries=list(previous.get('ranking_history',[]))
    def add(point):
        if point and (not entries or entries[-1]['key']!=point['key']):entries.append(point)
    if not entries:
        for old in archived:add(snapshot(old))
    add(snapshot(previous))
    add(snapshot(state))
    return annotate_history(entries)


def export_history(folder, entries):
    fields=['snapshot','recorded_at','player_id','name','rank','score_rate','points','games','wins','losses','draws','win_rate','opponents','model_sha256','complete_round_robin','protocol','changed_player_ids','changed_player_names','change_summary','model_updates_json']
    with (Path(folder)/'ranking_history.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for index,point in enumerate(annotate_history(entries),1):
            for row in point['players']:
                writer.writerow(dict(snapshot=index,recorded_at=point['recorded_at'],player_id=row['id'],name=row['name'],
                    **{k:row.get(k) for k in ('rank','score_rate','points','games','wins','losses','draws','win_rate','opponents')},
                    model_sha256=row['sha256'],complete_round_robin=point['complete_round_robin'],protocol=point['protocol'],
                    changed_player_ids=';'.join(p['id'] for p in point['model_updates']),
                    changed_player_names='、'.join(p['name'] for p in point['model_updates']),
                    change_summary=point['change_summary'],model_updates_json=json.dumps(point['model_updates'],ensure_ascii=False)))
