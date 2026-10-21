import assert from 'node:assert/strict';
import {seedRoundText} from '../site/seed-round.js';
const round={id:'daily-20261022',next_rotation_at:'2026-10-22T20:00:00Z'};
assert.equal(seedRoundText(round,Date.parse('2026-10-22T19:00:00Z')).remaining,'換輪倒數 01:00:00');
assert.ok(seedRoundText(round,Date.parse('2026-10-22T20:00:01Z')).remaining.includes('等待雲端'));
assert.ok(seedRoundText(round).next.includes('04:00:00'));
assert.equal(seedRoundText({...round,id:'legacy-s01'}).name,'原固定開局輪');
assert.ok(seedRoundText(null).next.includes('待雲端'));
console.log('Shared-round display: Taipei boundary, countdown, delayed publication, legacy fallback passed');
