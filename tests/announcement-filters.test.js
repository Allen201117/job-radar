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

// 首屏由服务端算、全量到货后由浏览器算：两边必须是同一套函数、同一个结果，
// 否则用户会看到「首屏写 N 条、一动筛选（哪怕又清空）变成 N±k」。
test("initialAnnouncementView 与浏览器在无筛选+最新发布时算出的逐项相同", () => {
  const pool = [
    ...POOL,
    mk({ title: "广东医院招聘", region: "广东省", employerType: "医疗卫生", audience: "fresh_grad", deadline: "2026-09-22", publishedAt: "2026-09-16" }),
    mk({ title: "浙江高校招聘", region: "浙江省", employerType: "高校", audience: "both", deadline: null, publishedAt: "2026-09-02" }),
  ];
  const pageSize = 3;
  const view = F.initialAnnouncementView(pool, TODAY, pageSize);
  const visible = F.sortPostings(pool.filter((p) => F.matchesFilters(p, F.EMPTY_FILTERS, TODAY)), "newest", TODAY);
  assert.deepEqual(view.postings, visible.slice(0, pageSize));
  assert.deepEqual(view.facets, F.buildFacets(pool, F.EMPTY_FILTERS, TODAY));
  assert.equal(view.total, pool.length);
  assert.equal(view.unknownDeadlineCount, 2);
  assert.equal(view.postings.length, pageSize, "只下发一页");
  assert.equal(F.initialAnnouncementView(pool, TODAY).postings.length, pool.length, "不足一页时全给");
});

// 2026-10-10 线上实测：455 张公告里 87 张卡片写「地区未标注」，地区下拉却没有这一项——
// 这批公告按地区怎么筛都筛不到；下拉各项之和（365）也因此对不上总数。
test("地区判不出的公告在下拉里单列一项、排最后，各项之和等于总数", () => {
  const pool = [
    ...POOL,
    mk({ title: "某集团公开招聘公告", region: null, employerType: "央国企", deadline: "2026-10-30" }),
    mk({ title: "某研究所招聘启事", region: null, employerType: "科研院所", deadline: "2026-10-30" }),
  ];
  const facets = F.buildFacets(pool, F.EMPTY_FILTERS, TODAY);
  assert.deepEqual(facets.regions.at(-1), { value: F.UNKNOWN_REGION, count: 2 });
  assert.equal(F.UNKNOWN_REGION, "地区未标注", "下拉这一项的名字要与卡片上的文案一字不差");
  assert.equal(facets.regions.reduce((sum, r) => sum + r.count, 0), pool.length);
  // 没有地区未知的公告时不凭空多出一项
  assert.ok(!F.buildFacets(POOL, F.EMPTY_FILTERS, TODAY).regions.some((r) => r.value === F.UNKNOWN_REGION));
  // 单位类型那一维不加「未标注」项（卡片上没有对应文案）：各项之和只数有单位类型的
  const withType = [...pool, mk({ title: "无类型公告", region: "北京市", employerType: null, deadline: "2026-10-30" })];
  const typeFacets = F.buildFacets(withType, F.EMPTY_FILTERS, TODAY).employerTypes;
  assert.equal(typeFacets.reduce((sum, e) => sum + e.count, 0), withType.length - 1);

  const only = pool.filter((p) => F.matchesFilters(p, { ...F.EMPTY_FILTERS, region: F.UNKNOWN_REGION }, TODAY));
  assert.deepEqual(only.map((p) => p.title), ["某集团公开招聘公告", "某研究所招聘启事"]);
  // 反方向：选了具体地区时，地区未知的不混进来
  assert.equal(pool.filter((p) => F.matchesFilters(p, { ...F.EMPTY_FILTERS, region: "北京市" }, TODAY)).length, 2);
  // 选中「地区未标注」后，别的地区的计数照样给得出来（分面忽略本维度自身的选择）
  const picked = F.buildFacets(pool, { ...F.EMPTY_FILTERS, region: F.UNKNOWN_REGION }, TODAY);
  assert.equal(Object.fromEntries(picked.regions.map((r) => [r.value, r.count]))["北京市"], 2);
});

// 国聘约四成公告写「招满即止」，登记的结束日只是上限。照原样写「报名截止 12/31」= 告诉用户还有两个多月。
test("招满即止的公告不写成「报名截止 X」", () => {
  const chip = (deadline, deadlineText) => F.deadlineChip({ deadline, deadlineText }, TODAY);
  assert.deepEqual(chip("2026-12-31", "招满即止"), { tone: "amber", text: "招满即止，尽早报名 · 最晚 2026/12/31" });
  assert.equal(chip("2026-12-31", "报满即止").text, "招满即止，尽早报名 · 最晚 2026/12/31");
  assert.deepEqual(chip("2026-09-20", "招满即止"), { tone: "rose", text: "招满即止 · 最晚还剩 2 天（2026/9/20）" });
  assert.deepEqual(chip(TODAY, "招满即止"), { tone: "rose", text: "招满即止 · 最晚今天 2026/9/18" });
  assert.deepEqual(chip(null, "招满即止"), { tone: "amber", text: "招满即止，尽早报名" });
  // 反方向：有固定截止日的公告文案一个字都不变
  assert.deepEqual(chip("2026-12-31", "2026-09-01 至 2026-12-31"), { tone: "amber", text: "报名截止 2026/12/31" });
  assert.deepEqual(chip("2026-09-20", "2026-09-01 至 2026-09-20"), { tone: "rose", text: "还剩 2 天 · 2026/9/20 截止" });
  assert.deepEqual(chip(TODAY, null), { tone: "rose", text: "今天 2026/9/18 截止报名" });
  assert.deepEqual(chip(null, "9月18日-9月24日"), { tone: "neutral", text: "报名时间：9月18日-9月24日" });
  assert.deepEqual(chip(null, null), { tone: "neutral", text: "报名时间以公告为准" });
});

// 2026-10-10：筛选 / 排序 / 翻页挪到服务端。首屏与接口必须是同一个函数，否则数字两套。
test("queryAnnouncements：一页一页取，拼起来就是整份筛选结果，计数与分面不随翻页变", () => {
  const pool = [];
  for (let i = 0; i < 95; i += 1) {
    pool.push(mk({
      id: `p${i}`, title: `公告${i}`, region: i % 3 === 0 ? "北京市" : i % 3 === 1 ? "上海市" : null,
      employerType: i % 2 ? "高校" : "央企", audience: i % 4 === 0 ? "fresh_grad" : "unknown",
      deadline: i % 5 === 0 ? null : `2026-10-${String(1 + (i % 28)).padStart(2, "0")}`,
      publishedAt: `2026-09-${String(1 + (i % 17)).padStart(2, "0")}`,
    }));
  }
  for (const [filters, sort] of [
    [F.EMPTY_FILTERS, "newest"],
    [{ ...F.EMPTY_FILTERS, region: "北京市" }, "closing"],
    [{ ...F.EMPTY_FILTERS, region: F.UNKNOWN_REGION, employerType: "高校" }, "newest"],
    [{ ...F.EMPTY_FILTERS, q: "公告1", audience: "fresh_grad" }, "closing"],
  ]) {
    const whole = F.sortPostings(pool.filter((p) => F.matchesFilters(p, filters, TODAY)), sort, TODAY);
    const pages = [];
    for (let offset = 0; ; offset += 40) {
      const r = F.queryAnnouncements(pool, { filters, sort, offset, limit: 40, after: null }, TODAY);
      assert.equal(r.total, whole.length);
      assert.equal(r.allTotal, pool.length);
      assert.deepEqual(r.facets, F.buildFacets(pool, filters, TODAY));
      pages.push(...r.postings);
      if (r.postings.length < 40) break;
    }
    assert.deepEqual(pages.map((p) => p.id), whole.map((p) => p.id));
  }
  // 首屏 = 无筛选、最新发布的第一页（页面随 HTML 下发的就是它）
  assert.deepEqual(F.initialAnnouncementView(pool, TODAY),
    F.queryAnnouncements(pool, { filters: F.EMPTY_FILTERS, sort: "newest", offset: 0, limit: F.ANNOUNCEMENT_PAGE_SIZE, after: null }, TODAY));

  // 翻页游标：两次请求之间，已经画出来的前 40 条里有 3 条下架了。
  // 只按条数（offset=40）接着取 → 后面的整体前移 3 位，有 3 条被跳过；带上「最后一张卡是谁」就一条不漏。
  const q = { filters: F.EMPTY_FILTERS, sort: "newest", limit: 40 };
  const first = F.queryAnnouncements(pool, { ...q, offset: 0, after: null }, TODAY).postings;
  const gone = new Set([first[3].id, first[10].id, first[20].id]);
  const shrunk = pool.filter((p) => !gone.has(p.id));
  const expected = F.sortPostings(shrunk, "newest", TODAY).filter((p) => !first.some((f) => f.id === p.id)).map((p) => p.id);
  const byOffset = F.queryAnnouncements(shrunk, { ...q, offset: 40, after: null }, TODAY).postings.map((p) => p.id);
  const byCursor = F.queryAnnouncements(shrunk, { ...q, offset: 40, after: first.at(-1).sourceUrl }, TODAY).postings.map((p) => p.id);
  assert.deepEqual(byCursor, expected.slice(0, 40), "游标：从最后一张卡后面接着取，一条不漏");
  assert.notDeepEqual(byOffset, expected.slice(0, 40), "对照组：只按条数取确实会跳过 3 条");
  // 游标那条自己也下架了 → 退回按条数取，不报错、不返回空
  const fallback = F.queryAnnouncements(shrunk, { ...q, offset: 40, after: "https://gov.cn/不存在" }, TODAY).postings.map((p) => p.id);
  assert.deepEqual(fallback, byOffset);
});

test("查询串两端互转：浏览器拼的，接口解析出来一字不差；怪参数回默认、不报错", () => {
  const q = {
    filters: { region: "地区未标注", employerType: "地方国企", audience: "experienced", closingWithinDays: 7, q: "招聘 公告" },
    sort: "closing", offset: 80, limit: 40, after: "https://hr.example.cn/notice/?id=1&x=招聘#/detail",
  };
  const round = F.parseAnnouncementQuery(new URLSearchParams(F.announcementQueryParams(q).toString()));
  assert.deepEqual(round, q);
  // 无筛选时的查询串是固定的（浏览器靠它判断「回到了首屏那一组条件」）
  const pristine = { filters: F.EMPTY_FILTERS, sort: "newest", offset: 0, limit: 40, after: null };
  assert.equal(F.announcementQueryParams(pristine).toString(), "limit=40");
  assert.deepEqual(F.parseAnnouncementQuery(new URLSearchParams("limit=40")), pristine);
  // 只有空格的搜索词不算条件
  assert.equal(F.announcementQueryParams({ ...pristine, filters: { ...F.EMPTY_FILTERS, q: "   " } }).toString(), "limit=40");
  // 怪参数：回默认；数字夹在范围里；搜索词截断
  const odd = F.parseAnnouncementQuery(new URLSearchParams(
    `audience=hacker&sort=random&offset=-5&limit=999999&closing=abc&q=${"长".repeat(500)}`));
  assert.equal(odd.filters.audience, "all");
  assert.equal(odd.sort, "newest");
  assert.equal(odd.offset, 0);
  assert.equal(odd.limit, 200, "单次最多 200 条：挡住手写 URL 把全量一次拖走");
  assert.equal(odd.filters.closingWithinDays, 7);
  assert.equal(odd.filters.q.length, 80);
});
