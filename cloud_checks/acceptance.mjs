import {chromium} from 'playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const url='https://big-hero-hex.github.io/orbit-supremacy-league/';
let state;
// A push also starts Pages deployment; wait for that version rather than testing
// the preceding release and misreporting a missing new feature as a regression.
for(let i=0;i<60;i++){
 state=await (await fetch(url+'data/latest.json?acceptance='+Date.now())).json();
 if(state.ranking_history?.length && state.ranking_history.every(p=>Array.isArray(p.model_updates)))break;
 await new Promise(resolve=>setTimeout(resolve,5000));
}
assert.ok(Array.isArray(state.ranking_history),'Requires ranking-history deployment');
assert.ok(state.total_games>=100,'Requires genuine finished matches, not fixtures');
const pair=state.pairs.find(p=>p.a==='liao'&&p.b==='yang');assert.ok(pair);assert.equal(pair.games.length,100);
mkdirSync('runtime/real-acceptance',{recursive:true});
// Production H.264 MP4 needs the media codecs shipped with Google Chrome;
// Playwright's stripped Chromium headless shell may not ship those codecs.
const browser=await chromium.launch({channel:'chrome'});const errors=[];
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(url,{waitUntil:'networkidle'});
 for(let attempt=0;await page.locator('#rankingUpdates').count()===0 && attempt<40;attempt++){await page.waitForTimeout(5000);await page.reload({waitUntil:'networkidle'});}
 await page.waitForFunction(()=>document.querySelectorAll('.leader-row').length>=2);
 await page.waitForFunction(()=>document.querySelectorAll('#rankingChart circle').length>=2);
 assert.ok(state.ranking_history.length>=1);
 const expectedPoints=state.ranking_history.reduce((n,p)=>n+p.players.length,0);
 await page.selectOption('#rankingMetric','rank');assert.equal(await page.locator('#rankingChart circle').count(),expectedPoints);
 assert.equal(await page.locator('#rankingUpdates').evaluate(e=>e.open),false);
 assert.equal(await page.locator('#rankingChanges button').first().isVisible(),false);
 assert.ok((await page.locator('#rankingLatestUpdate').textContent()).includes(state.ranking_history.at(-1).change_summary));
 await page.locator('#rankingUpdates>summary').click();
 assert.equal(await page.locator('#rankingChanges button').count(),state.ranking_history.length);
 for(let i=0;i<state.ranking_history.length;i++){
  await page.locator(`#rankingChanges button[data-index="${i}"]`).click();
  assert.ok((await page.locator('#rankingDetail').textContent()).includes(state.ranking_history[i].change_summary));
  assert.equal(await page.locator('#rankingDetail .version-change').count(),state.ranking_history[i].model_updates.length);
 }
 await page.locator('#rankingUpdates>summary').click();
 assert.equal(await page.locator('#rankingUpdates').evaluate(e=>e.open),false);
 await page.selectOption('#rankingMetric','score_rate');
 await page.locator('#ranking-history').screenshot({path:'runtime/real-acceptance/ranking-real.png'});
 const csv=await (await fetch(url+'data/ranking_history.csv?verify='+Date.now())).text();assert.ok(csv.includes('model_sha256'));assert.ok(csv.includes('changed_player_names'));assert.ok(csv.includes('model_updates_json'));assert.ok(csv.includes('廖格致'));
 await page.locator(`[data-pair="${pair.key}"]`).first().click();
 await page.waitForFunction(()=>document.getElementById('screenEmpty').hidden===true);
 if(await page.locator('#watchSet').count())await page.selectOption('#watchSet','all');
 assert.equal(await page.locator('.game-row').count(),100);
 assert.equal(await page.locator('#totalGames').textContent(),String(state.total_games));
 await page.selectOption('#seatFilter','ship1');assert.equal(await page.locator('.game-row').count(),50);
 await page.selectOption('#seatFilter','ship2');assert.equal(await page.locator('.game-row').count(),50);
 await page.selectOption('#seatFilter','');
 await page.click('#play');await page.waitForTimeout(500);await page.click('#play');assert.ok(Number(await page.locator('#seek').inputValue())>0);
 await page.screenshot({path:'runtime/real-acceptance/desktop-real.png',fullPage:true});
 await page.locator('.broadcast-layout').screenshot({path:'runtime/real-acceptance/broadcast-real.png'});
 const video=pair.videos[0];await page.locator(`[data-game="${video.game_id}"]`).click();await page.waitForFunction(()=>document.getElementById('screenEmpty').hidden===true);
 await page.click('#mp4Button');
 try{await page.waitForFunction(()=>document.getElementById('mp4').readyState>=2&&document.getElementById('mp4').currentTime>0,null,{timeout:30000});}
 catch(error){writeFileSync('runtime/real-acceptance/media-diagnostic.json',JSON.stringify(await page.locator('#mp4').evaluate(v=>({src:v.currentSrc,readyState:v.readyState,networkState:v.networkState,paused:v.paused,time:v.currentTime,error:v.error?{code:v.error.code,message:v.error.message}:null,h264:v.canPlayType('video/mp4; codecs="avc1.42E01E"')})),null,2));throw error;}
 await page.locator('.stage').screenshot({path:'runtime/real-acceptance/official-mp4.png'});
 const teacherChecks=[];
 if(state.players.some(p=>p.kind==='official_rulebot')){
  assert.equal(state.players.length,6);assert.equal(state.expected_pairs,15);assert.equal(state.expected_games,1500);
  const ready=state.players.filter(p=>p.status==='ready').length;assert.equal(state.pairs.length,ready*(ready-1)/2);assert.equal(state.total_games,state.pairs.length*100);
  for(const p of state.pairs){
   assert.equal(p.games.length,100);assert.equal(new Set(p.games.map(g=>g.seed)).size,50);
   assert.equal(p.games.filter(g=>g.a_seat==='ship1').length,50);assert.equal(p.games.filter(g=>g.a_seat==='ship2').length,50);
   assert.equal(p.viewing_guide.game_ids.length,20);assert.deepEqual(p.viewing_guide.seat_counts,{ship1:10,ship2:10});
   for(const id of [p.a,p.b])if(['rusher','sniper'].includes(id)){assert.equal(p.model_info[id].kind,'official_rulebot');assert.equal(p.model_info[id].parameters,0);}
  }
  assert.equal(await page.locator('.roster-card').count(),6);assert.equal(await page.locator('.roster-card a[href*="undefined"]').count(),0);
  for(const bot of ['rusher','sniper']){
   const p=state.pairs.find(p=>p.a==='liao'&&p.b===bot);assert.ok(p);
   await page.locator(`[data-pair="${p.key}"]`).first().click();await page.selectOption('#watchSet','guide');
   await page.waitForFunction(()=>document.getElementById('screenEmpty').hidden===true);assert.equal(await page.locator('.game-row').count(),20);
   await page.selectOption('#seatFilter','ship1');assert.equal(await page.locator('.game-row').count(),10);await page.selectOption('#seatFilter','');
   await page.click('#play');await page.waitForTimeout(350);await page.click('#play');assert.ok(Number(await page.locator('#seek').inputValue())>0);
   await page.locator('.broadcast-layout').screenshot({path:`runtime/real-acceptance/${bot}-real.png`});
   teacherChecks.push({bot,all100_scores:true,guide20_balanced:true,canvas_playback:true,ours:p.stats.liao});
  }
 }
 await page.setViewportSize({width:390,height:844});
 writeFileSync('runtime/real-acceptance/mobile-width-diagnostic.json',JSON.stringify(await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,wide:[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,id:e.id,class:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width,client:e.clientWidth,scroll:e.scrollWidth})).slice(0,80)})),null,2));
 await page.screenshot({path:'runtime/real-acceptance/mobile-before-check.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:'runtime/real-acceptance/mobile-real.png',fullPage:true});assert.deepEqual(errors,[]);
 writeFileSync('runtime/real-acceptance/results.json',JSON.stringify({passed:true,synthetic_data:false,total_real_games:state.total_games,pair:pair.key,ours:{wins:pair.stats.liao.wins,losses:pair.stats.liao.losses,draws:pair.stats.liao.draws},all100_replays:true,seat_filters_50_each:true,canvas_playback:true,official_mp4_playback:true,teacherChecks,desktop_mobile_no_overflow:true,errors},null,2));
}finally{await browser.close();}
