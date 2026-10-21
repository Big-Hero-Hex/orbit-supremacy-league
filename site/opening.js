/** Opening diagnostics: display cloud-derived fields only. No simulation or inference. */
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=n=>Number.isFinite(n)?`${(n*100).toFixed(1)}%`:'—',sec=n=>Number.isFinite(n)?`${n.toFixed(2)}s`:'—';
const ratio=(a,b)=>b?`${a} / ${b}`:'—';
export function silentLoss(game,id){const o=game.opening?.players?.[id];return Boolean(o&&o.first_loss!==null&&o.shots_before_loss===0);}
export const anySilentLoss=game=>Object.values(game.assignment).some(id=>silentLoss(game,id));
export function openingLine(game,name){
 const players=game.opening?.players;if(!players)return '';
 return ['ship1','ship2'].filter(seat=>players[game.assignment[seat]]).map(seat=>{const id=game.assignment[seat],o=players[id];
  const shot=o.first_shot===null?'整局未開火':`首發 ${sec(o.first_shot/50)}`,loss=o.first_loss===null?'未失船':`失船 ${sec(o.first_loss/50)} · 失船前 ${o.shots_before_loss} 發`;
  return `${seat==='ship1'?'藍':'紅'} ${name(id)}：${shot} · ${loss}`;}).join('　｜　');
}
const fields=[
 ['未開火就先失船',s=>`${pct(s.silent_loss_rate)} <small>${ratio(s.silent_losses,s.lost_first_ship)}</small>`],
 ['└ 其中失船前從未扣扳機',s=>ratio(s.silent_without_trigger,s.silent_losses)],
 ['失船前實際發射（中位數）',s=>Number.isFinite(s.shots_before_loss_median)?`${s.shots_before_loss_median} 發`:'—'],
 ['首發時間（中位數）',s=>sec(s.first_shot_median_s)],
 ['整局未開火',s=>`${s.never_fired} 局`],
 ['首次失船時間（中位數）',s=>sec(s.first_loss_median_s)],
 ['搶先開火率',s=>pct(s.fired_first_rate)],
 ['搶先時勝率 ／ 被搶先時勝率',s=>`${pct(s.win_rate_fired_first)} ／ ${pct(s.win_rate_opponent_fired_first)}`],
 ['失船前機頭對準敵人（±15°）',s=>pct(s.aim_before_loss_mean)],
 ['時序與官方發射數一致',s=>ratio(s.exact_games,s.games)]];
/** rows: [{id, opening}] for the selected statistics scope. */
export function renderOpening(rows,name){
 const ready=rows.filter(r=>r.opening?.games);
 if(!ready.length)return {summary:'等待雲端由既有錄影補齊逐局紀錄',table:'<p class="empty">尚無開局紀錄；下一次雲端發布會從既有錄影補算，不重跑比賽。</p>'};
 const worst=ready.filter(r=>Number.isFinite(r.opening.silent_loss_rate)).sort((a,b)=>b.opening.silent_loss_rate-a.opening.silent_loss_rate)[0];
 return {summary:worst?`未開火先失船最高：${name(worst.id)} ${pct(worst.opening.silent_loss_rate)}`:'目前範圍內無人失船',
  table:`<table><thead><tr><th>開局指標</th>${ready.map(r=>`<th>${esc(name(r.id))}</th>`).join('')}</tr></thead><tbody>${fields.map(([label,fn])=>`<tr><td>${label}</td>${ready.map(r=>`<td>${fn(r.opening)}</td>`).join('')}</tr>`).join('')}</tbody></table>`};
}
