const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

// 与 tests/insight-verification.test.js 同一套 TS 转译 shim（lib 是 TS，测试是 CJS）。
function loadTsModule(relPath, deps = {}) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const compiled = ts.transpileModule(fs.readFileSync(sourcePath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const localRequire = (spec) => {
    if (deps[spec]) return deps[spec];
    return require(spec);
  };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    module.exports,
    localRequire,
    module,
    sourcePath,
    path.dirname(sourcePath),
  );
  return module.exports;
}

const V = loadTsModule(path.join("lib", "insight-verification.ts"));
// 数据层名单与抽屉共用，住在 insight-bundle 里 —— 这个 shim 得把它一并转译进来。
const B = loadTsModule(path.join("lib", "insight-bundle.ts"), {
  "./insight-verification": V,
  "./types": {},
});
const L = loadTsModule(path.join("lib", "insight-library.ts"), {
  "./insight-bundle": B,
  "./insight-verification": V,
  "./types": {},
});

const NOW = new Date("2026-09-03T00:00:00.000Z");

function subject(over = {}) {
  return {
    id: "s-1",
    company_id: "c-1",
    kind: "business_unit",
    name: "飞书",
    job_count: 397,
    status: "active",
    ...over,
  };
}

function signalItem(over = {}) {
  return {
    id: `i-${Math.random()}`,
    company_id: "c-1",
    subject_id: "s-1",
    dimension: "hiring",
    grade: "fact",
    origin: "derived",
    assertion: "signal",
    title: "飞书",
    content: "近 30 天新挂出并仍在招的岗位 47 个（基于 397 个在招岗）。",
    sample_size: 397,
    payload: { sample_n: 397 },
    metric_key: "hiring_volume_30d",
    metric_value: 47,
    metric_unit: "个",
    scope: {},
    time_window: "截至 2026-09-03 的在招岗位",
    valid_from: null,
    valid_until: null,
    last_verified_at: "2026-09-02T00:00:00.000Z",
    deidentified: true,
    status: "active",
    created_at: "2026-09-02T00:00:00.000Z",
    updated_at: "2026-09-02T00:00:00.000Z",
    sources: [],
    ...over,
  };
}

function source(url, over = {}) {
  return {
    id: url,
    url,
    publisher: "p",
    source_kind: "public_web",
    excerpt: null,
    collected_at: "2026-08-01T00:00:00.000Z",
    deidentified: true,
    created_at: "2026-08-01T00:00:00.000Z",
    ...over,
  };
}

const COMPANIES = new Map([["c-1", { company: "字节跳动", industry: "互联网/科技" }]]);

test("索引计数只算「过了展示门」的条目——卡面数字必须等于点进去看到的条数", () => {
  const items = [
    signalItem(),
    // 无来源的 claim：展示门会挡掉（需时间窗 + ≥2 独立域名），因此不许计入
    signalItem({
      origin: "public_web",
      assertion: "claim",
      grade: "experience",
      content: "据公开讨论，加班较多。",
      metric_key: "overtime_level",
      metric_value: null,
      sources: [],
    }),
  ];
  const index = L.buildLibraryIndex([subject()], items, COMPANIES, NOW);
  assert.equal(index.length, 1);
  assert.equal(index[0].item_count, 1);
  assert.deepEqual(index[0].assertion_counts, { fact: 0, signal: 1, claim: 0 });
});

test("带 ≥2 独立域名与时间窗的 claim 计入 claim 档", () => {
  const claim = signalItem({
    origin: "public_web",
    assertion: "claim",
    grade: "experience",
    content: "据公开讨论，年终奖普遍在 2-3 个月。",
    metric_key: "bonus_months",
    metric_value: 2.5,
    sample_size: 6,
    sources: [source("https://a.com/x"), source("https://b.com/y")],
  });
  const index = L.buildLibraryIndex([subject()], [signalItem(), claim], COMPANIES, NOW);
  assert.deepEqual(index[0].assertion_counts, { fact: 0, signal: 1, claim: 1 });
  assert.equal(index[0].item_count, 2);
});

test("没有画像的主体不进索引（宁可少一个，也不显示无归属的名字）", () => {
  const index = L.buildLibraryIndex(
    [subject({ company_id: "unknown" })],
    [signalItem()],
    COMPANIES,
    NOW,
  );
  assert.equal(index.length, 0);
});

test("rejected / retired 主体不进索引（人工治理结论必须生效）", () => {
  for (const status of ["rejected", "retired"]) {
    assert.equal(
      L.buildLibraryIndex([subject({ status })], [signalItem()], COMPANIES, NOW).length,
      0,
      status,
    );
  }
});

// ── 筛选 ────────────────────────────────────────────────────────────────
function index2() {
  const subjects = [
    subject({ id: "s-1", name: "飞书", kind: "business_unit", job_count: 397 }),
    subject({ id: "s-2", name: "字节跳动", kind: "company", job_count: 20642 }),
  ];
  const items = [
    signalItem({ subject_id: "s-1", metric_key: "hiring_trend_30d_pct", metric_value: 42 }),
    signalItem({ subject_id: "s-1", metric_key: "salary_range_k", metric_value: 30,
                 dimension: "compensation_intensity" }),
    signalItem({ subject_id: "s-2", metric_key: "hiring_trend_30d_pct", metric_value: 5 }),
  ];
  return L.buildLibraryIndex(subjects, items, COMPANIES, NOW);
}

test("验收 §5.2：能筛出「招聘量增长 >30% 且有薪资数据的业务线」", () => {
  const rows = L.filterSubjects(index2(), {
    kind: "business_unit",
    metric: "hiring_trend_30d_pct",
    metricMin: 30,
    has: ["salary_range_k"],
  });
  assert.deepEqual(rows.map((r) => r.name), ["飞书"]);
});

test("筛选：缺少 has 指标的主体被排除", () => {
  const rows = L.filterSubjects(index2(), { has: ["salary_range_k"] });
  assert.deepEqual(rows.map((r) => r.id), ["s-1"]);
});

test("筛选：metricMax 生效，且没有该指标的主体一律不放行", () => {
  const rows = L.filterSubjects(index2(), { metric: "hiring_trend_30d_pct", metricMax: 10 });
  assert.deepEqual(rows.map((r) => r.id), ["s-2"]);
  assert.equal(L.filterSubjects(index2(), { metric: "bonus_months" }).length, 0);
});

test("分面：每个分面在「排除自己」的集合上计数，点下去不会得到 0 条", () => {
  const rows = index2();
  const facets = L.computeFacets(rows, { kind: "business_unit" });
  // kind 分面自己不受 kind 筛选影响 → 两个 kind 都还在
  assert.deepEqual(
    facets.kind.sort((a, b) => a.key.localeCompare(b.key)),
    [{ key: "business_unit", count: 1 }, { key: "company", count: 1 }],
  );
  // metric 分面在「已按 kind 筛过」的集合上算 → 只剩业务线那条
  const salary = facets.metric.find((m) => m.key === "salary_range_k");
  assert.deepEqual(salary, { key: "salary_range_k", count: 1 });
  // 每个分面项的计数都必须等于「真的筛出来多少个」
  for (const bucket of facets.metric) {
    const actual = L.filterSubjects(rows, { kind: "business_unit", metric: bucket.key }).length;
    assert.equal(bucket.count, actual, bucket.key);
  }
});

test("排序：jobs 按在招规模、insights 按条目数、fresh 按新鲜度", () => {
  const rows = index2();
  assert.deepEqual(L.sortSubjects(rows, "jobs").map((r) => r.id), ["s-2", "s-1"]);
  assert.deepEqual(L.sortSubjects(rows, "insights").map((r) => r.id), ["s-1", "s-2"]);
});

test("查询串解析：未知取值丢弃，不静默筛出 0 条", () => {
  const f = L.parseLibraryFilters(
    new URLSearchParams("kind=nope&assertion=fact&dimension=bogus&sort=weird&metricMin=30&has=a&has=b"),
  );
  assert.equal(f.kind, undefined);
  assert.equal(f.dimension, undefined);
  assert.equal(f.assertion, "fact");
  assert.equal(f.sort, "fresh");
  assert.equal(f.metricMin, 30);
  assert.deepEqual(f.has, ["a", "b"]);
});

test("索引不带正文：缓存条目超 2MB 会被 Vercel 静默丢弃，正文必须留到分页时现取", () => {
  const index = L.buildLibraryIndex([subject()], [signalItem()], COMPANIES, NOW);
  const metric = index[0].metrics[0];
  // 元组顺序 = [metric_key, metric_value, sample_size, assertion]，改口径必须改这里
  assert.deepEqual(metric, ["hiring_volume_30d", 47, 397, "signal"]);
  assert.equal(L.metricKey(metric), "hiring_volume_30d");
  assert.equal(L.metricValue(metric), 47);
  assert.equal(L.metricSample(metric), 397);
  assert.equal(L.metricAssertion(metric), "signal");
  assert.equal(index[0].cards, undefined, "正文不该出现在缓存索引里");
});

test("索引体积：1500 个主体 × 7 条指标必须远小于 2MB 缓存上限", () => {
  const subjects = [];
  const items = [];
  for (let i = 0; i < 1500; i++) {
    subjects.push(subject({ id: `s-${i}`, name: `业务线${i}` }));
    for (let k = 0; k < 7; k++) {
      items.push(
        signalItem({ id: `i-${i}-${k}`, subject_id: `s-${i}`, metric_key: `m_key_${k}` }),
      );
    }
  }
  const bytes = JSON.stringify(
    L.buildLibraryIndex(subjects, items, COMPANIES, NOW),
  ).length;
  // 超过 2MB 会被 Vercel 数据缓存**静默丢弃** → 每请求重建索引（线上实测 ~10s）。
  // 留 2 倍余量：洞察库还会长。
  assert.ok(bytes < 1_000_000, `索引 ${Math.round(bytes / 1024)}KB，离 2MB 上限太近`);
});


test("subject_id 为 NULL = 公司级，必须挂到公司主体上（否则存量说法整批消失）", () => {
  // 线上实测：存量 5,958 条 T2/T3 条目都是公司级写入的（subject_id 为 NULL）。
  // 按 subject_id 硬筛会让洞察库的筛选器里只剩「数据」一档，一条说法都不出现。
  const companySubject = subject({ id: "s-co", kind: "company", name: "字节跳动" });
  const legacyClaim = signalItem({
    id: "legacy-1",
    subject_id: null,
    origin: "public_web",
    assertion: "claim",
    grade: "experience",
    content: "据公开讨论，年终奖普遍在 2-3 个月。",
    metric_key: "bonus_months",
    metric_value: 2.5,
    sample_size: 6,
    sources: [source("https://a.com/x"), source("https://b.com/y")],
  });
  const index = L.buildLibraryIndex([companySubject], [legacyClaim], COMPANIES, NOW);
  assert.equal(index.length, 1);
  assert.equal(index[0].assertion_counts.claim, 1);
  assert.equal(index[0].item_count, 1);
});

test("公司级条目不会误挂到业务线主体上", () => {
  const bu = subject({ id: "s-bu", kind: "business_unit", name: "飞书" });
  const legacy = signalItem({ id: "legacy-2", subject_id: null });
  // 没有 company 主体时，公司级条目无处可挂 —— 宁可不显示，也不能记到业务线头上。
  // 结果是这个业务线主体一条内容都没有 → 整个不进洞察库（不留空卡片）。
  const index = L.buildLibraryIndex([bu], [legacy], COMPANIES, NOW);
  assert.equal(index.length, 0);
});

// ============================================================
// 2026-09-03 创始人定调：洞察库不放「数据层」——招聘结构不算信息差。
// ============================================================

test("一条可展示内容都没有的主体不进洞察库（撤掉数据层后不能留下空卡片）", () => {
  const onlySignal = subject({ id: "s-only-signal" });
  // 索引层面：即使传进来的条目全被门挡掉，主体也不该出现
  const index = L.buildLibraryIndex([onlySignal], [], COMPANIES, NOW);
  assert.equal(index.length, 0);
});

test("有说法内容的主体照常进洞察库", () => {
  const claim = signalItem({
    origin: "public_web",
    assertion: "claim",
    grade: "experience",
    content: "据公开讨论，年终奖普遍在 2-3 个月。",
    metric_key: "bonus_months",
    sample_size: 6,
    sources: [source("https://a.com/x"), source("https://b.com/y")],
  });
  const index = L.buildLibraryIndex([subject()], [claim], COMPANIES, NOW);
  assert.equal(index.length, 1);
  assert.equal(index[0].item_count, 1);
  assert.equal(L.metricKey(index[0].metrics[0]), "bonus_months");
});

test("说法层的主题键都有人话标签（没有标签的键会在页面上直接露出英文）", () => {
  for (const key of [
    "bonus_months", "overtime_level", "interview_rounds",
    "promotion_pace", "intern_experience", "work_culture", "layoff_mention",
  ]) {
    assert.ok(L.METRIC_LABEL[key], `metric_key ${key} 缺人话标签`);
  }
});

test("迁移 209 的主题映射与 T3 写入的标题一一对应（改一边必须改另一边）", () => {
  const fs2 = require("node:fs");
  const sql = fs2.readFileSync(
    path.join(__dirname, "..", "supabase", "migrations", "209_insight_topic_metric_keys.sql"),
    "utf8",
  );
  const catalog = fs2.readFileSync(
    path.join(__dirname, "..", "crawler", "insight_backlog.py"),
    "utf8",
  );
  // T3_TOPIC_CATALOG 里的每个主题名都必须在迁移的映射里出现，否则那批条目归不了类
  const topics = [...catalog.matchAll(/^\s{4}"([^"]+)":\s*\{"topic"/gm)].map((m) => m[1]);
  assert.ok(topics.length >= 5, "没解析到 T3 主题目录");
  for (const topic of topics) {
    assert.ok(
      sql.includes(`title like '${topic}%'`),
      `T3 主题「${topic}」没有对应的 metric_key 映射（迁移 209）`,
    );
  }
});

test("同主题多条时按中位数筛，不能取碰到的第一条", () => {
  // 线上实测：滴滴同时挂着「加班强度·准时下班(1)」与两条「加班强度·加班多(4)」。
  // 取第一条会让它被「加班强度 ≤ 2」筛出来 —— 用户筛「加班少的公司」，第一个结果写着「加班多」。
  const items = [1, 4, 4].map((v, i) =>
    signalItem({
      id: `ot-${i}`,
      origin: "public_web",
      assertion: "claim",
      grade: "experience",
      content: `据公开讨论，加班情况 ${v}`,
      metric_key: "overtime_level",
      metric_value: v,
      sample_size: 6,
      sources: [source(`https://a${i}.com/x`), source(`https://b${i}.com/y`)],
    }),
  );
  const index = L.buildLibraryIndex([subject()], items, COMPANIES, NOW);
  assert.equal(index.length, 1);
  // 中位数 = 4 → 「加班少（≤2）」筛不出来
  assert.equal(L.filterSubjects(index, { metric: "overtime_level", metricMax: 2 }).length, 0);
  // 「加班多（≥4）」筛得出来
  assert.equal(L.filterSubjects(index, { metric: "overtime_level", metricMin: 4 }).length, 1);
});

test("单条时中位数就是它自己（不能因为改了聚合口径把正常情况弄坏）", () => {
  const one = signalItem({
    origin: "public_web", assertion: "claim", grade: "experience",
    content: "据公开讨论，准时下班", metric_key: "overtime_level", metric_value: 1,
    sample_size: 6, sources: [source("https://a.com/x"), source("https://b.com/y")],
  });
  const index = L.buildLibraryIndex([subject()], [one], COMPANIES, NOW);
  assert.equal(L.filterSubjects(index, { metric: "overtime_level", metricMax: 2 }).length, 1);
});

// ── 洞察库只收信息差：数据层的排除名单 ─────────────────────────────────
// 2026-09-07 线上实测的故障：只有「索引 / 卡面」两处过滤了 origin=derived，
// 「展开全部」那一处漏了 —— 而库里带 subject_id 的行全部是 derived，
// 于是波克城市卡面写「说法 1 条」，点开是 7 条清一色的数据层。
// 下面三条把「排除名单」「取数点共用」「筛选项不透传已撤维度」钉死。

test("数据层三类一律不收：派生结构分布 / 年报数字 / 上市状态", () => {
  const derived = signalItem();
  const filing = signalItem({
    origin: "official_filing",
    assertion: "fact",
    subject_id: null,
    metric_key: null,
    content: "据 2025 年年报，在职员工 31,213 人；技术人员占 21%。",
  });
  const listing = signalItem({
    origin: "wikidata",
    assertion: "fact",
    dimension: "listing",
    metric_key: "listing_status",
    content: "据 Wikidata 公开资料，58同城 为已上市公司。",
  });
  for (const item of [derived, filing, listing]) {
    assert.equal(L.isLibraryContent(item), false, `${item.origin}/${item.dimension} 应被排除`);
  }
});

test("真信息差照收：公开说法、以及人工录入的招聘时机", () => {
  const claim = signalItem({
    origin: "public_web",
    assertion: "claim",
    dimension: "culture",
    metric_key: "overtime_level",
    content: "据公开讨论，加班较多。",
  });
  const timing = signalItem({
    origin: "manual",
    assertion: "fact",
    dimension: "timing",
    metric_key: null,
    content: "据公开信息，财年切换前后 HC 相对偏紧。",
  });
  assert.equal(L.isLibraryContent(claim), true);
  assert.equal(L.isLibraryContent(timing), true);
});

test("已撤下的维度不许再从查询串进来（否则用户读成「这家没数据」）", () => {
  assert.ok(L.LIBRARY_EXCLUDED_DIMENSIONS.includes("listing"));
  const f = L.parseLibraryFilters(new URLSearchParams("dimension=listing"));
  assert.equal(f.dimension, undefined, "listing 已整维撤下，透传它必然筛出 0 条");
  const ok = L.parseLibraryFilters(new URLSearchParams("dimension=culture"));
  assert.equal(ok.dimension, "culture");
});

test("取数层的四个点共用同一份排除名单，不许再手写 neq(origin, derived)", () => {
  const store = fs.readFileSync(path.join(__dirname, "..", "lib", "insight-library-store.ts"), "utf8");
  // 只看代码行：注释里刻意留着这个写法当反面教材。
  const code = store
    .split("\n")
    .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
    .join("\n");
  assert.equal(
    /\.neq\(\s*["']origin["']/.test(code),
    false,
    "别在取数点手写 origin 过滤，一律走 libraryScope（上一版就是漏了一处）",
  );
  // 三条 insight_items 查询（索引 / 按 subject / 按 company）都必须被 libraryScope 包住。
  const queries = store.match(/from\("insight_items"\)/g) || [];
  const scoped = store.match(/libraryScope\(/g) || [];
  assert.equal(queries.length, 3, "insight_items 的取数点数量变了，请确认每一处都过了 libraryScope");
  assert.equal(
    scoped.length,
    queries.length,
    "libraryScope 的调用点数 ≠ insight_items 取数点数，必有一处漏过滤",
  );
});

test("主题标签有语义色且文字用 ink-1（同族 fg 在浅底上过不了 AA）", () => {
  assert.equal(L.metricTone("overtime_level"), "amber");
  assert.equal(L.metricTone("interview_rounds"), "sky");
  assert.equal(L.metricTone("bonus_months"), "green");
  assert.equal(L.metricTone("从没见过的键"), "neutral");
  const cls = L.metricChipClass("overtime_level");
  assert.match(cls, /bg-tone-amber-bg/);
  assert.match(cls, /\bink-1\b/, "标签文字必须是 ink-1，别退回 text-tone-*-fg / ink-3");
  assert.equal(/t-micro/.test(cls), false, "11px 是改前那版看不见的字号");
});

// ── 数据层名单必须被「洞察库」与「岗位卡抽屉」两个面共用 ──────────────────
// 2026-09-07 创始人先撤洞察库的数据层，再撤抽屉里的年报数字。两处各写一份名单，
// 迟早出现「一个面撤了、另一个面还在显示」。名单住在 lib/insight-bundle。

test("洞察库的 origin 排除名单就是共用的那一份，不许在库这边另写一份", () => {
  const bundle = fs.readFileSync(path.join(__dirname, "..", "lib", "insight-bundle.ts"), "utf8");
  assert.match(bundle, /export const DATA_LAYER_ORIGINS = \["derived", "official_filing"\]/);
  assert.deepEqual([...L.LIBRARY_EXCLUDED_ORIGINS], ["derived", "official_filing"]);
});

test("抽屉与徽章计数两条读路都过同一份名单（否则徽章说有洞察、点开是空的）", () => {
  const drawer = fs.readFileSync(path.join(__dirname, "..", "app", "api", "insights", "route.ts"), "utf8");
  const availability = fs.readFileSync(
    path.join(__dirname, "..", "app", "api", "insights", "availability", "route.ts"), "utf8",
  );
  for (const [name, src] of [["抽屉 /api/insights", drawer], ["徽章计数 /api/insights/availability", availability]]) {
    assert.match(src, /DATA_LAYER_ORIGINS_FILTER/, `${name} 必须用共用的数据层过滤`);
    const code = src.split("\n").filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line)).join("\n");
    assert.equal(
      /\.neq\(\s*["']origin["']/.test(code),
      false,
      `${name} 别再手写 neq(origin, derived)`,
    );
  }
});

test("洞察库比抽屉多撤上市状态那一维（抽屉是看岗位顺带了解公司，上市与否还算上下文）", () => {
  const listing = { origin: "wikidata", dimension: "listing", metric_key: "listing_status" };
  assert.equal(L.isLibraryContent(listing), false);
  // 但它不属于共用的数据层名单 —— 抽屉照常显示。
  assert.equal(B_isDataLayer(listing), false);
});

function B_isDataLayer(item) {
  const B = loadTsModule(path.join("lib", "insight-bundle.ts"), {
    "./insight-verification": V,
    "./types": {},
  });
  return B.isDataLayerItem(item);
}

// ============================================================
// 标签只承载类型，不承载取值（2026-09-09 创始人定）
// 上线前的形态是「加班强度 · 996/大小周」「数据 · 基于 217 个在招岗」：同一主体同时挂着
// 相反档位时，两张同名标签会自相矛盾。判据写成机器可查的两条，避免下次有人拼回去。
// ============================================================
const AC = loadTsModule(path.join("lib", "insight-assertion-chip.ts"), { "./types": {} });

test("承诺芯片的 label 只有档位名：不含取值、不含分隔号", () => {
  const cases = [
    AC.assertionChip("fact", "fact", null, 3, null),
    AC.assertionChip("signal", "experience", null, 0, { sample_n: 217 }),
    AC.assertionChip("claim", "experience", null, 4, null),
    AC.assertionChip(null, "fact", null, 0, null),        // 存量行回落
    AC.assertionChip(null, "experience", 12, 0, null),    // 存量行回落
  ];
  for (const chip of cases) {
    assert.match(chip.label, /^(事实|数据|说法|经验)$/, `label 必须只有档位名，实际是「${chip.label}」`);
    assert.equal(/\d/.test(chip.label), false, `label 里不许出现数字：${chip.label}`);
    assert.equal(chip.label.includes("·"), false, `label 里不许拼依据：${chip.label}`);
  }
});

test("承诺依据没被删掉，只是挪出芯片：样本量 / 来源数仍在 basis 里", () => {
  // signal 丢掉样本量 = 丢掉「只给数字」这个承诺本身（spec §1.5 红线）。
  assert.equal(AC.assertionChip("signal", "experience", null, 0, { sample_n: 217 }).basis, "基于 217 个在招岗");
  assert.equal(AC.assertionChip("signal", "experience", 320, 0, null).basis, "基于 320 个在招岗");
  assert.equal(AC.assertionChip("signal", "experience", null, 0, null).basis, "基于在招岗位");
  assert.equal(AC.assertionChip("claim", "experience", null, 4, null).basis, "据 4 处公开讨论");
  assert.equal(AC.assertionChip("fact", "fact", null, 0, null).basis, "据官方披露");
});

test("两个展示面用同一份 label + basis，不许任一处把依据拼回芯片", () => {
  for (const rel of [path.join("app", "insights", "insights-client.tsx"), path.join("components", "CompanyInsightDrawer.tsx")]) {
    const src = fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
    assert.match(src, /\{chip\.label\}/, `${rel} 芯片必须只渲染 chip.label`);
    assert.match(src, /\{chip\.basis\}/, `${rel} 承诺依据必须仍然渲染在芯片外`);
  }
});

test("主题标签同样只有类型名：档位取值不许进标签", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "app", "insights", "insights-client.tsx"), "utf8");
  // 档位取值（准时下班 / 996 …）来自 GRADE_LABEL；页面一旦引它就是又拼回标签了。
  assert.equal(/GRADE_LABEL/.test(src), false, "洞察库页面不该再用 GRADE_LABEL 拼标签");
  // 卡面与展开视图两处：标签文字之后必须直接闭合，不许再挂任何东西。
  const flat = src.replace(/\s/g, "");
  for (const who of ["m", "item"]) {
    assert.ok(
      flat.includes(`{METRIC_LABEL[${who}.metric_key]||${who}.metric_key}</span>`),
      `${who} 那处主题标签后面被拼了东西（标签只放类型名）`,
    );
  }
});
