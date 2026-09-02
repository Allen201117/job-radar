const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadRoute, resolvedQuery } = require("./route-test-utils");

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
