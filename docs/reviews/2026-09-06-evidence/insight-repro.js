// Read-only counterexample: use actual derivation code with synthetic public jobs.
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const { loadTs } = require(path.join(root, 'tests/_load-ts.js'));
const { deriveHiring } = loadTs(path.join(root, 'lib/insight-derive.ts'));
const now = '2026-09-06T00:00:00.000Z';
function cohort(n, firstSeen, label) {
  return Array.from({ length: n }, (_, i) => ({
    id: `${label}-${i}`, company: '示例公司', title: '软件工程师',
    location: '上海', job_type: '社招', status: 'active',
    first_seen_at: firstSeen, last_seen_at: now,
    jd_url: `https://example.com/jobs/${label}-${i}`,
    summary: null, experience: null, education: null,
  }));
}
const prior = cohort(30, '2026-07-25T00:00:00Z', 'prior');
const recent = cohort(30, '2026-08-25T00:00:00Z', 'recent');
const derive = jobs => deriveHiring(jobs, now, { headcountBand: '1000-5000' });
const before = derive([...prior, ...recent]);
const after = derive([...prior.slice(0, 3), ...recent]);
const noBaseline = derive(recent);
assert.equal(before.payload.trend, 0);
assert.equal(after.payload.trend, 900);
assert.match(after.content, /HC 较充足/);
assert.equal(noBaseline.payload.trend, null);
assert.match(noBaseline.content, /招聘平稳/);
for (const [name, item] of Object.entries({ before, after, noBaseline })) {
  console.log(name, JSON.stringify({ trend: item.payload.trend, content: item.content }));
}
console.log('PASS: unchanged publication cohorts become +900% after older jobs close; missing baseline becomes steady.');
