const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const A = loadTs(path.join(__dirname, "..", "lib", "announcement-postings.ts"));

const row = (overrides = {}) => ({
  id: "1", source_portal: "x", source_url: "https://gov.example.cn/notice/1/?utm_source=radar",
  title: "北京市某单位公开招聘公告", region: null, employer_type: "事业单位", audience: "unknown",
  published_at: "2026-09-20", deadline: "2026-10-01", deadline_text: null, status: "active",
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

test("公告页首屏限量加载、文案说明搜索范围和未知截止日", () => {
  const fs = require("node:fs");
  const source = fs.readFileSync(path.join(__dirname, "..", "app", "programs", "announcements-client.tsx"), "utf8");
  // 页大小挪进 lib：服务端要按同一个数切首屏那一页（从 "use client" 文件里拿不到常量值）。
  const F = loadTs(path.join(__dirname, "..", "lib", "announcement-filters.ts"));
  assert.equal(F.ANNOUNCEMENT_PAGE_SIZE, 40);
  assert.match(source, /const INITIAL_VISIBLE_COUNT = ANNOUNCEMENT_PAGE_SIZE/);
  assert.match(source, /visible\.slice\(0, shownCount\)/);
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
  assert.match(route, /postings\.map\(toAnnouncementCard\)/);

  const client = read("app", "programs", "announcements-client.tsx");
  assert.match(client, /fetch\("\/api\/programs\/postings"/);
  // 全量没到时，筛选后的数字给不出来就不写——不许拿首屏（无筛选）的计数冒充
  assert.match(client, /all \? buildFacets\(all, filters, today\) : pristine \? initial\.facets : null/);
});
