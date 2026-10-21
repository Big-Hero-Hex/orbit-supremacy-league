/** Display cloud-drawn seeds and timing only. Never draw seeds or run games. */
export function seedRoundText(round, now=Date.now()) {
 if(!round)return {name:'共同 50 seed · 雙座位',next:'輪換資訊待雲端發布',remaining:''};
 const due=new Date(round.next_rotation_at).getTime(),seconds=Math.max(0,Math.ceil((due-now)/1000));
 const hh=Math.floor(seconds/3600),mm=Math.floor(seconds%3600/60),ss=seconds%60;
 return {name:round.id==='legacy-s01'?'原固定開局輪':`共同開局輪 ${round.id.replace('daily-','')}`,
  next:`下輪 ${new Date(due).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}（台灣）`,
  remaining:due<=now?'輪換時間已到 · 等待雲端完成新輪':`換輪倒數 ${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}`};
}
export function renderSeedRound(round) {
 const text=seedRoundText(round);
 for(const [id,key] of [['seedRoundName','name'],['seedRoundNext','next'],['seedRoundCountdown','remaining']]){
  const element=document.getElementById(id);if(element)element.textContent=text[key];
 }
}
