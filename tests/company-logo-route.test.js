const { test } = require("node:test");
const assert = require("node:assert");
const { loadRoute } = require("./route-test-utils");

function loadLogoRoute(rows) {
  const seen = { keys: [] };
  const supabase = {
    from(table) {
      assert.equal(table, "company_logos");
      return {
        select() {
          return this;
        },
        in(column, keys) {
          assert.equal(column, "company_key");
          seen.keys = keys;
          return Promise.resolve({
            data: rows.filter((row) => keys.includes(row.company_key)),
            error: null,
          });
        },
      };
    },
  };
  const { GET } = loadRoute("app/api/company-logos/route.ts", {
    "@/lib/auth": { createServerSupabase: async () => supabase },
    "@/lib/auth-claims": { verifyRequestClaims: async () => ({ id: "user-1" }) },
  });
  return { GET, seen };
}

async function getLogos(GET, companies) {
  const response = await GET({
    nextUrl: new URL(`https://example.test/api/company-logos?companies=${encodeURIComponent(companies)}`),
  });
  return response.json();
}

test("company logo route keeps ordinary company lookup unchanged", async () => {
  const { GET, seen } = loadLogoRoute([
    { company_key: "腾讯", logo_data: "data:full", status: "found" },
  ]);

  const body = await getLogos(GET, "腾讯");

  assert.deepEqual(seen.keys, ["腾讯"]);
  assert.deepEqual(body.logos["腾讯"], { data: "data:full", status: "found" });
});

test("company logo route prefers an exact full-name logo over its brand fallback", async () => {
  const company = "国网江苏省电力有限公司（国家电网）";
  const { GET, seen } = loadLogoRoute([
    { company_key: company, logo_data: "data:full", status: "found" },
    { company_key: "国家电网", logo_data: "data:brand", status: "found" },
  ]);

  const body = await getLogos(GET, company);

  assert.deepEqual(seen.keys, [company, "国家电网"]);
  assert.deepEqual(body.logos[company], { data: "data:full", status: "found" });
});

test("company logo route falls back to the bracketed group brand when full name misses", async () => {
  const company = "国网江苏省电力有限公司（国家电网）";
  const { GET } = loadLogoRoute([
    { company_key: "国家电网", logo_data: "data:brand", status: "found" },
  ]);

  const body = await getLogos(GET, company);

  assert.deepEqual(body.logos[company], { data: "data:brand", status: "found" });
});

test("company logo route also accepts an ASCII parenthesized group brand", async () => {
  const company = "国网江苏省电力有限公司(国家电网)";
  const { GET } = loadLogoRoute([
    { company_key: "国家电网", logo_data: "data:brand", status: "found" },
  ]);

  const body = await getLogos(GET, company);

  assert.deepEqual(body.logos[company], { data: "data:brand", status: "found" });
});

test("company logo route does not treat a terminal city qualifier as a group brand", async () => {
  const company = "某某公司(北京)";
  const { GET, seen } = loadLogoRoute([
    { company_key: "北京", logo_data: "data:wrong", status: "found" },
  ]);

  const body = await getLogos(GET, company);

  assert.deepEqual(seen.keys, [company]);
  assert.deepEqual(body.logos[company], { data: null, status: "not_found" });
});
