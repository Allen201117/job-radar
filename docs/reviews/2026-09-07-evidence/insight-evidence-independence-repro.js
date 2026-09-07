// Read-only boundary test: two domains can carry the same original observation.
// This tests the domain-count gate, not the complete generation/publication chain.
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const { loadTs } = require(path.join(root, 'tests/_load-ts.js'));
const { countDistinctPublishers, passesClaimGate } = loadTs(
  path.join(root, 'lib/insight-verification.ts'),
);
const sources = ['https://example.com/repost', 'https://example.org/repost'].map(url => ({
  url,
  source_kind: 'community_deidentified',
  deidentified: true,
  excerpt: '同一份原始说法，被两个网站转载。',
}));
assert.equal(sources[0].excerpt, sources[1].excerpt);
assert.equal(countDistinctPublishers(sources), 2);
assert.equal(passesClaimGate({ time_window: '2026 年' }, sources), true);
console.log('REPRODUCED: two domains pass the claim gate without proving two independent observations.');
