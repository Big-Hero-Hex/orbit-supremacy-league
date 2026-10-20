"""Twenty-game viewing guide, never used to compute standings or statistics."""
import hashlib

def viewing_guide(games,a,b):
    picked=[];reasons={};seats={'ship1':0,'ship2':0}
    def add(row,reason):
        if row is None or row['id'] in reasons or len(picked)>=20 or seats[row['a_seat']]>=10:return False
        picked.append(row['id']);reasons[row['id']]=reason;seats[row['a_seat']]+=1;return True
    # Twelve seeds chosen without looking at results or events; six per seat.
    seeds=sorted({r['seed'] for r in games},key=lambda s:hashlib.sha256(f'OSL-viewing-guide:{s}'.encode()).hexdigest())
    for i,seed in enumerate(seeds[:12]):
        add(next(r for r in games if r['seed']==seed and r['a_seat']==('ship1' if i%2==0 else 'ship2')),'一般局 · 結果無關固定seed抽樣')
    def pick(rows,reason):
        used={r['seed'] for r in games if r['id'] in reasons}
        for row in sorted(rows,key=lambda r:(r['seed'] in used,r['seed'],r['a_seat'])):
            if add(row,reason):return
    for winner,reason in [(a,'左方勝例'),(b,'右方勝例'),(None,'和局案例')]:pick([r for r in games if r['winner']==winner],reason)
    def comeback(r):
        es=[e for e in r.get('timeline',[]) if e['kind']=='eject']
        if not es or not r['winner']:return False
        first=min(e['tick'] for e in es);targets={e['target'] for e in es if e['tick']==first}
        return targets=={r['winner']}
    pick([r for r in games if comeback(r)],'先失船後逆轉')
    pick([r for r in games if any(e['kind']=='respawn' for e in r.get('timeline',[]))],'飛行員存活／復活')
    pick([r for r in games if any(m.get('laser_shots',0) for m in r.get('metrics',{}).values())],'雷射運用')
    for row in sorted(games,key=lambda r:(-r['ticks'],r['seed'],r['a_seat'])):
        if add(row,'最長拉鋸'):break
    for row in sorted(games,key=lambda r:(r['ticks'],r['seed'],r['a_seat'])):
        if add(row,'快速終結'):break
    # If a category never occurred, fill with typical-duration games, maintaining
    # exact 10/10 seats and preferring previously unrepresented seeds.
    lengths=sorted(r['ticks'] for r in games);median=lengths[len(lengths)//2]
    used={r['seed'] for r in games if r['id'] in reasons}
    for row in sorted(games,key=lambda r:(r['seed'] in used,abs(r['ticks']-median),r['seed'],r['a_seat'])):add(row,'一般局 · 接近中位局長')
    return dict(game_ids=picked,reasons=reasons,ordinary_count=12,seat_counts=seats,method='12 outcome-independent fixed seeds + up to8 win/loss/draw/comeback/respawn/laser/long/short cases; 10 seats each; guide is descriptive, all100 games determine every statistic')
