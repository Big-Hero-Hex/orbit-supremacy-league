/** Pure status derivation. A predicted tick is never reported as a real check. */
export function cloudPulse(data, meta, now=Date.now()) {
 const runs=meta?.runs??[],isLeague=r=>r.path?.split('@')[0].endsWith('/league.yml')||r.name==='OSL · 雲端賽事中心',isClock=r=>r.path?.split('@')[0].endsWith('/poll-clock.yml')||r.name==='OSL · 五分鐘雲端時鐘';
 const league=runs.filter(isLeague),last=league.find(r=>r.status==='completed'&&r.conclusion==='success'),latest=league[0];
 const active=league.some(r=>['in_progress','queued','waiting','pending'].includes(r.status));
 const clocks=runs.filter(isClock),clock=clocks.find(r=>r.status==='waiting')??clocks.find(r=>['in_progress','queued','pending'].includes(r.status));
 const checked=last?.updated_at??data.checked_at,age=now-Date.parse(checked),due=clock?Date.parse(clock.run_started_at??clock.created_at)+300000:Date.parse(checked)+300000;
 const unavailable=(data.players??[]).filter(p=>p.status!=='ready'),failures=data.failures??[];
 const common={checked,due,hasClock:!!clock,noChange:!unavailable.length&&!failures.length&&!!last&&String(last.id)!==String(data.cloud_run)};
 if(meta?.unavailable)return {...common,status:'unverified',message:'無法確認雲端排程狀態，請查看雲端賽程；目前顯示的是最後已發布成績。'};
 if(active)return {...common,status:'checking',message:''};
 if(latest?.status==='completed'&&['failure','timed_out','action_required'].includes(latest.conclusion))return {...common,status:'failed',message:'最近一輪雲端檢查失敗。既有成績已保留；下一輪會再次檢查，換版配對不會被直接判輸。'};
 // Status is cached for five minutes; allow that cache window before declaring
 // a waiting clock late, otherwise a healthy completed tick looks stalled.
 if(age>900000||(clock&&now-due>360000))return {...common,status:'delayed',message:'雲端檢查已逾時，這不是「已檢查但沒變更」。請查看最後成功時間與雲端賽程；倒數不代表檢查已執行。'};
 if(unavailable.length||failures.length)return {...common,status:'blocked',message:[...unavailable.map(p=>`${p.name??p.id}：${p.message??p.status}`),...failures.map(f=>`${f.a} vs ${f.b}：${f.message}`)].join('；')};
 return {...common,status:'idle',message:''};
}
