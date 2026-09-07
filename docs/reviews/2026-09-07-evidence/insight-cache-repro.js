// Isolated real-function counterexample; fetch is replaced with an in-memory server.
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const { loadTs } = require(path.join(root, 'tests/_load-ts.js'));
const { fetchCompanyInsights } = loadTs(path.join(root, 'lib/insight-client.ts'));

async function main() {
  const originalFetch = global.fetch;
  let calls = 0;
  let retired = false;
  global.fetch = async () => {
    calls++;
    return { json: async () => ({ ok: true, dimensions: { culture: retired ? [] : [{ id: 'later-retired' }] } }) };
  };
  try {
    const first = await fetchCompanyInsights('示例公司');
    retired = true; // The simulated server now excludes the withdrawn item.
    const reopened = await fetchCompanyInsights('示例公司');
    assert.equal(calls, 1);
    assert.equal(reopened, first);
    assert.equal(reopened.dimensions.culture[0].id, 'later-retired');
    console.log('REPRODUCED: reopening the drawer returns a cached withdrawn item without another request.');
  } finally {
    global.fetch = originalFetch;
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
