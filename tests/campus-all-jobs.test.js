// 校招专区「全部校招岗」视图（2026-09-18 默认态）的契约。
//
// 这个视图靠 /api/jobs/search 的 jobType 筛选把结果限在校招/实习。jobType 一旦被清空，
// 专区会**静默**开始显示社招岗 —— 不报错、不崩、不变慢，人肉走查也看不出来（社招岗长得
// 和校招岗一样）。所以三条能写 filters 的路径每一条都要有断言钉着。
// 设计文档：docs/superpowers/specs/2026-09-18-campus-zone-all-campus-jobs-design.md

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const repoRoot = path.join(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(repoRoot, rel), "utf8");

const {
  CAMPUS_MODE_JOB_TYPE,
  CAMPUS_VIEW_STORAGE_KEY,
  isCampusView,
  withCampusMode,
  campusResetFilters,
} = loadTs(path.join(repoRoot, "lib", "campus-zone.ts"));
const { DEFAULT_FILTERS, SQL_PUSHED_FILTER_KEYS } = loadTs(path.join(repoRoot, "lib", "job-filter.ts"));

const allJobs = read("app/campus/campus-all-jobs.tsx");
const campusClient = read("app/campus/campus-client.tsx");
const jobFilters = read("components/JobFilters.tsx");

test("模式 → jobType 的两个字面量必须与三桶分类逐字一致", () => {
  // 这两个字符串在 SQL 里是字面量比较（appendRecruitmentPrefilter 的 recruitment_category = '校招'），
  // 写错一个字不会报错，只会让专区返回空列表。
  assert.deepEqual(CAMPUS_MODE_JOB_TYPE, { campus: "校招", intern: "实习" });
  const search = read("lib/jobs-store/search.ts");
  assert.ok(
    search.includes("jobType !== \"校招\" && jobType !== \"实习\""),
    "appendRecruitmentPrefilter 认的取值变了，CAMPUS_MODE_JOB_TYPE 必须跟着改",
  );
});

test("jobType 必须是能下推 SQL 的筛选项（否则计数会退回「N+」且候选口径不可证）", () => {
  assert.ok(
    SQL_PUSHED_FILTER_KEYS.includes("jobType"),
    "jobType 从 SQL 下推表里掉出去了：专区的候选集不再由库收窄，性能与计数两头都会塌",
  );
});

test("withCampusMode: 强制写回 jobType，两个模式各一条", () => {
  assert.equal(withCampusMode({ ...DEFAULT_FILTERS }, "campus").jobType, "校招");
  assert.equal(withCampusMode({ ...DEFAULT_FILTERS }, "intern").jobType, "实习");
  // 被清空过的 filters（DEFAULT_FILTERS.jobType === ""）也必须能救回来
  assert.equal(withCampusMode({ ...DEFAULT_FILTERS, jobType: "" }, "campus").jobType, "校招");
  // 用户手上那份被篡改成社招也要被改回去
  assert.equal(withCampusMode({ ...DEFAULT_FILTERS, jobType: "社招" }, "intern").jobType, "实习");
});

test("withCampusMode: 已经相等时返回同一个对象引用（否则挂载那一拍会白发一次搜索）", () => {
  const f = { ...DEFAULT_FILTERS, jobType: "校招" };
  assert.equal(withCampusMode(f, "campus"), f);
  assert.notEqual(withCampusMode(f, "intern"), f);
});

test("withCampusMode: 不动其它任何筛选项", () => {
  const f = { ...DEFAULT_FILTERS, jobType: "", city: "北京,上海", keyword: "算法", sortBy: "newest" };
  const out = withCampusMode(f, "campus");
  assert.equal(out.city, "北京,上海");
  assert.equal(out.keyword, "算法");
  assert.equal(out.sortBy, "newest");
});

test("campusResetFilters: 「清空全部」保留排序与模式，其余回默认", () => {
  const current = {
    ...DEFAULT_FILTERS,
    jobType: "校招",
    city: "深圳",
    keyword: "后端",
    education: "硕士",
    sortBy: "newest",
  };
  const out = campusResetFilters(DEFAULT_FILTERS, current, "campus");
  // ① jobType 必须活下来 —— 这是整块砖要防的那件事
  assert.equal(out.jobType, "校招");
  // ② 排序是展示偏好不是筛选条件，与 useJobFilters.clearAll 同口径
  assert.equal(out.sortBy, "newest");
  // ③ 其余真的清掉了
  assert.equal(out.city, "");
  assert.equal(out.keyword, "");
  assert.equal(out.education, "");
});

test("campusResetFilters: 在实习模式下清空，回到的是实习不是校招", () => {
  const current = { ...DEFAULT_FILTERS, jobType: "实习", city: "杭州", sortBy: "match" };
  assert.equal(campusResetFilters(DEFAULT_FILTERS, current, "intern").jobType, "实习");
});

test("泄漏路径①②：JobFilters 的 lockedJobType 同时藏掉控件与 chip", () => {
  // 控件：筛选条（桌面）与筛选弹窗（移动）两处都必须被 lockedJobType 守住。
  const guarded = jobFilters.match(/\{!lockedJobType && <RecruitmentType\b/g) || [];
  const all = jobFilters.match(/<RecruitmentType\b/g) || [];
  assert.equal(all.length, 2, `RecruitmentType 的渲染点数量变了（现 ${all.length} 处），逐个确认是否要加守卫`);
  assert.equal(guarded.length, all.length, "每一处 RecruitmentType 都必须被 lockedJobType 守住");
  // chip：collectActiveChips 必须在 lockedJobType 时把 jobType 摘掉。
  // chip 点一下就把 jobType 清成「全部」，是最隐蔽的一条泄漏路径。
  assert.match(
    jobFilters,
    /\["jobType", lockedJobType \? "" : filters\.jobType, ""\]/,
    "已选条件行必须在 lockedJobType 时跳过 jobType chip",
  );
});

test("泄漏路径③：全部校招岗视图不得直接用 hook 自带的 clearAll / clearOne", () => {
  // hook 的 clearAll 会把 jobType 清成 DEFAULT_FILTERS.jobType（= ""），正好是要防的那件事。
  assert.doesNotMatch(
    allJobs,
    /onClearAll=\{clearAll\}|onClearOne=\{clearOne\}/,
    "必须传自己的 clearAll / clearOne（经 withCampusMode 写回 jobType）",
  );
  assert.match(allJobs, /onClearAll=\{clearAllKeepingMode\}/);
  assert.match(allJobs, /onClearOne=\{clearOneKeepingMode\}/);
  assert.match(allJobs, /campusResetFilters\(DEFAULT_FILTERS, f, mode\)/);
  // 单项清除那条路也必须过 withCampusMode（清的正好是 jobType 时会被写回去）
  assert.match(allJobs, /withCampusMode\(next as Filters, mode\)/);
  // 传给 JobFilters 的锁
  assert.match(allJobs, /lockedJobType\s*\/?>/, "必须给 JobFilters 传 lockedJobType");
});

test("全部校招岗视图不得在 SSR 里下发岗位行（CLAUDE.md「校招专区首屏」那块碑）", () => {
  // 6.6 万条逐条序列化 = 必然重演 2026-09-02 那次 responseEnd 10.1s / 单页 2.09MB。
  assert.match(allJobs, /initialJobs: \[\]/, "首屏种子必须为空，岗位一律挂载后经接口取");
  assert.match(allJobs, /initialTotal: 0/);
  assert.match(campusClient, /<CampusAllJobs mode=\{mode\}/);
  // 页面（服务端）不许把岗位行传进这个视图
  const page = read("app/campus/page.tsx");
  assert.doesNotMatch(page, /campusJobs=|internJobs=/, "页面不得向客户端下发岗位行");
});

test("视图切换：默认 all，localStorage 读取必须在 effect 里且包 try/catch", () => {
  assert.equal(CAMPUS_VIEW_STORAGE_KEY, "campus-view");
  assert.ok(isCampusView("all") && isCampusView("must"));
  assert.ok(!isCampusView("") && !isCampusView(null) && !isCampusView("ALL"));
  // 默认值必须是常量 all：在 useState 初始值里读 localStorage = hydration 不一致。
  assert.match(campusClient, /useState<CampusView>\("all"\)/);
  assert.doesNotMatch(
    campusClient,
    /useState<CampusView>\([^)]*localStorage/,
    "不许在 useState 初始值里读 localStorage（服务端渲染不出它 → hydration 不一致）",
  );
  // 读与写各自包 try/catch：隐私窗口 / 站点数据被清时 localStorage 会抛。
  const getter = campusClient.match(/try \{[\s\S]{0,200}?localStorage\.getItem\(CAMPUS_VIEW_STORAGE_KEY\)/);
  assert.ok(getter, "localStorage 读取必须包 try/catch");
  const setter = campusClient.match(/try \{[\s\S]{0,200}?localStorage\.setItem\(CAMPUS_VIEW_STORAGE_KEY/);
  assert.ok(setter, "localStorage 写入必须包 try/catch");
});

test("必投视图必须是渲染函数调用，不能是 render 体内声明的组件", () => {
  // render 体内 `function Foo(){}` 每次渲染都是**新的组件类型** → React 卸载重挂整棵子树：
  // 展开区滚动丢、焦点丢、JobCard 的 effect 全部重跑。不报错、不崩，只是每次交互都闪一下。
  assert.match(campusClient, /renderMustApplyBoard\(\)/, "必投视图要用函数调用内联 JSX");
  assert.doesNotMatch(
    campusClient,
    /<MustApplyBoard\s*\/?>/,
    "不许把 render 体内声明的函数当组件渲染（会导致整棵子树每次重挂）",
  );
});

test("两个视图共用同一个 mode 状态（切过去不会莫名回到校招）", () => {
  const modeStates = campusClient.match(/useState<RecruitMode>/g) || [];
  assert.equal(modeStates.length, 1, "mode 只能有一处状态；第二处必然和第一处漂");
  assert.doesNotMatch(allJobs, /useState<RecruitMode>/, "全部校招岗视图的 mode 由页面传入，不得自持一份");
});

test("库存计数与列表计数是两个数，措辞不能混（诚实口径）", () => {
  // 列表那条撞取数上限时只能给「N+」，不能拿它冒充库存量；库存量走 countCampusLibrary 的精确计数。
  assert.match(allJobs, /formatMatchTotal\(total, capped, exactTotal\)/);
  assert.match(campusClient, /libraryCounts/);
  const search = read("lib/jobs-store/search.ts");
  // 口径：recruitment_explicit 这一条不能少（少了是 75,744，而列表只给得出 69,138 —— 两个数字打架）
  const body = search.match(/export async function countCampusLibrary[\s\S]*?\n\}/);
  assert.ok(body, "找不到 countCampusLibrary");
  assert.match(body[0], /"recruitment_explicit"/, "库存计数必须带 recruitment_explicit，与列表口径对齐");
  assert.match(body[0], /grad_class is null or grad_class >= /, "库存计数必须带同一条往届门");
  assert.match(body[0], /appendJobScopeWhere/, "库存计数必须跟随用户的求职范围");
});

// 审查抓到：空态文案写死「必投 30 家」，而视图切换按钮上的数字是按用户行业收窄后的 cards.length（不恒等于 30）。
test("全部校招岗视图不许写死「必投 30 家」，数量必须来自 props", () => {
  const src = read("app/campus/campus-all-jobs.tsx");
  assert.doesNotMatch(src.replace(/\/\/.*$/gm, ""), /必投 30 家/, "文案里不许出现写死的 30");
  assert.match(src, /mustApplyCount/, "必须通过 mustApplyCount prop 拿数量");
  const client = read("app/campus/campus-client.tsx");
  assert.match(client, /mustApplyCount=\{cards\.length\}/, "父组件必须把 cards.length 传下去");
});
