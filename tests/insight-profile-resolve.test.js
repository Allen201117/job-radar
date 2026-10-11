// 「公司名 → 公司画像」：建画像之前先认别名。
//
// 2026-10-11 全库对拍：136 家公司各有 2~5 个画像，根因是每个建画像的入口只按正名去重。
// 这里钉三件事：① 网站侧的归属与爬虫侧（bu_extract）逐条一致；② 建画像的公共入口先找后建；
// ③ app/ lib/ 里除了公共入口，没有第二处直接往 company_profiles 里 upsert。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const ROOT = path.resolve(__dirname, "..");
const resolveMod = loadTs(path.join(ROOT, "lib", "insight-profile-resolve.ts"));
const storeMod = loadTs(path.join(ROOT, "lib", "insight-profile-store.ts"));
const FIXTURE = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "profile-resolve-cases.json"), "utf8"),
);

test("归属与爬虫侧同一份夹具逐条一致", () => {
  const index = resolveMod.buildProfileNameIndex(FIXTURE.profiles);
  for (const c of FIXTURE.cases) {
    const got = resolveMod.resolveProfileByName(index, c.name);
    assert.equal(got ? got.id : null, c.expect, `${JSON.stringify(c.name)}：${c.why}`);
  }
});

// 只支持公共入口用到的那几个调用形态；别的形态直接抛，免得测试悄悄走了别的路。
function fakeService(profiles) {
  const calls = [];
  return {
    calls,
    from(table) {
      assert.equal(table, "company_profiles");
      const q = { _op: null };
      return {
        select() {
          if (q._op === "upsert") return this;
          q._op = "select";
          return this;
        },
        order() {
          return this;
        },
        range(from, to) {
          return Promise.resolve({ data: profiles.slice(from, to + 1), error: null });
        },
        update(patch) {
          q._op = "update";
          q.patch = patch;
          return this;
        },
        eq(col, value) {
          calls.push(["update", col, value, q.patch]);
          return Promise.resolve({ error: null });
        },
        upsert(row, opts) {
          q._op = "upsert";
          calls.push(["upsert", row, opts]);
          return this;
        },
        single() {
          const row = calls.find((c) => c[0] === "upsert")[1];
          return Promise.resolve({ data: { id: "new-id", company: row.company }, error: null });
        },
      };
    },
  };
}

const PROFILES = [
  { id: "p1", company: "知乎", aliases: ["知乎 Zhihu"] },
  { id: "p2", company: "腾讯音乐", aliases: ["腾讯音乐 TME"] },
];

test("名字是已有画像的别名：返回那个画像，不新建", async () => {
  const service = fakeService(PROFILES);
  const got = await storeMod.ensureCompanyProfile(service, "知乎 Zhihu");
  assert.deepEqual(got, { id: "p1", company: "知乎", created: false });
  assert.deepEqual(service.calls, []);
});

test("名字是已有画像的别名且带 patch：按 id 更新那个画像，不新建", async () => {
  const service = fakeService(PROFILES);
  const got = await storeMod.ensureCompanyProfile(service, "腾讯音乐 TME", { insight_checked_at: null });
  assert.equal(got.id, "p2");
  assert.deepEqual(service.calls, [["update", "id", "p2", { insight_checked_at: null }]]);
});

test("哪个画像都不认这个名字：才新建", async () => {
  const service = fakeService(PROFILES);
  const got = await storeMod.ensureCompanyProfile(service, " 新公司 ", { industry: "互联网" });
  assert.deepEqual(got, { id: "new-id", company: "新公司", created: true });
  assert.deepEqual(service.calls, [
    ["upsert", { company: "新公司", industry: "互联网" }, { onConflict: "company" }],
  ]);
});

test("画像表超过一页时也读全（第二页上的别名照样认）", async () => {
  const many = Array.from({ length: 1000 }, (_, i) => ({
    id: `a${String(i).padStart(4, "0")}`,
    company: `占位公司${i}`,
    aliases: [],
  }));
  many.push({ id: "z1", company: "云尖信息", aliases: ["云尖信息 校招"] });
  const service = fakeService(many);
  const got = await storeMod.ensureCompanyProfile(service, "云尖信息 校招");
  assert.equal(got.id, "z1");
  assert.deepEqual(service.calls, []);
});

test("空名字直接报错，不建空画像", async () => {
  await assert.rejects(() => storeMod.ensureCompanyProfile(fakeService([]), "  "), /company_required/);
});

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

test("app/ lib/ 里只有公共入口直接往 company_profiles 里写新行", () => {
  const allowed = new Set(["lib/insight-profile-store.ts"]);
  const offenders = [];
  for (const file of [...walk(path.join(ROOT, "app")), ...walk(path.join(ROOT, "lib"))]) {
    const rel = path.relative(ROOT, file).replace(/\\/g, "/");
    const src = fs.readFileSync(file, "utf8");
    if (/from\(\s*["']company_profiles["']\s*\)\s*\.(?:upsert|insert)\(/.test(src) && !allowed.has(rel)) offenders.push(rel);
  }
  assert.deepEqual(offenders, [], "建公司画像请走 lib/insight-profile-store 的 ensureCompanyProfile（先按正名 + 别名找，没有才建）");
});

test("抽屉现查的占位用的是画像规范名，不是查询词原文", () => {
  const src = fs.readFileSync(path.join(ROOT, "app/api/insights/route.ts"), "utf8");
  assert.match(src, /const enrichCompany = profileLight\?\.company \?\? company;/);
  assert.match(src, /maybeDispatchInsightEnrich\(\{[^}]*company: enrichCompany/);
});
