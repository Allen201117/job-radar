const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadRoute, resolvedQuery } = require("./route-test-utils");
const { loadTs } = require("./_load-ts");

const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), "utf8");

const jobLibraryStat = read("../components/JobLibraryStat.tsx");
const jobFilters = read("../components/JobFilters.tsx");
const tagInput = read("../components/TagInput.tsx");
const preferenceForm = read("../components/PreferenceForm.tsx");
const resumeProfilePanel = read("../components/ResumeProfilePanel.tsx");
// 顶栏交互标记（移动端菜单/汉堡按钮）住在客户端组件里；components/Navbar.tsx 现在只是
// 读 middleware 注入请求头、把登录态透传下去的服务端外壳，不含任何标记。
const navbar = read("../components/NavbarClient.tsx");
const appliedPage = read("../app/applied/page.tsx");
const actionToast = read("../components/ActionToast.tsx");
const jobCard = read("../components/JobCard.tsx");
const jobsClient = read("../app/jobs/jobs-client.tsx");
const savedClient = read("../app/saved/saved-client.tsx");
const sourceTable = read("../components/SourceTable.tsx");
const insightDrawer = read("../components/CompanyInsightDrawer.tsx");
const insightsAdmin = read("../components/InsightsAdminClient.tsx");
const jobsStoreWrite = read("../lib/jobs-store/write.ts");

function tagInputCalls(source) {
  return source.match(/<TagInput\b[\s\S]*?\/>/g) ?? [];
}

function assertTagInputLabels(source, expectedCount, context, expectedFragments) {
  const calls = tagInputCalls(source);
  assert.equal(calls.length, expectedCount, `${context} TagInput call count changed; audit every call`);
  calls.forEach((call, index) => {
    assert.match(call, /ariaLabel=["'][^"']+["']/, `${context} TagInput #${index + 1} needs ariaLabel`);
  });

  const labels = calls.map((call) => call.match(/ariaLabel=["']([^"']+)["']/)?.[1]);
  assert.equal(new Set(labels).size, expectedCount, `${context} aria labels must identify each business field`);
  for (const expected of expectedFragments) {
    assert.ok(labels.some((label) => label.includes(expected)), `missing ${context} aria label: ${expected}`);
  }
}

function createStatsSupabase({ rpcResult, recentResult, sourcesResult } = {}) {
  return {
    rpc: async () => rpcResult ?? { data: 12, error: null },
    from(table) {
      if (table === "jobs") return resolvedQuery(recentResult ?? { count: 8, error: null });
      if (table === "sources") return resolvedQuery(sourcesResult ?? { count: 5, error: null });
      throw new Error(`unexpected table: ${table}`);
    },
  };
}

function loadStatsRoute({
  storeEnabled = false,
  supabase,
  countValidActive,
  countRecentActive,
  onCreateServiceClient,
  onCreateServerSupabase,
  serviceClientError,
} = {}) {
  return loadRoute("app/api/jobs/stats/route.ts", {
    "@/lib/auth": {
      createServerSupabase: async () => {
        onCreateServerSupabase?.();
        throw new Error("stats must not use the cookie-bound Supabase client");
      },
    },
    "@/lib/supabaseService": {
      createServiceClient: () => {
        onCreateServiceClient?.();
        if (serviceClientError) throw serviceClientError;
        return supabase ?? createStatsSupabase();
      },
    },
    "@/lib/jobs-store/read": {
      jobsStoreEnabled: () => storeEnabled,
      countValidActive: countValidActive ?? (async () => 12),
      countRecentActive: countRecentActive ?? (async () => 8),
    },
  });
}

async function assertUncachedStatsFailure(response) {
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { ok: false, error: "stats_failed" });
  const cacheControl = response.headers.get("cache-control");
  assert.equal(cacheControl, "no-store");
  assert.ok(!cacheControl.includes("public"));
  assert.ok(!cacheControl.includes("s-maxage"));
}

test("jobs stats GET returns its real body with a one-minute CDN cache policy", async () => {
  const route = loadStatsRoute({
    storeEnabled: true,
    supabase: createStatsSupabase({ sourcesResult: { count: 5, error: null } }),
    countValidActive: async () => 12,
    countRecentActive: async () => 8,
  });

  const response = await route.GET();

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    ok: true,
    validActive: 12,
    recent24h: 8,
    sources: 5,
  });
  assert.equal(
    response.headers.get("cache-control"),
    "public, s-maxage=60, stale-while-revalidate=300",
  );
});

test("jobs stats uses one fixed service aggregation identity for anonymous and logged-in cache semantics", async () => {
  let serviceClients = 0;
  let cookieClients = 0;
  const route = loadStatsRoute({
    supabase: createStatsSupabase({
      rpcResult: { data: 27, error: null },
      recentResult: { count: 19, error: null },
      sourcesResult: { count: 7, error: null },
    }),
    onCreateServiceClient: () => { serviceClients += 1; },
    onCreateServerSupabase: () => { cookieClients += 1; },
  });

  const anonymous = await route.GET();
  const loggedIn = await route.GET();
  const expected = { ok: true, validActive: 27, recent24h: 19, sources: 7 };

  assert.deepEqual(await anonymous.json(), expected);
  assert.deepEqual(await loggedIn.json(), expected);
  assert.equal(serviceClients, 2);
  assert.equal(cookieClients, 0);
  assert.equal(anonymous.headers.get("cache-control"), loggedIn.headers.get("cache-control"));
});

test("jobs stats source has no cookie-bound or user-data dependency", () => {
  const statsRoute = read("../app/api/jobs/stats/route.ts");
  assert.match(statsRoute, /createServiceClient/);
  assert.doesNotMatch(statsRoute, /createServerSupabase|cookies?\s*\(/);
  assert.doesNotMatch(statsRoute, /auth\.getUser|user_metadata|candidate_profiles|user_preferences/);
});

test("jobs stats returns an uncached 500 when fixed service client initialization fails", async () => {
  const route = loadStatsRoute({ serviceClientError: new Error("missing service credentials") });
  await assertUncachedStatsFailure(await route.GET());
});

for (const scenario of [
  { name: "valid-active RPC", key: "rpcResult" },
  { name: "recent jobs query", key: "recentResult" },
  { name: "sources query", key: "sourcesResult" },
]) {
  test(`jobs stats returns an uncached 500 when the Supabase ${scenario.name} fails`, async () => {
    const supabase = createStatsSupabase({
      [scenario.key]: { data: null, count: null, error: new Error(`${scenario.name} failed`) },
    });
    const route = loadStatsRoute({ supabase });

    await assertUncachedStatsFailure(await route.GET());
  });
}

test("jobs stats returns an uncached 500 when the HK jobs store rejects", async () => {
  const route = loadStatsRoute({
    storeEnabled: true,
    countValidActive: async () => {
      throw new Error("jobs store failed");
    },
  });

  await assertUncachedStatsFailure(await route.GET());
});

test("jobs stats returns an uncached 500 when the HK recent-active count rejects", async () => {
  const route = loadStatsRoute({
    storeEnabled: true,
    countRecentActive: async () => {
      throw new Error("recent jobs store failed");
    },
  });

  await assertUncachedStatsFailure(await route.GET());
});

test("empty single-select filters do not masquerade as active conditions", () => {
  // 2026-09-02 线上实测：已选条件行凭空冒出两个「✕不限」（经验 + 发布时间）。
  // 根因是 labelFor 照常查表——每个单选组第一项都是 { value: "", label: "不限" / "全部海外" }，
  // 于是「没选」被翻译成「不限」这个看起来像已选的字符串，既生成了 chip、又让触发按钮显示成已选态。
  // 「不限」是给弹层里的选项用的，不是给「已选摘要」用的，所以空值必须早返回空串。
  const body = jobFilters.match(/function labelFor\([\s\S]*?\n\}/)?.[0];
  assert.ok(body, "could not locate labelFor");
  assert.match(body, /if \(!value\) return "";/, "labelFor must return empty string for an unset value");
});

test("filter popovers escape the filter bar's scroll container", () => {
  // 2026-09-02 线上实测：筛选条内层是 overflow-x-auto（移动端要横滑），而**滚动容器两个轴都裁剪**。
  // 弹层原本 absolute 在条里 → 463px 高的弹层被裁进 42px 高的条里，DOM 里明明打开了、屏幕上
  // 什么都不出现，用户直接判「这些按钮点不了」。必须 portal 到 body + fixed 定位手动锚位。
  assert.match(jobFilters, /import \{ createPortal \} from "react-dom";/, "popover must be portaled");
  // ⚠️ 别用 /function X\([\s\S]*?\n\}/ 切函数体：多行解构参数里的 `}: {` 是顶格的，会把匹配提前
  // 截断成只剩签名（这条断言初版就栽在这）。切到下一个顶层 function 为止才稳。
  const popover = jobFilters.match(/function Popover\([\s\S]*?(?=\nfunction )/)?.[0];
  assert.ok(popover, "could not locate Popover");
  assert.match(popover, /createPortal\(/, "popover must render through a portal, not inline");
  assert.match(popover, /className="job-filter-pop fixed /, "portaled popover must be position:fixed");
  assert.doesNotMatch(popover, /className="[^"]*\babsolute\b/, "popover must not go back to absolute inside the bar");
  // 锚位要跟着滚动走，否则 portal 出去的弹层会飘在原地
  assert.match(popover, /addEventListener\("scroll", place, true\)/, "popover must re-anchor on scroll");
});

test("filter popovers can be closed by clicking their own trigger", () => {
  // 2026-09-02 回归：关外部逻辑挂在 window 的 pointerdown 上，判据是「点击目标不在弹层内」。
  // 触发按钮本身不在弹层里 → 点它会先被判成「点了外面」而关闭，紧接着的 click 又把它开回来，
  // 净效果是同一个按钮永远关不掉，只能按 Esc 或点空白处。修法是让「触发按钮 + 弹层」的包裹层
  // 吃掉 pointerdown，别让 window 监听器看见。这里钉死：每个包裹层都必须带这个拦截。
  // 注意别用 /<div ...[^>]*>/ 去圈整个标签：箭头函数的 `=>` 里就有个 `>`，会把匹配提前截断
  // （本断言初版就栽在这，报了个假失败）。改成「带守卫的包裹层数量 == 全部包裹层数量」。
  // 2026-09-02 起五个维度收进 FilterField 统一封装，守卫也只剩这一处。
  const allWrappers = (jobFilters.match(/<div ref=\{anchorRef\} className="relative shrink-0"/g) || []).length;
  const guarded = (
    jobFilters.match(
      /<div ref=\{anchorRef\} className="relative shrink-0" onPointerDown=\{\(event\) => event\.stopPropagation\(\)\}>/g,
    ) || []
  ).length;
  assert.ok(allWrappers >= 1, `expected the FilterField popover wrapper, found ${allWrappers}`);
  assert.equal(
    guarded,
    allWrappers,
    "every popover wrapper must swallow pointerdown so its own trigger can toggle it closed",
  );
});

test("job library stats wires the tested lifecycle helpers and keeps manual refresh accessible", () => {
  assert.match(
    jobLibraryStat,
    /import\s+\{\s*createJobStatsRefresher\s*,\s*installVisiblePolling\s*\}\s+from\s+["']@\/lib\/job-stats-refresh["']/,
  );
  assert.match(jobLibraryStat, /const\s+POLL_INTERVAL_MS\s*=\s*(?:60_000|60000)\s*;/);
  assert.match(jobLibraryStat, /createJobStatsRefresher\s*\(\s*\{/);
  assert.match(jobLibraryStat, /installVisiblePolling\s*\(\s*\{/);
  assert.match(jobLibraryStat, /documentLike:\s*document/);
  assert.match(jobLibraryStat, /windowLike:\s*window/);
  assert.match(jobLibraryStat, /intervalMs:\s*POLL_INTERVAL_MS/);
  assert.match(jobLibraryStat, /cleanupPolling\s*\(\s*\)/);
  assert.match(jobLibraryStat, /refresher\.dispose\s*\(\s*\)/);
  assert.match(jobLibraryStat, /aria-label=["']立即刷新岗位库计数["']/);
  // 展示给用户的刷新周期必须**从 POLL_INTERVAL_MS 推导**，不能写死数字（旧断言防的是
  // 「常量 60s、界面写 12s」这种谎）。2026-09-02 文案去黑话后，「轮询间隔 60s」这句从正文
  // 移到了 title 提示上——技术词不再糊在用户脸上，但派生关系照旧守住。
  assert.match(jobLibraryStat, /\$\{POLL_INTERVAL_MS\s*\/\s*1000\}\s*秒自动更新/);
  // 「不许出现」类守卫必须只看**用户可见文案**：整份源码里包含解释这些词为何被弃用的注释，
  // 直接对全文断言会把注释算成违规（2026-09-02 实际踩到）。所以先剥掉注释再断言。
  const visibleCopy = stripComments(jobLibraryStat);
  assert.doesNotMatch(visibleCopy, /轮询间隔\s*\d+\s*s/);
  // 去黑话：这两个词是内部实现细节，对求职者零信息量，不许再回到界面上。
  assert.doesNotMatch(visibleCopy, /首屏服务端计数/);
  assert.doesNotMatch(jobLibraryStat, /fetch\(\s*["']\/api\/jobs\/stats["']\s*,\s*\{[\s\S]*?cache\s*:\s*["']no-store["']/);
  const statusText = jobLibraryStat.match(/const\s+statusText\s*=([\s\S]*?);/)?.[1];
  assert.ok(statusText, "could not locate statusText");
  // 诚实底线不变：这个数是 60s 轮询来的，**任何形式的「实时」都不许出现**（旧断言只挡了
  // 「实时刷新」四个字，挡不住单说「实时」——2026-09-02 改文案时就真踩了这个洞，被本测试抓到）。
  assert.ok(!/实时/.test(stripComments(statusText)), "status copy must not claim real-time refresh");
  assert.match(
    jobLibraryStat,
    /const\s+syncLabel\s*=[\s\S]*?每分钟更新/,
    "status copy must describe scheduled refresh in plain Chinese",
  );
});

test("TagInput requires and applies a business-specific accessible name", () => {
  const propsBody = tagInput.match(/interface\s+Props\s*\{([^}]*)\}/)?.[1];
  assert.ok(propsBody, "could not locate TagInput Props");
  assert.match(propsBody, /ariaLabel\s*:\s*string\s*;/);
  assert.match(tagInput, /function\s+TagInput\s*\(\s*\{[\s\S]*?ariaLabel[\s\S]*?\}\s*:\s*Props\s*\)/);
  assert.match(tagInput, /<input\b[\s\S]*?aria-label=\{ariaLabel\}[\s\S]*?\/>/);
});

test("all six preference TagInput calls have distinct explicit aria labels", () => {
  assertTagInputLabels(
    preferenceForm,
    6,
    "PreferenceForm",
    // 「命中关键词」2026-09-02 改名「补充搜索词」：旧名 + 旧占位（Python、机器学习…）在教用户
    // 把技能填进搜索框，正是 /jobs 恒 0 结果那次事故的认知源头。技能改由 skills 列承载（迁移 202）。
    ["目标城市", "目标岗位", "关注公司", "补充搜索词", "排除关键词", "目标行业"],
  );
});

test("all four resume TagInput calls have distinct explicit aria labels", () => {
  assertTagInputLabels(
    resumeProfilePanel,
    4,
    "ResumeProfilePanel",
    ["目标岗位", "期望城市", "技能", "行业"],
  );
});

test("mobile menu backdrop is hidden, non-semantic, and still closes the menu", () => {
  const backdrop = navbar.match(
    /<(?:button|div)\b(?:(?!<(?:button|div)\b)[\s\S])*?className=["'][^"']*fixed inset-0 top-14[^"']*["'][\s\S]*?\/>/,
  )?.[0];

  assert.ok(backdrop, "could not locate the mobile menu backdrop");
  assert.match(backdrop, /^<div\b/);
  assert.match(backdrop, /aria-hidden=["']true["']/);
  assert.match(backdrop, /onClick=\{\(\)\s*=>\s*setMenuOpen\(false\)\}/);
  assert.doesNotMatch(backdrop, /\b(?:role|tabIndex|type|aria-label)=/);

  const hamburger = navbar.match(
    /<button\b(?:(?!<button\b)[\s\S])*?aria-label=\{menuOpen\s*\?\s*["']关闭菜单["']\s*:\s*["']打开菜单["']\}[\s\S]*?<\/button>/,
  )?.[0];
  assert.ok(hamburger, "could not locate the mobile hamburger button");
  assert.match(hamburger, /aria-expanded=\{menuOpen\}/);
});

test("applied empty state explains the real action and has one primary Today CTA", () => {
  assert.match(appliedPage, /import\s+Link\s+from\s+["']next\/link["'];/);
  const emptyState = appliedPage.match(
    /if\s*\(!actions\s*\|\|\s*actions\.length\s*===\s*0\)\s*\{[\s\S]*?\n\s*\}/,
  )?.[0];

  assert.ok(emptyState, "could not locate the no-applied-jobs empty state");
  assert.ok(emptyState.includes("点击「标记投递」"), "empty-state copy must name the actual action");
  assert.match(
    emptyState,
    /<EmptyPanel\b[\s\S]*?action=\{[\s\S]*?<Link\s+href=["']\/today["']\s+className=["']btn-ink["']>[\s\S]*?返回今日机会[\s\S]*?<\/Link>[\s\S]*?\}/,
  );
  assert.equal((appliedPage.match(/返回今日机会/g) ?? []).length, 1, "Today CTA must be unique");
});

// ───────────────────────────────────────────────────────────────
// 点击反馈契约（2026-09-03 立）：每个「点一下要等服务端」的操作，都必须让用户看见
// ① 中间态（在跑）② 结果态（成没成）。分两档：重提交走 SaveToast（居中转圈+打勾），
// 就地高频操作走 ActionToast（底部胶囊）。失败静默 = 用户以为按钮坏了，是这里最要防的事。
// ───────────────────────────────────────────────────────────────

test("简历 AI 解析与保存都复用 SaveToast 的中间态 + 结果态", () => {
  assert.match(resumeProfilePanel, /import\s+SaveToast[\s\S]*?from\s+["']@\/components\/SaveToast["']/);
  // 解析：saving / done / error 三态都要落到 toast 上，不能只有按钮文案。
  assert.match(resumeProfilePanel, /setParseState\("saving"\)/);
  assert.match(resumeProfilePanel, /setParseState\("done"\)/);
  assert.match(resumeProfilePanel, /setParseState\("error"\)/);
  assert.match(resumeProfilePanel, /setSaveState\("saving"\)/);
  assert.match(resumeProfilePanel, /setSaveState\("done"\)/);
  assert.match(resumeProfilePanel, /setSaveState\("error"\)/);
  const toasts = resumeProfilePanel.match(/<SaveToast\b[\s\S]*?\/>/g) ?? [];
  assert.equal(toasts.length, 2, "解析和保存各要一个 SaveToast");
  assert.ok(
    toasts.some((t) => /state=\{parseState\}/.test(t) && /savingText=/.test(t)),
    "解析的中间态要说清在做什么（AI 解析中…）",
  );
  assert.ok(toasts.some((t) => /state=\{saveState\}/.test(t)));
  // 选了文件也要当场确认收到，别让用户盯着一个没反应的输入框。
  assert.match(resumeProfilePanel, /已选择 \{file\.name\}/);
});

test("岗位卡动作在落库后才回调 onActionResult，页面据此弹就地反馈", () => {
  // onActionChange 在乐观更新和失败回滚时各调一次，拿它弹提示会把回滚说成成功。
  assert.match(jobCard, /onActionResult\?:\s*\(result:\s*\{[\s\S]*?ok:\s*boolean/);
  assert.match(jobCard, /onActionResult\?\.\(\{\s*jobId:\s*job\.id,\s*action:\s*next,\s*ok:\s*true\s*\}\)/);
  assert.match(jobCard, /onActionResult\?\.\(\{\s*jobId:\s*job\.id,\s*action:\s*next,\s*ok:\s*false\s*\}\)/);
  for (const [name, source] of [["jobs", jobsClient], ["saved", savedClient]]) {
    assert.match(source, /<ActionToast\b/, `${name} 页要渲染 ActionToast`);
    assert.match(source, /onActionResult=\{/, `${name} 页要把结果接到 toast 上`);
    assert.match(source, /jobActionToastText\(action, ok\)/, `${name} 页要用共用文案`);
  }
  // 文案只有一份，别各页各写一套。
  assert.match(actionToast, /export function jobActionToastText/);
});

test("失败不许静默：源开关 / 取消值得投 / 洞察申诉都要说出来", () => {
  // 源开关：以前失败什么也不做，用户以为切成功了。
  assert.match(sourceTable, /setToggleError\(/);
  assert.match(sourceTable, /disabled=\{togglingId !== null\}/);
  assert.match(sourceTable, /切换中/);
  // 已下线岗位的「取消值得投」：以前失败只是把卡片悄悄放回去。
  assert.match(savedClient, /取消失败，请重试/);
  assert.match(savedClient, /cancelingId === d\.jobId \? "取消中…" : "取消值得投"/);
  // 洞察申诉：以前 !res.ok 直接吞掉。
  assert.match(insightDrawer, /setSendError\("提交失败/);
  assert.match(insightDrawer, /sending \? "提交中…" : "提交"/);
});

test("退出登录有 pending，失败也要有话说", () => {
  assert.match(navbar, /const \[loggingOut, setLoggingOut\] = useState\(false\)/);
  assert.match(navbar, /setLogoutError\("退出失败/);
  const logoutButtons = navbar.match(/<button[^>]*onClick=\{handleLogout\}[\s\S]*?<\/button>/g) ?? [];
  assert.equal(logoutButtons.length, 2, "桌面端和移动端各一个退出按钮");
  logoutButtons.forEach((btn, i) => {
    assert.match(btn, /disabled=\{loggingOut\}/, `退出按钮 #${i + 1} 缺 pending 态`);
  });
});

test("洞察后台审核结果走站内 toast，不再用原生 alert", () => {
  assert.equal(
    (stripComments(insightsAdmin).match(/\balert\(/g) ?? []).length,
    0,
    "原生 alert 是阻断式弹窗，且和站内反馈风格不一致",
  );
  assert.match(insightsAdmin, /<ActionToast\b/);
  // 四组审核按钮都要在处理时给转圈。
  assert.ok(
    (insightsAdmin.match(/处理中…/g) ?? []).length >= 6,
    "上下架 / 申诉 / 分享审核 / 招聘周期四组按钮都要有 pending 文案",
  );
});

// 剥掉 JS/JSX 注释，只留会渲染给用户看的代码文本。
// 顺序要紧：先块注释（含 {/* JSX 注释 */}），再整行 // 注释——只剥「整行就是注释」的行，
// 不碰行尾注释，免得把字符串里的 https:// 之类误伤。
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !/^\s*\/\//.test(line))
    .join("\n");
}


// ───────────────────────────────────────────────────────────────
// 计数诚实契约（2026-09-03 立）：检索是「先取候选、再 JS 精筛」，候选有取数上限。
// 撞上限时 total 只是「取到这么多」，不是真实匹配数 —— 线上「深圳+社招」因此长期把 8000
// （FTS_CAP）当真实数展示，而库里符合条件的有 15,290 个。撞上限时一律不许渲染确定数字。
// ───────────────────────────────────────────────────────────────

test("撞取数上限时页面不渲染确定数字，一律走 formatMatchTotal", () => {
  const code = stripComments(jobsClient);
  assert.match(code, /import \{ formatMatchTotal \} from "@\/lib\/match-total"/);
  assert.match(code, /formatMatchTotal\(total, capped, exactTotal\)/);
  // 计数行必须用 matchTotal.text，不能再把 total 直接插进文案。
  assert.match(code, /\$\{matchTotal\.text\} 个匹配岗位/);
  assert.doesNotMatch(code, /\$\{total\} 个匹配岗位/);
  // 「还有 N 个」是拿 total 减出来的，撞上限时同样是假数字 → 必须先判 capped。
  assert.doesNotMatch(
    code,
    /^\s*<span className="t-num ink-3">（还有 \{total - displayJobs\.length\} 个）<\/span>\s*$/m,
    "撞上限时不能无条件渲染「还有 N 个」",
  );
  assert.match(code, /matchTotal\.approximate \|\| capped \? "（还有更多）"/);
});

test("筛选弹窗的「查看 N 个岗位」拿的是同一份计数文案", () => {
  // 传数字进去就没法表达「8000+」；这里钉死它只接文案，源头统一在 jobs-client。
  assert.match(jobFilters, /resultTotalText: string/);
  assert.doesNotMatch(jobFilters, /resultTotal:\s*number/);
  assert.match(jobFilters, /<span className="t-num">\{resultTotalText\}<\/span>/);
  assert.match(jobsClient, /resultTotalText=\{matchTotal\.text\}/);
});

test("每个筛选项都必须显式归类，才允许用 SQL count 算真实总数", () => {
  const {
    DEFAULT_FILTERS,
    SQL_PUSHED_FILTER_KEYS,
    JS_ONLY_FILTER_KEYS,
    NON_FILTERING_FILTER_KEYS,
    filtersFullyPushedToSql,
  } = loadTs(path.resolve(__dirname, "../lib/job-filter.ts"));

  const classified = [
    ...SQL_PUSHED_FILTER_KEYS,
    ...JS_ONLY_FILTER_KEYS,
    ...NON_FILTERING_FILTER_KEYS,
  ];
  assert.equal(new Set(classified).size, classified.length, "同一个筛选项不能被归两次类");
  assert.deepEqual(
    classified.slice().sort(),
    Object.keys(DEFAULT_FILTERS).sort(),
    "新增筛选项必须显式归类：漏了就是线上悄悄给出另一个错数字",
  );

  // 全默认 → 每一项都已在候选 where 里表达，可以用 count(*) 算真实总数。
  assert.equal(filtersFullyPushedToSql(DEFAULT_FILTERS), true);
  // 任一「只能在 JS 里判」的条件被启用 → 不许再用 SQL 计数。
  for (const key of JS_ONLY_FILTER_KEYS) {
    const enabled = typeof DEFAULT_FILTERS[key] === "boolean" ? true : "x";
    assert.equal(
      filtersFullyPushedToSql({ ...DEFAULT_FILTERS, [key]: enabled }),
      false,
      `${key} 生效时不能用 SQL 计数`,
    );
  }
  // 已下推的条件不影响资格。
  assert.equal(
    filtersFullyPushedToSql({ ...DEFAULT_FILTERS, city: "深圳", jobType: "社招" }),
    true,
  );
  // 用户输入里带 LIKE 通配符时，候选 where 比 JS 的字面子串更宽 → 计数会多算，必须弃权。
  for (const bad of ["%", "_", "\\"]) {
    assert.equal(filtersFullyPushedToSql({ ...DEFAULT_FILTERS, company: bad }), false);
    assert.equal(filtersFullyPushedToSql({ ...DEFAULT_FILTERS, city: bad }), false);
  }
});

test("app 侧补正文时必须作废物化的招聘类型（分类和它依据的字段不许对不上）", () => {
  // 正文是分类输入之一。改了正文却留着旧分类 → 检索侧拿这两列**排除**候选，
  // 真校招/实习岗会被挡在候选外、用户搜不到（2026-09-03 在列表重抓那条链上实锤过 5,275 行）。
  // 不就地重算是刻意的：这里只有 summary，缺 company/apply_url/experience，算错比过时更糟。
  const stmt = stripComments(jobsStoreWrite).match(/update jobs set summary[\s\S]{0,240}?returning id/);
  assert.ok(stmt, "updateJobSummaryById 的 SQL 变了，请重新核对这条不变量");
  assert.match(stmt[0], /recruitment_category\s*=\s*null/i);
  assert.match(stmt[0], /recruitment_explicit\s*=\s*null/i);
});
