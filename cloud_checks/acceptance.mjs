import {chromium} from 'playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const url='https://jasonliaojcs.github.io/orbit-supremacy-league/';
const state=await (await fetch(url+'data/latest.json?acceptance='+Date.now())).json();
assert.ok(state.total_games>=100,'Requires genuine finished matches, not fixtures');
const pair=state.pairs.find(p=>p.a==='liao'&&p.b==='yang');assert.ok(pair);assert.equal(pair.games.length,100);
mkdirSync('runtime/real-acceptance',{recursive:true});
// Production H.264 MP4 needs the media codecs shipped with Google Chrome;
// Playwright's stripped Chromium headless shell may not ship those codecs.
const browser=await chromium.launch({channel:'chrome'});const errors=[];
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(url,{waitUntil:'networkidle'});await page.waitForFunction(()=>document.querySelectorAll('.leader-row').length>=2);
 await page.waitForFunction(()=>document.querySelectorAll('#rankingChart circle').length>=2);
 assert.equal(state.ranking_history.length,1,'Initial genuine history must not invent old snapshots');
 await page.selectOption('#rankingMetric','rank');assert.equal(await page.locator('#rankingChart circle').count(),2);
 await page.selectOption('#rankingMetric','score_rate');
 await page.locator('#ranking-history').screenshot({path:'runtime/real-acceptance/ranking-real.png'});
 const csv=await (await fetch(url+'data/ranking_history.csv?verify='+Date.now())).text();assert.ok(csv.includes('model_sha256'));assert.ok(csv.includes('廖格致'));
 await page.locator(`[data-pair="${pair.key}"]`).first().click();
 await page.waitForFunction(()=>document.getElementById('screenEmpty').hidden===true);
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
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:'runtime/real-acceptance/mobile-real.png',fullPage:true});assert.deepEqual(errors,[]);
 writeFileSync('runtime/real-acceptance/results.json',JSON.stringify({passed:true,synthetic_data:false,total_real_games:state.total_games,pair:pair.key,ours:{wins:pair.stats.liao.wins,losses:pair.stats.liao.losses,draws:pair.stats.liao.draws},all100_replays:true,seat_filters_50_each:true,canvas_playback:true,official_mp4_playback:true,desktop_mobile_no_overflow:true,errors},null,2));
}finally{await browser.close();}
