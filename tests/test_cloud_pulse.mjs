import assert from 'node:assert/strict';
import {cloudPulse} from '../site/cloud-pulse.js';
const now=Date.parse('2026-10-20T15:30:00Z'),data={checked_at:'2026-10-20T14:00:00Z',cloud_run:'1'};
for(const initial of [null,undefined]){
 const pending=cloudPulse(data,initial,now);
 assert.equal(pending.status,'loading','old published results do not prove an outage before the status API responds');
 assert.equal(pending.due,null,'no invented countdown before the scheduler is known');
 assert.equal(pending.message,'');
}
assert.equal(cloudPulse(data,{runs:[]},now).status,'delayed');
const good={id:2,path:'.github/workflows/league.yml',status:'completed',conclusion:'success',updated_at:'2026-10-20T15:29:30Z'};
const clock={path:'.github/workflows/poll-clock.yml',status:'waiting',created_at:'2026-10-20T15:28:00Z'};
let p=cloudPulse(data,{runs:[good,clock]},now);assert.equal(p.status,'idle');assert.equal(p.due,Date.parse('2026-10-20T15:33:00Z'));assert.equal(p.noChange,true);
assert.equal(cloudPulse(data,{runs:[{...good,status:'in_progress'},clock]},now).status,'checking');
assert.equal(cloudPulse(data,{runs:[{...good,conclusion:'failure'},clock]},now).status,'failed');
assert.equal(cloudPulse(data,{runs:[good,{...clock,created_at:'2026-10-20T15:10:00Z'}]},now).status,'delayed');
assert.equal(cloudPulse(data,{unavailable:true,runs:[good]},now).status,'unverified');
assert.equal(cloudPulse({...data,cloud_run:'2'},{runs:[good,clock]},now).noChange,false);
assert.equal(cloudPulse(data,{runs:[good,{...clock,created_at:'2026-10-20T15:21:00Z'}]},now).status,'idle','five-minute cached status must not falsely report an outage');
console.log('8 cloud pulse checks passed: stale ≠ nochange, server clock, active, failed, delayed, API unavailable, published, cache grace');
const blocked=cloudPulse({...data,players:[{id:'lee',name:'李',status:'invalid',message:'缺少 policy.pth'}]},{runs:[good,clock]},now);
assert.equal(blocked.status,'blocked');assert.equal(blocked.noChange,false);assert.match(blocked.message,/policy.pth/);
assert.equal(cloudPulse({...data,failures:[{a:'a',b:'b',message:'載入失敗，30分鐘後重試'}]},{runs:[good,clock]},now).status,'blocked');
const futureGood={...good,updated_at:'2026-10-20T16:29:30Z'},futureClock={...clock,created_at:'2026-10-20T16:28:00Z'};
for(const runs of [[futureGood,clock],[good,futureClock],[futureGood,futureClock]]){
 const future=cloudPulse({...data,checked_at:'2026-10-20T15:29:00Z'},{runs},now);
 assert.equal(future.status,'clock_unverified');assert.equal(future.due,null);assert.equal(future.hasClock,false);
 assert.ok(Date.parse(future.checked)<=now,'a future API timestamp is not presented as a verified local check time');
}
assert.equal(cloudPulse(data,{runs:[{...futureGood,conclusion:'timed_out'},futureClock]},now).status,'failed','real failures remain visible despite inconsistent timestamps');
assert.equal(cloudPulse(data,{runs:[{...futureGood,status:'in_progress'},futureClock]},now).status,'checking');
assert.equal(cloudPulse({...data,checked_at:futureGood.updated_at},{runs:[futureGood,futureClock]},now).checked,null,'do not present a future publication timestamp as a past successful check');
console.log('Future scheduler timestamps never produce a misleading hour-long five-minute countdown.');
console.log('Invalid uploads/runtime failures remain visible after a successful scheduler check.');
