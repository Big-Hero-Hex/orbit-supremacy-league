import {chromium} from 'playwright';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {gzipSync} from 'node:zlib';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {resolve,extname} from 'node:path';
const fixture=JSON.parse(readFileSync('runtime/ui-fixture.json','utf8'));
const liveState=await (await fetch('https://jasonliaojcs.github.io/orbit-supremacy-league/data/latest.json')).json();
// Preview the checked-out release on the cloud runner: ranked games may still
// be publishing, so a test must not accidentally exercise the preceding JS.
const root=resolve('site');
const server=createServer((request,response)=>{
 try{
  const path=decodeURIComponent(new URL(request.url,'http://localhost').pathname);
  if(path==='/data/latest.json'){response.setHeader('Content-Type','application/json');response.end(JSON.stringify(liveState));return;}
  const file=resolve(root,'.'+(path==='/'?'/index.html':path));if(!file.startsWith(root+'/'))throw Error('path');
  const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'};
  response.setHeader('Content-Type',mime[extname(file)]??'application/octet-stream');response.end(readFileSync(file));
 }catch{response.statusCode=404;response.end('missing');}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const preview=`http://127.0.0.1:${server.address().port}/`;
mkdirSync('runtime/ui-check',{recursive:true});
const browser=await chromium.launch();
const errors=[];const results=[];
try{
 const real=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
 real.on('pageerror',e=>errors.push(String(e)));
 await real.goto('https://jasonliaojcs.github.io/orbit-supremacy-league/',{waitUntil:'networkidle'});
 await real.locator('.roster-card').first().waitFor();
 assert.equal(await real.locator('.roster-card').count(),liveState.players.length);
 assert.equal(await real.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await real.screenshot({path:'runtime/ui-check/desktop.png',fullPage:true});results.push('Production page: published roster count, no horizontal overflow');
 await real.setViewportSize({width:390,height:844});
 await real.screenshot({path:'runtime/ui-check/mobile.png',fullPage:true});
 assert.equal(await real.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);results.push('Mobile 390px: no horizontal overflow');
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/data/latest.json',route=>route.fulfill({json:fixture.state}));
 await page.route('**/replays/*.json.gz',route=>route.fulfill({contentType:'application/gzip',body:gzipSync(JSON.stringify(fixture.record))}));
 await page.goto(preview,{waitUntil:'networkidle'});
 await page.waitForFunction(()=>document.querySelectorAll('.leader-row').length===6);
 await page.waitForFunction(()=>document.querySelectorAll('#rankingChart circle').length===18);
 await page.selectOption('#rankingMetric','rank');assert.ok((await page.locator('#rankingChart').textContent()).includes('#1'));
 await page.locator('#rankingLegend button').first().click();assert.equal(await page.locator('#rankingChart circle').count(),15);
 await page.locator('#rankingLegend button').first().click();assert.equal(await page.locator('#rankingChart circle').count(),18);
 await page.locator('#rankingChart circle').first().focus();assert.ok((await page.locator('#rankingDetail').textContent()).includes('2026'));
 await page.selectOption('#rankingMetric','points');assert.equal(await page.locator('#rankingHistoryTable tbody tr').count(),18);
 await page.locator('#ranking-history').screenshot({path:'runtime/ui-check/ranking-fixture-only.png'});
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.locator('#ranking-history').screenshot({path:'runtime/ui-check/ranking-mobile-fixture-only.png'});await page.setViewportSize({width:1440,height:1000});
 results.push('Synthetic UI history only: 3 snapshots /6participants, rank/points selector, legend toggles, keyboard detail, 18 table rows, mobile no overflow');
 assert.equal(await page.locator('.matrix-cell').count(),30);assert.equal(await page.locator('.pair-tab').count(),15);
 assert.equal(await page.locator('#playerCount').textContent(),'06');assert.equal(await page.locator('#pairCount').textContent(),'15');
 assert.equal(await page.locator('#gameList .game-row').count(),20);await page.selectOption('#seatFilter','ship1');assert.equal(await page.locator('.game-row').count(),10);
 await page.selectOption('#seatFilter','');await page.selectOption('#watchSet','all');
 assert.equal(await page.locator('.roster-card a[href*="undefined"]').count(),0);
 const teachers=page.locator('.roster-card').filter({hasText:'老師原版'});assert.equal(await teachers.count(),2);assert.equal(await teachers.locator('a').count(),0);
 await page.waitForFunction(()=>document.getElementById('screenEmpty').hidden===true);
 await page.selectOption('#seatFilter','ship1');assert.equal(await page.locator('.game-row').count(),50);
 await page.selectOption('#seatFilter','');await page.fill('#seedFilter',String(fixture.state.pairs[0].games[0].seed));assert.equal(await page.locator('.game-row').count(),2);
 await page.fill('#seedFilter','');await page.click('#play');await page.waitForTimeout(550);await page.click('#play');
 assert.ok(Number(await page.locator('#seek').inputValue())>0);
 await page.locator('.event-chip').first().click();await page.selectOption('#statsScope','pair');
 assert.equal(await page.locator('#detailedStats th').count(),3);
 await page.locator('.pair-tab').nth(2).click();await page.waitForFunction(()=>document.getElementById('screenEmpty').hidden===true);
 await page.screenshot({path:'runtime/ui-check/ui-fixture-only.png',fullPage:true});
 results.push('UI fixtures only: 15 pairs,30 matrix cells,20-game guide/10 each seat, all100 option, teachers have no upload link, seed/playback/event/pair statistics');
 // Exercise real rendered failure/recovery text with explicitly mocked status,
 // without running a game or changing the real published scores.
 let pulseReads=0;const pulse=await browser.newPage({viewport:{width:1440,height:1000}});pulse.on('pageerror',e=>errors.push(String(e)));
 await pulse.route('**/api.github.com/repos/*/orbit-supremacy-league/actions/runs?*',route=>{
  pulseReads++;const now=Date.now();return route.fulfill({json:{workflow_runs:[{id:'ui-test-only',path:'.github/workflows/league.yml',status:'completed',conclusion:'success',updated_at:new Date(now-(pulseReads===1?3600000:10000)).toISOString()},{path:'.github/workflows/poll-clock.yml',status:'waiting',created_at:new Date(now-(pulseReads===1?3600000:10000)).toISOString()}]}});
 });
 await pulse.goto(preview,{waitUntil:'networkidle'});
 await pulse.waitForFunction(()=>document.getElementById('cloudState').textContent.includes('逾時'));
 assert.equal(await pulse.locator('#pollWarning').isVisible(),true);await pulse.locator('.broadcast-status').screenshot({path:'runtime/ui-check/stale-status-fixture-only.png'});
 await pulse.click('#refresh');await pulse.waitForFunction(()=>document.getElementById('cloudState').textContent.includes('模型無變更'));
 assert.equal(pulseReads,2,'manual refresh must bypass five-minute API cache');assert.equal(await pulse.locator('#pollWarning').isVisible(),false);
 await pulse.locator('.broadcast-status').screenshot({path:'runtime/ui-check/recovered-status-fixture-only.png'});
 results.push('Mocked cloud status: stale warning visible, manual refresh refetches API immediately, healthy unchanged recovery hides warning');
 assert.deepEqual(errors,[]);writeFileSync('runtime/ui-check/results.json',JSON.stringify({passed:true,results,errors,fixture_scores_are_not_real_results:true},null,2));console.log(results.join('\n'));
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
