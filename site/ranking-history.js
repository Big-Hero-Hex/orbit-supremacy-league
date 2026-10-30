/** Display only cloud-produced score snapshots. No inference or simulation. */
export function renderRankingHistory(state) {
 const chart=document.getElementById('rankingChart'),legend=document.getElementById('rankingLegend'),detail=document.getElementById('rankingDetail'),selector=document.getElementById('rankingMetric');
 const entries=state.ranking_history??[],people=state.players??[],hidden=new Set(),events=document.getElementById('rankingChanges');
 const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const when=t=>t?new Date(t).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false}):'時間未記錄';
 const label=(r,metric)=>metric==='rank'?`第 ${r.rank} 名`:metric==='points'?`${r.points} 分`:`${(r.score_rate*100).toFixed(1)}%`;
 const has=id=>entries.some(e=>e.players.some(r=>r.id===id));
 legend.innerHTML=people.map(p=>`<button type="button" data-player="${escape(p.id)}" aria-pressed="true" ${has(p.id)?'':'disabled'} style="--team:${escape(p.color)}"><i></i>${escape(p.name)}${has(p.id)?'':' · 尚無戰績'}</button>`).join('');
 document.getElementById('rankingHistoryCount').textContent=`${entries.length} 次有效戰績更新`;
 const changes=point=>point.change_summary??'歷史版本資訊待雲端補齊';
 document.getElementById('rankingUpdateCount').textContent=`· ${entries.length} 筆`;
 document.getElementById('rankingLatestUpdate').textContent=entries.length?`最新：${changes(entries.at(-1))}`:'尚無紀錄';
 events.innerHTML=entries.map((point,i)=>`<button type="button" data-index="${i}" aria-pressed="false"><small>第 ${i+1} 次 · ${escape(when(point.recorded_at))}</small><strong>${escape(changes(point))}</strong></button>`).reverse().join('');
 const snapSelect=document.getElementById('snapshotSelect'),snapTable=document.getElementById('snapshotTable'),snapMeta=document.getElementById('snapshotMeta'),snapReplay=document.getElementById('snapshotReplay'),snapPrev=document.getElementById('snapshotPrev'),snapNext=document.getElementById('snapshotNext');
 const pctText=n=>Number.isFinite(n)?`${(n*100).toFixed(1)}%`:'—';
 snapSelect.innerHTML=entries.map((point,i)=>`<option value="${i}">第 ${i+1} 次 · ${escape(when(point.recorded_at))}</option>`).reverse().join('');
 function showSnapshot(index) {
  const point=entries[index];
  if(!point){snapTable.innerHTML='<p class="empty">尚無歷史快照。</p>';snapMeta.innerHTML='';snapReplay.innerHTML='';snapPrev.disabled=snapNext.disabled=true;return;}
  snapSelect.value=String(index);snapPrev.disabled=index===0;snapNext.disabled=index===entries.length-1;
  const name=id=>point.players.find(r=>r.id===id)?.name??people.find(p=>p.id===id)?.name??id;
  snapMeta.innerHTML=`${escape(when(point.recorded_at))} · ${point.total_games??0} 場 · ${point.complete_round_robin?'完整全輪':'暫列／部分配對'} · ${escape(changes(point))} · 快照代碼 <code>${escape(point.key)}</code>`;
  const last=index===entries.length-1;
  snapReplay.innerHTML=last?'<span class="tag green">目前版本 · 重播在上方對戰區</span>':point.replay_available?`<span class="tag green">${point.starred?'★ ':''}完整重播已保存</span> <button type="button" class="button small" data-view="${index}">查看此快照的重播</button>`:'<span class="tag">此快照的重播已清理</span> <small class="muted">最多2個星號快照會永久保留完整重播，其餘只留成績。</small>';
  if(!point.matchups?.length){snapTable.innerHTML='<p class="empty">此快照建立時尚未記錄逐配對勝負，不補造數字。排名與積分仍可在上方走勢與表格查看。</p>';return;}
  snapTable.innerHTML=`<table><thead><tr><th>對戰配對</th><th>勝 / 敗 / 和（左方視角）</th><th>左方勝率</th><th>右方勝率</th><th>場數</th></tr></thead><tbody>${point.matchups.map(m=>`<tr><td>${escape(name(m.a))} <span class="faded">vs</span> ${escape(name(m.b))}</td><td>${m.a_stats?.wins??'—'} / ${m.a_stats?.losses??'—'} / ${m.a_stats?.draws??'—'}</td><td>${pctText(m.a_stats?.win_rate)}</td><td>${pctText(m.b_stats?.win_rate)}</td><td>${m.a_stats?.games??'—'}</td></tr>`).join('')}</tbody></table>`;
 }
 snapReplay.onclick=e=>{const b=e.target.closest('button[data-view]');if(b)document.dispatchEvent(new CustomEvent('view-snapshot',{detail:entries[Number(b.dataset.view)]}));};
 snapSelect.onchange=()=>showSnapshot(Number(snapSelect.value));
 snapPrev.onclick=()=>showSnapshot(Number(snapSelect.value)-1);
 snapNext.onclick=()=>showSnapshot(Number(snapSelect.value)+1);
 function show(point,row) {
  detail.innerHTML=`<strong>${escape(changes(point))}</strong><span>${escape(row.name)} · ${escape(label(row,selector.value))} · ${escape(when(point.recorded_at))} · ${row.wins}勝 ${row.losses}敗 ${row.draws}和 / ${row.games}場 · ${point.complete_round_robin?'完整全輪':'暫列／部分配對'}</span>${point.model_updates?.length?`<details class="version-details"><summary>查看本次 ${point.model_updates.length} 位換版者的前後 SHA</summary>${point.model_updates.map(p=>`<div class="version-change"><b>${escape(p.name)} 換版</b><small>原版本 SHA <code>${escape(p.old_sha256)}</code></small><small>新版本 SHA <code>${escape(p.new_sha256)}</code></small></div>`).join('')}</details>`:''}<small>開局輪 ${escape(point.seed_round?.id??'歷史輪次未記錄')} · 所選選手模型 ${escape((row.sha256??'').slice(0,12))} · 當時已完成 ${point.total_games} 場；同一節點列出所有換版者，其他人的曲線也可能受影響。</small>`;
  for(const button of events.querySelectorAll('button'))button.setAttribute('aria-pressed',String(entries[Number(button.dataset.index)]===point));
  showSnapshot(entries.indexOf(point));
 }
 events.onclick=e=>{const button=e.target.closest('button[data-index]');if(!button)return;const point=entries[Number(button.dataset.index)],row=point.players.find(r=>!hidden.has(r.id))??point.players[0];if(row)show(point,row);};
 function draw() {
  const metric=selector.value;
  if(!entries.length){showSnapshot(-1);chart.innerHTML='<p class="empty">尚無真實戰績。首輪完成後，將自動留下第一筆歷史。</p>';detail.textContent='歷史只記錄真實已完成結果，不補造過去曲線。';return;}
  const W=1000,H=340,L=62,R=35,T=25,B=60,width=W-L-R,height=H-T-B;
  const vals=entries.flatMap(e=>e.players.map(r=>r.points??0)),max=metric==='rank'?Math.max(people.length,2):metric==='points'?Math.max(10,Math.ceil(Math.max(...vals)/10)*10):100;
  const value=r=>metric==='rank'?r.rank:metric==='points'?r.points:r.score_rate*100;
  const x=i=>L+(entries.length===1?width/2:i/(entries.length-1)*width),y=v=>T+(metric==='rank'?(v-1)/(max-1):1-v/max)*height;
  const ticks=metric==='rank'?Array.from({length:max},(_,i)=>i+1):Array.from({length:5},(_,i)=>max*i/4);
  let html=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${metric==='rank'?'排名':metric==='points'?'總積分':'每場積分率'}歷史走勢，詳細數值可由下方表格與CSV讀取"><g class="chart-grid">`;
  for(const tick of ticks)html+=`<line x1="${L}" y1="${y(tick)}" x2="${W-R}" y2="${y(tick)}"/><text x="${L-14}" y="${y(tick)+4}" text-anchor="end">${metric==='rank'?'#'+tick:Math.round(tick)+(metric==='score_rate'?'%':'')}</text>`;
  html+='</g>';
  for(let i=0;i<entries.length;i++)if(i===0||i===entries.length-1||i%Math.max(1,Math.ceil(entries.length/5))===0){const t=entries[i].recorded_at,d=t?new Date(t):null;html+=`<text class="chart-date" x="${x(i)}" y="${H-30}" text-anchor="middle">${d?escape(d.toLocaleDateString('zh-TW',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit'})):'未記錄'} · ${i+1}</text>`;}
  for(const p of people){if(hidden.has(p.id))continue;let segment=[];const flush=()=>{if(segment.length>1)html+=`<polyline points="${segment.join(' ')}" fill="none" stroke="${escape(p.color)}" stroke-width="3" vector-effect="non-scaling-stroke"/>`;segment=[];};
   entries.forEach((point,i)=>{const row=point.players.find(r=>r.id===p.id);if(!row){flush();return;}segment.push(`${x(i)},${y(value(row))}`);});flush();
   entries.forEach((point,i)=>{const row=point.players.find(r=>r.id===p.id);if(!row)return;html+=`<circle data-index="${i}" data-player="${escape(p.id)}" tabindex="0" role="button" aria-label="${escape(p.name+' '+when(point.recorded_at)+' '+label(row,metric)+' '+changes(point))}" cx="${x(i)}" cy="${y(value(row))}" r="6" fill="${escape(p.color)}" stroke="#0c1119" stroke-width="2"><title>${escape(p.name+' · '+when(point.recorded_at)+' · '+label(row,metric)+' · '+changes(point))}</title></circle>`;});
  }
  html+='</svg>';chart.innerHTML=html;
  const latest=entries.at(-1),row=latest.players.find(r=>!hidden.has(r.id));if(row)show(latest,row);else detail.textContent='點選上方選手，即可重新顯示走勢。';
  for(const dot of chart.querySelectorAll('circle')){const select=()=>{const point=entries[Number(dot.dataset.index)],row=point.players.find(r=>r.id===dot.dataset.player);show(point,row);};dot.onmouseenter=select;dot.onfocus=select;dot.onclick=select;dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};}
 }
 legend.onclick=e=>{const b=e.target.closest('button[data-player]');if(!b||b.disabled)return;const id=b.dataset.player;hidden.has(id)?hidden.delete(id):hidden.add(id);b.setAttribute('aria-pressed',String(!hidden.has(id)));draw();};
 selector.onchange=draw;draw();
 document.getElementById('rankingHistoryTable').innerHTML=`<table><thead><tr><th>更新／時間</th><th>本次異動（全體）</th><th>選手</th><th>排名</th><th>積分率</th><th>積分／場數</th><th>模型</th><th>範圍</th></tr></thead><tbody>${entries.flatMap((point,i)=>point.players.map(row=>`<tr><td>${i+1} · ${escape(when(point.recorded_at))}</td><td>${escape(changes(point))}</td><td>${escape(row.name)}</td><td>#${row.rank}</td><td>${(row.score_rate*100).toFixed(1)}%</td><td>${row.points} / ${row.games}</td><td><code>${escape((row.sha256??'').slice(0,12))}</code></td><td>${point.complete_round_robin?'完整全輪':'暫列'}</td></tr>`)).reverse().join('')}</tbody></table>`;
}
