/** Weakness diagnostics: display cloud-derived fields only. No simulation or inference. */
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,unit)=>!Number.isFinite(v)?'—':unit==='pct'?`${(v*100).toFixed(1)}%`:unit==='s'?`${v.toFixed(2)}s`:`${v.toFixed(1)} ${unit}`;
// Same keys, labels and directions as arena/diagnostics.py SKILLS.
const skills=[
 ['accuracy','命中率','high','pct'],['enemy_accuracy','被命中率（對手命中自己）','low','pct'],['shot_discipline','開火時對準敵人（±15°）','high','pct'],
 ['asteroid_share','子彈打到小行星','low','pct'],['aim_share','船型時對準敵人（±15°）','high','pct'],['exposed_share','被持彈敵人瞄準的時間','low','pct'],
 ['loss_empty_share','失船時空彈且無雷射','low','pct'],['loss_facing_away_share','失船時背對敵人','low','pct'],['pilot_survival','飛行員存活到復活','high','pct'],
 ['pilot_rammed_share','飛行員死亡中被撞死','low','pct'],['pilot_distance','飛行員與敵船平均距離','high','px'],['finish_rate','擊落後補刀成功','high','pct'],
 ['finish_time_s','補刀時間（中位數）','low','s'],['speed','船型平均速度（不排名）',null,'px/s'],['turn_flips_per_s','轉向來回切換／秒（不排名）',null,'/s']];
/** rows: [{id, diag, found}] for the selected statistics scope. */
export function renderDiagnostics(rows,name,selected){
 const ready=rows.filter(r=>r.diag?.games);
 if(!ready.length)return {skills:'<p class="empty">尚無弱點診斷；下一次雲端發布會從既有錄影補算，不重跑比賽。</p>',options:'',selected:null,weakness:''};
 const table=`<table><thead><tr><th>技術指標</th>${ready.map(r=>`<th>${esc(name(r.id))}</th>`).join('')}</tr></thead><tbody>${skills.map(([key,label,better,unit])=>{
  const values=ready.map(r=>r.diag.rates[key]),known=values.filter(Number.isFinite),worst=better&&known.length>1?(better==='high'?Math.min(...known):Math.max(...known)):null;
  return `<tr><td>${label}</td>${values.map(v=>`<td${Number.isFinite(v)&&v===worst?' class="diag-worst" title="此範圍內最差"':''}>${fmt(v,unit)}</td>`).join('')}</tr>`;}).join('')}</tbody></table>`;
 const ids=ready.filter(r=>r.found).map(r=>r.id),pick=ids.includes(selected)?selected:ids[0],found=ready.find(r=>r.id===pick)?.found;
 return {skills:table,options:ids.map(id=>`<option value="${esc(id)}"${id===pick?' selected':''}>${esc(name(id))}</option>`).join(''),selected:pick??null,weakness:found?renderWeakness(found):''};
}
const replays=items=>items?.length?items.map((x,i)=>`<a class="diag-replay" href="#game=${encodeURIComponent(x.pair)}/${encodeURIComponent(x.game_id)}@${x.at}" title="開啟重播，從失誤前 2 秒開始">▶${i+1}</a>`).join(''):'—';
const change=r=>!Number.isFinite(r.change)?'—':`<span class="${r.improved?'diag-better':r.improved===false?'diag-worse':''}">${r.change>0?'+':''}${(r.change*100).toFixed(1)} 個百分點${r.improved?' 改善':r.improved===false?' 退步':''}</span>`;
function renderConditions(c){
 if(!c)return '';
 const rows=[['出生朝向',c.spawn],['開局被瞄準',c.pressure]].flatMap(([kind,groups])=>groups.filter(g=>g.games).map(g=>`<tr><td>${kind} ${esc(g.label)}</td><td>${g.games}</td><td>${fmt(g.silent_loss_rate,'pct')}</td><td>${fmt(g.face_median_s,'s')}</td><td>${fmt(g.score_rate,'pct')}</td></tr>`)).join('');
 return `<h5>開局條件</h5><p class="muted">出生朝向＝出生時機頭偏離對手的角度；開局被瞄準＝開賽頭 1.5 秒內被持彈敵人瞄準的時間比例。未開火先失船以有失船的局為分母。</p><table><thead><tr><th>分組</th><th>局數</th><th>未開火先失船</th><th>對準所需時間（中位）</th><th>積分率</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function renderVersions(v){
 if(!v)return '';
 const b=v.previous_version;
 if(!b)return '<h5>與上一版比較</h5><p class="muted">尚無上一版的診斷紀錄；下一次換版後會自動比較。</p>';
 return `<h5>與上一版比較</h5><p class="muted">上一版 <code>${esc(b.sha256.slice(0,12))}</code>（開局輪 ${esc(b.seed_round)}）→ 目前 <code>${esc(v.current.sha256.slice(0,12))}</code>（${esc(v.current.seed_round)}）。${b.same_round?'同一開局輪。':'開局輪不同，對手也可能換版，變化不能全歸因於模型。'}</p><table><thead><tr><th>指標</th><th>上一版</th><th>目前</th><th>變化</th></tr></thead><tbody>${b.rows.map(r=>`<tr><td>${esc(r.label)}</td><td>${fmt(r.before,'pct')}</td><td>${fmt(r.after,'pct')}</td><td>${change(r)}</td></tr>`).join('')}</tbody></table>`;
}
function renderWeakness(f){
 const p=f.loss_paths;
 const situations=f.situations.length?`<table><thead><tr><th>情境（依估計失分排序）</th><th>發生局數</th><th>發生時積分率</th><th>未發生時</th><th>估計失分</th><th>重播</th></tr></thead><tbody>${f.situations.map(s=>`<tr><td>${esc(s.label)}</td><td>${s.games}</td><td>${fmt(s.score_rate_when,'pct')}</td><td>${fmt(s.score_rate_otherwise,'pct')}</td><td>${s.points_lost.toFixed(1)}</td><td>${replays(s.examples)}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">此範圍沒有明顯失分情境。</p>';
 const behind=f.behind.length?`<ul class="diag-behind">${f.behind.map(s=>`<li>${esc(s.label)}：<b>${fmt(s.value,s.unit)}</b> · 最佳 ${fmt(s.best,s.unit)} · 第 ${s.rank}/${s.of}</li>`).join('')}</ul>`:'<p class="muted">沒有排名墊底的技術指標。</p>';
 return `${situations}<p class="diag-paths">輸掉的 ${p.lost_games} 局：飛行員被撞死 ${p.pilot_rammed}${p.rammed_examples?.length?`（${replays(p.rammed_examples)}）`:''}、被射殺 ${p.pilot_shot}；開局未開火就先失船 ${p.silent_first_loss}；先擊落對手卻仍輸 ${p.led_then_lost}。</p><h5>明顯落後的技術指標</h5>${behind}${renderConditions(f.opening_conditions)}${renderVersions(f.version_comparison)}`;
}
// Same keys as arena/mistakes.py METRICS; each value is a share of applicable ticks.
const mistakes=[['open_not_turning','開局沒轉向對手'],['missed_shot','能命中卻不開火'],['blocked_fire','射線被擋仍開火'],['exposed_unarmed','被瞄準時沒面向敵人'],
 ['thrust_away_close','近距離背對推進'],['pilot_exposed','飛行員暴露在敵船視線'],['finish_passive','不追擊近處敵方飛行員'],['empty_charge','空彈還衝向敵人']];
/** rows: [{id, m}] with each player's conceptual-mistake summary for the scope. */
export function renderMistakes(rows,name){
 const ready=rows.filter(r=>r.m?.games);
 if(!ready.length)return '<p class="empty">尚無概念性失誤資料；下一次雲端發布會從既有動作／觀測紀錄補算。</p>';
 const line=(label,values,unit,worse)=>{const known=values.filter(Number.isFinite),worst=known.length>1?(worse==='high'?Math.max(...known):Math.min(...known)):null;
  return `<tr><td>${label}</td>${values.map(v=>`<td${Number.isFinite(v)&&v===worst?' class="diag-worst" title="此範圍內最差"':''}>${unit==='deg'?(Number.isFinite(v)?`${v.toFixed(0)}°`:'—'):unit==='cos'?(Number.isFinite(v)?v.toFixed(2):'—'):fmt(v,'pct')}</td>`).join('')}</tr>`;};
 return `<table><thead><tr><th>失誤（發生 tick ÷ 適用 tick）</th>${ready.map(r=>`<th>${esc(name(r.id))}</th>`).join('')}</tr></thead><tbody>${mistakes.map(([key,label])=>line(label,ready.map(r=>r.m.rates[key]),'pct','high')).join('')}${line('開局 1 秒偏離提前量（中位）',ready.map(r=>r.m.angle_1s_median),'deg','high')}${line('飛行員逃離方向 cos（越高越好）',ready.map(r=>r.m.pilot_flee_cos),'cos','low')}</tbody></table>`;
}
