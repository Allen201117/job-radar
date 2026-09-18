const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const F = loadTs(path.join(__dirname, "..", "lib", "announcement-filters.ts"));
const { todayInDisplayZone } = loadTs(path.join(__dirname, "..", "lib", "relative-time.ts"));

const TODAY = "2026-09-18";
const mk = (o) => ({
  id: o.id ?? o.title, sourcePortal: "x", sourceUrl: `https://gov.cn/${o.id ?? o.title}`,
  title: o.title, region: o.region ?? null, employerType: o.employerType ?? null,
  audience: o.audience ?? "unknown", publishedAt: o.publishedAt ?? "2026-09-01",
  deadline: o.deadline ?? null, deadlineText: null, verdict: o.verdict ?? "ok",
});

const POOL = [
  mk({ title: "北京高校教师招聘", region: "北京市", employerType: "高校", audience: "fresh_grad", deadline: "2026-09-20", publishedAt: "2026-09-10" }),
  mk({ title: "北京医院招聘", region: "北京市", employerType: "医疗卫生", audience: "experienced", deadline: "2026-12-01", publishedAt: "2026-09-12" }),
  mk({ title: "上海事业单位招聘", region: "上海市", employerType: "事业单位", audience: "both", deadline: "2026-09-19", publishedAt: "2026-09-05" }),
  mk({ title: "湖南研究院招聘", region: "湖南省", employerType: "科研院所", audience: "unknown", deadline: null, publishedAt: "2026-09-15" }),
];

test("按地区/单位类型/受众/关键词筛", () => {
  const f = (p) => POOL.filter((x) => F.matchesFilters(x, { ...F.EMPTY_FILTERS, ...p }, TODAY)).map((x) => x.title);
  assert.deepEqual(f({ region: "北京市" }), ["北京高校教师招聘", "北京医院招聘"]);
  assert.deepEqual(f({ employerType: "高校" }), ["北京高校教师招聘"]);
  assert.deepEqual(f({ q: "医院" }), ["北京医院招聘"]);
  // both 同时算进应届与社会；unknown 只在「全部」里出现——不知道就别假装知道
  assert.deepEqual(f({ audience: "fresh_grad" }), ["北京高校教师招聘", "上海事业单位招聘"]);
  assert.deepEqual(f({ audience: "experienced" }), ["北京医院招聘", "上海事业单位招聘"]);
});

test("「7 天内截止」不把截止日未知的算进去", () => {
  const soon = POOL.filter((x) =>
    F.matchesFilters(x, { ...F.EMPTY_FILTERS, closingWithinDays: 7 }, TODAY)).map((x) => x.title);
  assert.deepEqual(soon, ["北京高校教师招聘", "上海事业单位招聘"]);
  // 湖南那条 deadline=null：不知道什么时候截止，就不该混进「快截止了，赶紧投」里催人
  assert.ok(!soon.includes("湖南研究院招聘"));
});

test("分面计数忽略该维度自身的选择（选了北京仍能看见其它省有多少）", () => {
  const facets = F.buildFacets(POOL, { ...F.EMPTY_FILTERS, region: "北京市" }, TODAY);
  const regions = Object.fromEntries(facets.regions.map((r) => [r.value, r.count]));
  assert.equal(regions["北京市"], 2);
  assert.equal(regions["上海市"], 1, "选了北京后，上海的计数仍要给出来，否则换地区得先清空");
  // 单位类型这一维则**受**地区选择影响（它不是自身维度）
  assert.deepEqual(facets.employerTypes.map((e) => e.value).sort(), ["医疗卫生", "高校"]);
});

test("排序：最快截止在前，截止日未知的沉底", () => {
  const byClosing = F.sortPostings(POOL, "closing", TODAY).map((x) => x.title);
  assert.deepEqual(byClosing, ["上海事业单位招聘", "北京高校教师招聘", "北京医院招聘", "湖南研究院招聘"]);
  const byNewest = F.sortPostings(POOL, "newest", TODAY).map((x) => x.title);
  assert.equal(byNewest[0], "湖南研究院招聘");
});

test("daysUntilDeadline 以自然日计，今天截止 = 0", () => {
  assert.equal(F.daysUntilDeadline("2026-09-18", TODAY), 0);
  assert.equal(F.daysUntilDeadline("2026-09-25", TODAY), 7);
  assert.equal(F.daysUntilDeadline(null, TODAY), null);
});

test("activeFilterCount 数得准（空格不算一个条件）", () => {
  assert.equal(F.activeFilterCount(F.EMPTY_FILTERS), 0);
  assert.equal(F.activeFilterCount({ ...F.EMPTY_FILTERS, q: "   " }), 0);
  assert.equal(F.activeFilterCount({ ...F.EMPTY_FILTERS, region: "北京市", audience: "fresh_grad" }), 2);
});

// ⚠️ 回归：报名截止日是「北京时间的哪一天」，不能用 UTC 日期比。
// Vercel 函数跑 UTC → 北京时间 00:00-08:00 这八小时里 UTC 还是昨天，
// 昨天刚截止的公告会被判成「还没到期」继续展示。
test("todayInDisplayZone 用北京时区，不是 UTC", () => {
  const earlyMorningBeijing = new Date("2026-09-18T00:30:00+08:00"); // = 09-17T16:30Z
  assert.equal(todayInDisplayZone(earlyMorningBeijing), "2026-09-18");
  assert.equal(earlyMorningBeijing.toISOString().slice(0, 10), "2026-09-17", "前提：UTC 确实是前一天");
});
