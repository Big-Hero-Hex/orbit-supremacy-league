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
function renderWeakness(f){
 const p=f.loss_paths;
 const situations=f.situations.length?`<table><thead><tr><th>情境（依估計失分排序）</th><th>發生局數</th><th>發生時積分率</th><th>未發生時</th><th>估計失分</th></tr></thead><tbody>${f.situations.map(s=>`<tr><td>${esc(s.label)}</td><td>${s.games}</td><td>${fmt(s.score_rate_when,'pct')}</td><td>${fmt(s.score_rate_otherwise,'pct')}</td><td>${s.points_lost.toFixed(1)}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">此範圍沒有明顯失分情境。</p>';
 const behind=f.behind.length?`<ul class="diag-behind">${f.behind.map(s=>`<li>${esc(s.label)}：<b>${fmt(s.value,s.unit)}</b> · 最佳 ${fmt(s.best,s.unit)} · 第 ${s.rank}/${s.of}</li>`).join('')}</ul>`:'<p class="muted">沒有排名墊底的技術指標。</p>';
 return `${situations}<p class="diag-paths">輸掉的 ${p.lost_games} 局：飛行員被撞死 ${p.pilot_rammed}、被射殺 ${p.pilot_shot}；開局未開火就先失船 ${p.silent_first_loss}；先擊落對手卻仍輸 ${p.led_then_lost}。</p><h5>明顯落後的技術指標</h5>${behind}`;
}
