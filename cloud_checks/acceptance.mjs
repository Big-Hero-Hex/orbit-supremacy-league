import {chromium} from 'playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const url='https://jasonliaojcs.github.io/orbit-supremacy-league/';
const state=await (await fetch(url+'data/latest.json?acceptance='+Date.now())).json();
assert.ok(state.total_games>=100,'Requires genuine finished matches, not fixtures');
const pair=state.pairs.find(p=>p.a==='liao'&&p.b==='yang');assert.ok(pair);assert.equal(pair.games.length,100);
mkdirSync('runtime/real-acceptance',{recursive:true});
const browser=await chromium.launch();const errors=[];
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(url,{waitUntil:'networkidle'});await page.waitForFunction(()=>document.querySelectorAll('.leader-row').length>=2);
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
 await page.click('#mp4Button');await page.waitForFunction(()=>document.getElementById('mp4').readyState>=2&&document.getElementById('mp4').currentTime>0,{timeout:30000});
 await page.locator('.stage').screenshot({path:'runtime/real-acceptance/official-mp4.png'});
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:'runtime/real-acceptance/mobile-real.png',fullPage:true});assert.deepEqual(errors,[]);
 writeFileSync('runtime/real-acceptance/results.json',JSON.stringify({passed:true,synthetic_data:false,total_real_games:state.total_games,pair:pair.key,ours:{wins:pair.stats.liao.wins,losses:pair.stats.liao.losses,draws:pair.stats.liao.draws},all100_replays:true,seat_filters_50_each:true,canvas_playback:true,official_mp4_playback:true,desktop_mobile_no_overflow:true,errors},null,2));
}finally{await browser.close();}
