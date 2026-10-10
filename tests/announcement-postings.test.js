const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const A = loadTs(path.join(__dirname, "..", "lib", "announcement-postings.ts"));

// deadline 必须是远期：toAnnouncementPosting 会按「今天」丢掉已过截止日的公告。
// 原写 2026-10-01，过了那天 5 条用例集体变红（CI run 37120468602）。
const row = (overrides = {}) => ({
  id: "1", source_portal: "x", source_url: "https://gov.example.cn/notice/1/?utm_source=radar",
  title: "北京市某单位公开招聘公告", region: null, employer_type: "事业单位", audience: "unknown",
  published_at: "2026-09-20", deadline: "2099-12-31", deadline_text: null, status: "active",
  verdict: "ok", first_seen_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z", ...overrides,
});

test("同一份公告两路收录只留一条，官网链接压过公众号转载", () => {
  const weixin = row({ id: "wx", title: "安徽省水电有限责任公司2026年度第二次公开招聘公告", source_url: "https://mp.weixin.qq.com/s/abc", published_at: "2026-09-15" });
  const official = row({ id: "site", title: "安徽省水电有限责任公司 2026 年度第二次公开招聘公告", source_url: "https://www.ahsdgs.cn/index/Article/info.html?cate=6&id=911", published_at: "2026-09-15" });
  const postings = A.toAnnouncementPostings([weixin, official]);
  assert.equal(postings.length, 1);
  assert.equal(postings[0].id, "site");
  assert.equal(postings[0].sameTitleHint, null);
});

test("同名但不同日发布的是不同批次：不合并，用发布日期区分", () => {
  const title = "天津市部分事业单位公开招聘信息";
  const postings = A.toAnnouncementPostings([
    row({ id: "a", title, source_url: "https://hrss.tj.gov.cn/ztzl/ztzl1/sydwgkzp/202609/t20260917_7376612.html", published_at: "2026-09-17" }),
    row({ id: "b", title, source_url: "https://hrss.tj.gov.cn/ztzl/ztzl1/sydwgkzp/202609/t20260911_7372274.html", published_at: "2026-09-11" }),
    row({ id: "c", title: "北京市水务集团公开招聘公告", source_url: "https://gov.example.cn/notice/9" }),
  ]);
  assert.deepEqual(postings.map((p) => p.id), ["a", "b", "c"]);
  assert.deepEqual(postings.map((p) => p.sameTitleHint), ["9月17日发布", "9月11日发布", null]);
});

test("URL 的 # 片段不参与去重（国聘链接里有 SPA hash 路由）", () => {
  const postings = A.toAnnouncementPostings([
    row({ id: "x", title: "甲公告", source_url: "https://www.kmrcjob.cn/#/notice/1" }),
    row({ id: "y", title: "乙公告", source_url: "https://www.kmrcjob.cn/#/notice/2" }),
  ]);
  assert.equal(postings.length, 2);
});

test("招聘单位未写明只给提示，不把公告当作无效", () => {
  const posting = A.toAnnouncementPosting(row({ title: "外派至某国有企业招聘启事" }));
  assert.equal(posting.employerUnclear, true);
  assert.equal(A.toAnnouncementPosting(row({ title: "北京市水务集团公开招聘公告" })).employerUnclear, false);
});

test("标题地区按中文词边界补充，不能把五大连池错认成大连", () => {
  assert.equal(A.inferAnnouncementRegion("北京市某单位公开招聘公告"), "北京市");
  assert.equal(A.inferAnnouncementRegion("五大连池风景区公开招聘公告"), null);
  assert.equal(A.inferAnnouncementRegion("某单位公开招聘公告"), null);
});

// 2026-10-10 线上实测：卡片自己按标题补地区、筛选器只认库里的字段——两套口径。
// 3 张卡片写着地区却按该地区筛不到（重庆下拉 25、卡片 26），「武汉市」「杭州市」在下拉里根本没有。
test("地区只在读侧定一次：库里没有才按标题补，且一律落到省级", () => {
  assert.equal(A.toAnnouncementPosting(row({ region: null, title: "重庆市合川区消防救援支队招聘公告" })).region, "重庆市");
  assert.equal(A.toAnnouncementPosting(row({ region: null, title: "武汉市某单位公开招聘公告" })).region, "湖北省");
  assert.equal(A.toAnnouncementPosting(row({ region: "", title: "杭州某研究院招聘启事" })).region, "浙江省");
  // 库里有值就不看标题（抓取端做过交叉验证，比标题子串可靠）
  assert.equal(A.toAnnouncementPosting(row({ region: "全国", title: "北京市某单位公开招聘公告" })).region, "全国");
  // 判不出就是 null，不硬凑
  assert.equal(A.toAnnouncementPosting(row({ region: null, title: "五大连池风景区公开招聘公告" })).region, null);
  // 标题补出来的地区必须都是省级写法，否则下拉里会多出「杭州市」这种凑不成一项的散户
  for (const city of ["大连", "杭州", "广州", "深圳", "南京", "武汉", "成都", "西安", "郑州", "长沙"]) {
    assert.match(A.inferAnnouncementRegion(`${city}某单位公开招聘公告`), /(省|北京市|天津市|上海市|重庆市)$/, city);
  }
  const client = require("node:fs").readFileSync(path.join(__dirname, "..", "app", "programs", "announcements-client.tsx"), "utf8");
  assert.doesNotMatch(client, /inferAnnouncementRegion/, "卡片不许再自己另推一遍地区：筛选器读不到它推的值");
});

test("招满即止 / 报满即止 认得出来，日期区间不误认", () => {
  assert.equal(A.isRollingDeadline("招满即止"), true);
  assert.equal(A.isRollingDeadline("报满即止"), true);
  assert.equal(A.isRollingDeadline("2026-09-28 至 2026-10-10"), false);
  assert.equal(A.isRollingDeadline(null), false);
});

// 2026-10-10：在展示的公告从 455 条涨到约 1,500 条。PostgREST 单次最多回 1000 行、超出是静默截断。
// 2026-10-10：在展示的公告从 455 条涨到约 1,500 条并会继续累积。两个静默的坑：
// PostgREST 单次最多回 1000 行（超出悄悄没了）；Next 数据缓存单条约 2MB（超了写不进去，每个请求都重取）。
test("公告取数按页取、按页缓存、翻页排序以 id 收尾", () => {
  const store = require("node:fs").readFileSync(path.join(__dirname, "..", "lib", "announcement-postings-store.ts"), "utf8");
  assert.match(store, /\.range\(index \* PAGE_SIZE, \(index \+ 1\) \* PAGE_SIZE - 1\)/, "不分页 = 超过 1000 行的部分悄悄没了");
  assert.match(store, /requestSafeCache\(\s*async \(_bucket: number, index: number\)/, "一页一个缓存条目：整表缓存成一条会撞 2MB");
  assert.match(store, /\.order\("published_at"[\s\S]{0,200}?\.order\("id"/, "翻页边界落在同一天发布的并列块里会重复 / 漏行");
  assert.match(store, /if \(error\) throw new Error\(error\.message\)/, "出错要抛：返回空会把「没取到」缓存 10 分钟");
  assert.match(store, /catch \(e\) \{[\s\S]{0,400}?break;/, "后面的页出错时用已取到的，别让整块公告区消失");
  const pages = Number(/const MAX_PAGES = (\d+);/.exec(store)[1]);
  assert.ok(pages >= 5, "在报名期的公告有几千条，别把保险丝定得比供给还低");
  assert.match(store, /console\.error\([\s\S]{0,120}读取上限/, "撞上限必须留下痕迹，不许静默截断");
  // 每页 1000 行 × 实测约 545 字节 ≈ 0.5MB，离单条 2MB 远
  assert.ok(1000 * 545 < 2 * 1024 * 1024);
});

test("公告页一次只画一页、文案说明搜索范围和未知截止日", () => {
  const fs = require("node:fs");
  const source = fs.readFileSync(path.join(__dirname, "..", "app", "programs", "announcements-client.tsx"), "utf8");
  // 页大小在 lib：服务端首屏、接口、浏览器三处按同一个数切页。
  const F = loadTs(path.join(__dirname, "..", "lib", "announcement-filters.ts"));
  assert.equal(F.ANNOUNCEMENT_PAGE_SIZE, 40);
  assert.match(source, /limit: ANNOUNCEMENT_PAGE_SIZE/);
  assert.match(source, /加载更多/);
  assert.match(source, /可搜：标题、地区、单位类型/);
  assert.match(source, /截止日待确认的/);
});

test("下发到浏览器的公告只带卡片/筛选要读的字段：去掉 id 与 sourcePortal，其余一个不少", () => {
  const posting = A.toAnnouncementPostings([row({ region: "北京市" })])[0];
  const card = A.toAnnouncementCard(posting);
  assert.deepEqual(
    Object.keys(card).sort(),
    Object.keys(posting).filter((k) => k !== "id" && k !== "sourcePortal").sort(),
    "AnnouncementPosting 加了新字段而卡片形状没跟上 → 要么补进 toAnnouncementCard，要么在这里显式排除",
  );
  for (const k of Object.keys(card)) assert.deepEqual(card[k], posting[k], k);
});

// 2026-09-23 线上实测：全量 400+ 条公告整块塞进页面 props，占 /programs HTML 的 252KB / 572KB，
// 而首屏只画 40 张卡。改为首屏只下发第一页 + 服务端分面，全量挂载后从接口取。
test("/programs 首屏不下发全量公告，全量走要登录、读同一份缓存的接口", () => {
  const fs = require("node:fs");
  const read = (...p) => fs.readFileSync(path.join(__dirname, "..", ...p), "utf8");
  const page = read("app", "programs", "page.tsx");
  assert.match(page, /initial=\{initialAnnouncementView\(postings\.map\(toAnnouncementCard\), today\)\}/);
  assert.doesNotMatch(page, /<AnnouncementsClient[^>]*postings=\{/, "别把全量又塞回 props");

  const route = read("app", "api", "programs", "postings", "route.ts");
  assert.match(route, /await requireUser\(\)/, "页面要登录，接口不另开匿名出口");
  assert.match(route, /getAnnouncementPostings\(\)/, "必须读页面同一个跨实例缓存，不新增未缓存的查询");

  assert.match(route, /parseAnnouncementQuery\(new URL\(request\.url\)\.searchParams\)/);
  assert.match(route, /queryAnnouncements\(postings\.map\(toAnnouncementCard\), query, todayInDisplayZone\(\)\)/,
    "接口与首屏必须是同一个函数算的，数字才不会两套");

  // 2026-10-10：筛选 / 排序 / 翻页挪到服务端。浏览器不再拿全量（1,500 条时那一份已有 570KB）。
  const client = read("app", "programs", "announcements-client.tsx");
  assert.match(client, /fetch\(`\/api\/programs\/postings\?\$\{params\.toString\(\)\}`/);
  assert.doesNotMatch(client, /buildFacets|matchesFilters|sortPostings/, "筛选别又挪回浏览器里算");
  // 新条件的结果没回来时，计数给不出来就不写——不许拿上一组条件的数字冒充
  assert.match(client, /const facets = settled \? result\.facets : null/);
  assert.match(client, /const visibleCount = settled \? result\.total : null/);
  // 回到无筛选状态直接用随页面下发的首屏，不再请求
  assert.match(client, /if \(wantKey === PRISTINE_KEY\) \{\s*setShown\(\(cur\) => [^\n]*\{ key: PRISTINE_KEY, result: initial \}\)\);\s*return;/);
  // 翻页带游标（最后一张卡是谁），不只带条数：两次请求之间前面有公告下架时不跳过后面的
  assert.match(client, /params\.set\("after", shownSoFar\[shownSoFar\.length - 1\]\.sourceUrl\)/);
});
