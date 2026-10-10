// 交互契约：2026-10-10 用户走查（真 Chrome 点线上）查出来的一批问题的回归钉。
// 每条断言对应一个当时实测到的现象，现象写在断言旁边 —— 看到红了先读那句话，别直接改断言。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

const jobCard = read("components/JobCard.tsx");
const jobFilters = read("components/JobFilters.tsx");
const todayClient = read("app/today-client.tsx");
const jobsClient = read("app/jobs/jobs-client.tsx");
const campusAllJobs = read("app/campus/campus-all-jobs.tsx");
const useJobFilters = read("hooks/useJobFilters.ts");
const insightsClient = read("app/insights/insights-client.tsx");
const insightDrawer = read("components/CompanyInsightDrawer.tsx");
const insightClient = read("lib/insight-client.ts");
const navbar = read("components/NavbarClient.tsx");
const profileEditor = read("components/ProfileEditor.tsx");
const resumePanel = read("components/ResumeProfilePanel.tsx");
const preferenceForm = read("components/PreferenceForm.tsx");
const globalsCss = read("app/globals.css");

// ───────────────────────── 样式：写错的透明度修饰符 ─────────────────────────

// Tailwind 3 的 `/NN` 透明度只认 0、5、10…100 这一档（步长 5），其它数字要写成 `/[0.98]`。
// 写成 `bg-[#f4efe6]/98` 不报错、不告警，只是**不生成任何 CSS** —— 背景直接透明。
// 现象：账号菜单浅色下是透明的，页面上的「3 个」徽标从菜单中间透出来；洞察库吸顶筛选条没有底色；
//       推荐页暗色模式的信号标签顶着浅色底配浅色字。线上 CSS 里这几个类一条规则都没有。
test("Tailwind 透明度修饰符只用合法档位，其余必须写成方括号", () => {
  const VALID = new Set([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]);
  const PREFIX = "(?:bg|text|border|ring|from|to|via|shadow|outline|divide|fill|stroke|decoration|accent|caret|placeholder)";
  const re = new RegExp(
    "(?:[a-z0-9\\[\\]=:&_.-]+:)*" + PREFIX + "-(?:\\[[^\\]\\s]+\\]|[a-z]+(?:-[a-z]+)*(?:-\\d{2,3})?)/(\\d{1,3})(?![\\d.\\]])",
    "g",
  );
  const hits = [];
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
      const full = path.join(dir, ent.name);
      if (ent.isDirectory()) walk(full);
      else if (/\.(tsx|ts|jsx|js|css)$/.test(ent.name)) {
        fs.readFileSync(full, "utf8")
          .split("\n")
          .forEach((line, i) => {
            re.lastIndex = 0;
            let m;
            while ((m = re.exec(line))) {
              if (!VALID.has(Number(m[1]))) {
                hits.push(`${path.relative(ROOT, full).replace(/\\/g, "/")}:${i + 1} ${m[0]}`);
              }
            }
          });
      }
    }
  };
  for (const dir of ["app", "components", "lib"]) walk(path.join(ROOT, dir));
  assert.deepEqual(hits, [], "这些类不会生成 CSS，改成 /[0.NN]：\n" + hits.join("\n"));
});

// 扫描器自己得能抓到东西，否则上面那条永远绿。
test("透明度扫描的正则确实能命中写错的写法", () => {
  const PREFIX = "(?:bg|text|border)";
  const re = new RegExp("(?:[a-z0-9\\[\\]=:&_.-]+:)*" + PREFIX + "-(?:\\[[^\\]\\s]+\\]|[a-z]+(?:-[a-z]+)*(?:-\\d{2,3})?)/(\\d{1,3})(?![\\d.\\]])", "g");
  const found = (s) => Array.from(s.matchAll(re), (m) => Number(m[1]));
  assert.deepEqual(found("bg-[#f4efe6]/98 p-1"), [98]);
  assert.deepEqual(found("dark:bg-[#7fb2e8]/12 dark:text-white"), [12]);
  assert.deepEqual(found("bg-white/72"), [72]);
  assert.deepEqual(found("bg-white/[0.72] border-black/[0.08]"), []);
  assert.deepEqual(found("bg-white/70"), [70]);
});

// 现象（审查发现，就出在修上面那条的时候）：把 `/12` 改成 `/[0.12]` 时后面的空格被吃掉，
// `dark:bg-[#e0b15a]/[0.12]dark:text-[#e0b15a]` 粘成一个类名 —— 两个 dark 类都不生效，
// 而上面的透明度扫描只认 `/NN`，看不见这种写法。
test("方括号透明度后面不能直接粘着下一个类", () => {
  const glued = /\/\[[0-9.]+\][A-Za-z]/;
  const hits = [];
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
      const full = path.join(dir, ent.name);
      if (ent.isDirectory()) walk(full);
      else if (/\.(tsx|ts|jsx|js)$/.test(ent.name)) {
        fs.readFileSync(full, "utf8")
          .split("\n")
          .forEach((line, i) => {
            if (glued.test(line)) hits.push(`${path.relative(ROOT, full).replace(/\\/g, "/")}:${i + 1}`);
          });
      }
    }
  };
  for (const dir of ["app", "components", "lib"]) walk(path.join(ROOT, dir));
  assert.deepEqual(hits, [], "这些行的类名粘在一起了，补空格：\n" + hits.join("\n"));
  assert.equal(glued.test("dark:bg-[#e0b15a]/[0.12]dark:text-[#e0b15a]"), true);
  assert.equal(glued.test("dark:bg-[#e0b15a]/[0.12] dark:text-[#e0b15a]"), false);
});

// ───────────────────────── 岗位卡「更多」菜单 ─────────────────────────

// 现象：点开「更多」后按 ESC、点卡片外都关不掉，只能再点一次「更多」；连开两张卡，两个菜单同时挂着。
test("岗位卡的「更多」/ 原因面板：点外面和按 ESC 都能关", () => {
  assert.match(jobCard, /useClickOutside\(actionsRef,\s*closePanels,\s*panelOpen\)/);
  assert.match(jobCard, /useEscapeKey\(/);
  assert.match(jobCard, /const panelOpen = moreOpen \|\| reasonOpen;/);
  assert.match(jobCard, /<div ref=\{actionsRef\}/);
});

// ───────────────────────── 筛选器 ─────────────────────────

// 现象（读码确证）：连调两次 set() 用的是同一份旧 filters，后一次把前一次盖回去 ——
// 「岗位方向」弹层点「清空」，二级清了、一级「全部研发」还勾着，筛选没变。
test("「岗位方向」清空必须一次改完一级和二级", () => {
  const picker = jobFilters.slice(jobFilters.indexOf("function FunctionPicker("), jobFilters.indexOf("function CompanyTierPicker("));
  assert.ok(picker.length > 0);
  assert.match(picker, /onClick=\{onClear\}/);
  assert.equal(
    /onClick=\{\(\) => \{\s*onChangeFunction\(""\);\s*onChangeRole\(""\);/.test(picker),
    false,
    "不要在一次点击里连调两个单字段 setter",
  );
  const clears = jobFilters.match(/onClear=\{\(\) => (?:patch|onPatch)\(\{ jobFunction: "", jobRole: "" \}\)\}/g) || [];
  assert.equal(clears.length, 2, "桌面弹层和「更多」弹窗里的两处 FunctionPicker 都要接 onClear");
});

// 现象：已有「深圳」时点开城市弹层，只看到一个 chip 和一片空白 —— 输入框没提示、也没光标。
test("城市 / 关键词弹层：打开即聚焦，已有条件时仍提示可以继续加", () => {
  assert.equal((jobFilters.match(/placeholder="输入(?:城市|关键词)后按回车" autoFocus/g) || []).length, 2);
  assert.match(jobFilters, /placeholder=\{chips\.length \? "再加一个，回车确认" : placeholder\}/);
  assert.equal(/placeholder=\{chips\.length \? "" : placeholder\}/.test(jobFilters), false);
});

// 「边打边搜」的输入框必须对中文输入法免疫：组词期间不上报。
test("边打边搜的三个输入框都走 useImeValue", () => {
  assert.match(jobFilters, /const mobileKeyword = useImeValue\(filters\.keyword/);
  assert.match(jobFilters, /<input \{\.\.\.mobileKeyword\} aria-label="关键词"/);
  assert.match(jobFilters, /const ime = useImeValue\(value, onChange\);/);
  assert.match(insightsClient, /const searchInput = useImeValue\(filters\.q/);
  assert.equal(/onChange=\{\(e\) => set\(\{ q: e\.target\.value \}\)\}/.test(insightsClient), false);
});

// ───────────────────────── 推荐页 ─────────────────────────

// 现象：处理完最后一张卡，整页换成「今天暂时没有新的对口机会」，「已收藏 · 撤销」跟着一起消失。
test("推荐页的提示条在有卡 / 无卡两种页面上都渲染", () => {
  assert.match(todayClient, /const toastNode =/);
  assert.equal((todayClient.match(/\{toastNode\}/g) || []).length, 2);
  assert.match(todayClient, /<AllHandled \/>/, "自己处理完的 0 和「没有对口机会」的 0 要分开说");
});

// 现象：动作接口失败时卡片消失又悄悄回来，没有任何说明。
test("推荐页的动作失败要说出来", () => {
  assert.match(todayClient, /onActionResult=\{handleActionResult\}/);
  // 文案走全站唯一那份（components/ActionToast 的 jobActionToastText），不在这里另写一句。
  assert.match(todayClient, /\{jobActionToastText\(null, false\)\}/);
});

// 失败提示和另一张卡的「撤销」条要能同时看见：A 卡失败的 3 秒里用户可能刚收藏了 B 卡。
test("推荐页：失败提示与撤销条叠放，不是二选一", () => {
  assert.match(todayClient, /actionFailed \|\| state\.toast \? \(/);
  assert.match(todayClient, /flex flex-col items-center gap-2 px-4/);
  assert.equal(/const toastNode = actionFailed \? \(/.test(todayClient), false);
});

// 现象（审查发现）：切范围触发的刷新在请求开头就读了操作记录；刷新途中刚点的收藏还没落库，
// 新 feed 里仍带着那张卡，重置队列时会把它「复活」成没处理过的样子。
test("推荐页：重置队列时滤掉本次会话已处理的岗", () => {
  assert.match(todayClient, /const actedRef = useRef<Set<string>>\(new Set\(\)\);/);
  assert.match(todayClient, /actedRef\.current\.add\(jobId\);/);
  assert.match(todayClient, /list\.filter\(\(o\) => !acted\.has\(o\.job\.id\)\)/);
  // 回滚 / 撤销成功后要放回去，否则那张卡再也回不来
  assert.equal((todayClient.match(/actedRef\.current\.delete\(jobId\);/g) || []).length, 2);
});

// 现象（线上实测）：顶栏切到「海外」，页面上方的说明已经写着「4 个海外岗排在最前」，
// 下面仍是原来那 30 个国内岗 —— useReducer 的初值只在挂载时读一次。
test("推荐页：服务端换了一批机会，队列跟着重置", () => {
  assert.match(todayClient, /feedStampRef\.current === feed\.generated_at/);
  assert.match(todayClient, /dispatch\(\{\s*type: "reset",\s*sections: \{/);
});

// ───────────────────────── 求职范围 ─────────────────────────

// 现象（线上实测）：/jobs 海外范围下 0 条，切回国内 7 秒后仍是 0 条，手动点「重新搜索」才回到 604 条。
test("切换求职范围后岗位列表要重搜", () => {
  for (const [name, src] of [["jobs-client", jobsClient], ["campus-all-jobs", campusAllJobs]]) {
    assert.match(src, /searchedScopeRef\.current === jobScope/, name);
    assert.match(src, /searchedScopeRef\.current = jobScope;\s*refresh\(\);/, name);
  }
});

// 现象（读码确证）：切换失败时开关先翻过去再悄悄翻回来，没有任何提示。
test("求职范围切换失败要有提示", () => {
  const fn = navbar.slice(navbar.indexOf("async function handleScopeChange"), navbar.indexOf("// 账号头像"));
  assert.match(fn, /setJobScope\(previous\);[\s\S]*setScopeToast\("切换失败，请重试"\)/);
});

// ───────────────────────── 搜索 / 加载更多 ─────────────────────────

test("搜索失败不把服务端原话给用户看；加载更多失败贴着按钮说", () => {
  assert.equal(/error: data\?\.error \|\| /.test(useJobFilters), false, "data.error 可能是数据库报错原文");
  assert.match(useJobFilters, /moreFailed: more,/);
  for (const [name, src] of [["jobs-client", jobsClient], ["campus-all-jobs", campusAllJobs]]) {
    assert.match(src, /\{error && !moreFailed && \(/, name);
    assert.match(src, /\{moreFailed && \(/, name);
  }
});

// 现象（读码确证）：校招全部岗搜索失败时，错误条和「没有匹配的校招岗位，可以放宽筛选条件」同时出现。
test("校招全部岗：搜索失败时不再配一个「没有匹配」的空状态", () => {
  assert.match(campusAllJobs, /visibleJobs\.length === 0 && error && !moreFailed \?/);
  assert.match(campusAllJobs, /onClick=\{refresh\}/);
});

// 现象（读码确证）：0 条来自学历 / 公司等条件时，「放宽筛选条件」只清城市、类型、关键词 = 点了没反应。
test("岗位库空状态的「放宽筛选条件」不会点了没反应", () => {
  const fn = jobsClient.slice(jobsClient.indexOf("function broadenFilters()"), jobsClient.indexOf("const { toast, show: showToast"));
  assert.match(fn, /if \(filters\.city \|\| filters\.jobType \|\| filters\.keyword\)/);
  assert.match(fn, /clearAllWithUrl\(\);/);
});

// ───────────────────────── 洞察 ─────────────────────────

// 现象（读码确证）：展开失败后点「点这里重试」，走的是 toggle —— 面板被收起来，不重试。
test("洞察库展开失败的重试是真的重试", () => {
  assert.match(insightsClient, /onClick=\{\(\) => void loadItems\(\)\} className="underline underline-offset-2">\s*点这里重试/);
});

test("洞察库：被新请求取代的旧请求不收尾 loading", () => {
  const fn = insightsClient.slice(insightsClient.indexOf("const load = useCallback("), insightsClient.indexOf("useEffect(() => {\n    if (firstRender.current)"));
  assert.match(fn, /if \(abortRef\.current === controller\) \{/);
});

// 现象：网络失败时抽屉写「该公司暂无经核实的职业洞察信息…宁缺毋滥」，和真没数据分不开，也没法重试。
test("洞察抽屉：没取到 ≠ 没有洞察", () => {
  assert.match(insightClient, /failure_reason: "fetch_failed"/);
  assert.match(insightClient, /if \(!res\.ok\) throw new Error/);
  assert.match(insightDrawer, /const fetchFailed = data\?\.failure_reason === "fetch_failed";/);
  assert.match(insightDrawer, /setRetryTick\(\(n\) => n \+ 1\)/);
});

// 现象（线上实测）：抽屉右上角的关闭是纯图标按钮，没有可读名字。
test("洞察抽屉的关闭按钮有可读名字", () => {
  assert.match(insightDrawer, /aria-label="关闭洞察"/);
});

// 现象（读码确证）：点完「提交」表单立刻被收起，「已提交，审核后匿名展示」那句跟着被藏掉。
test("洞察抽屉：提交成功后不收起表单", () => {
  assert.equal(/onSubmitted=\{\(\) => setSubmitOpen\(false\)\}/.test(insightDrawer), false);
});

// ───────────────────────── 个人中心 ─────────────────────────

// 现象（读码确证）：资料没读回来时表单是空的，点保存会把已有昵称 / 签名覆盖成空（服务端整行 upsert）。
test("个人资料没加载完 / 加载失败时不许保存", () => {
  assert.match(profileEditor, /disabled=\{saveState === "saving" \|\| loading \|\| loadFailed\}/);
  assert.match(profileEditor, /if \(loading \|\| loadFailed\) return;/);
});

// 现象（读码确证）：画像读取失败时显示「还没有简历画像，先上传或粘贴简历开始」，像是画像丢了。
test("简历画像读取失败不冒充「还没有画像」；内部报错不给用户看", () => {
  assert.match(resumePanel, /\) : loadFailed \? \(/);
  assert.equal(/SILICONFLOW_API_KEY/.test(resumePanel), false, "环境变量名和部署步骤不是给求职者看的");
  assert.equal(/原因：\$\{data\.llm_error/.test(resumePanel), false);
});

test("求职目标加载失败：中文说明 + 重试，不显示 Failed to fetch 这类原文", () => {
  assert.equal(/setMessage\("加载失败：" \+/.test(preferenceForm), false);
  assert.equal(/setSaveErr\("保存失败：" \+/.test(preferenceForm), false);
  assert.match(preferenceForm, /loadFailed && \(/);
  assert.match(preferenceForm, /id="watch-companies"/);
});

// ───────────────────────── 落地页 ─────────────────────────

// 现象（线上逐宽度实测）：610~840px 四张漂浮卡全部压在标题或正文上，860px 起才干净。
test("落地页漂浮卡在会压字的宽度下整组隐藏", () => {
  assert.match(globalsCss, /@media \(max-width: 860px\) \{ \.lp-floats \{ display: none; \} \}/);
  assert.equal(/@media \(max-width: 600px\) \{ \.lp-floats \{ display: none; \} \}/.test(globalsCss), false);
});

// ───────────────────────── 第二轮：审查与校招 / 公告 / 洞察走查 ─────────────────────────

// 现象（审查发现）：「加载更多」和「重新筛选」共用一个 abortRef、会互相取代；被取代的那个不收尾，
// 它的旗就永远复不了位 —— 按钮卡在 disabled 的「加载中…」，或者页面一直写着「正在筛选…」。
test("洞察库：入口同时管 loading / loadingMore 两个旗", () => {
  const fn = insightsClient.slice(insightsClient.indexOf("const load = useCallback("), insightsClient.indexOf("useEffect(() => {\n    if (firstRender.current)"));
  assert.match(fn, /setLoading\(!append\);\s*setLoadingMore\(append\);/);
  assert.match(fn, /abortRef\.current = null;\s*setLoading\(false\);\s*setLoadingMore\(false\);/);
});

// 现象（审查发现）：ESC 关弹层时同步把焦点移回按钮，输入框先收到 blur，把没回车的草稿当成条件提交了。
test("筛选弹层 ESC：等弹层卸载后再还焦点，不提交草稿", () => {
  assert.match(jobFilters, /window\.setTimeout\(\(\) => trigger\?\.focus\(\), 0\);/);
});

// 输入法不发 compositionend 的情况（安卓打英文、失焦时）要有兜底，同值不重复上报。
test("useImeValue：失焦兜底 + 同值不重复上报", () => {
  const hooks = read("lib/ui/hooks.ts");
  const fn = hooks.slice(hooks.indexOf("export function useImeValue("));
  assert.match(fn, /onBlur: \(event: \{ currentTarget: \{ value: string \} \}\) => \{\s*composing\.current = false;\s*push\(event\.currentTarget\.value\);/);
  assert.match(fn, /if \(next !== latest\.current\) saved\.current\(next\);/);
});

// 现象（线上实测）：校招页头写「1401 个匹配 · 已展示 1000」，翻到第 1000 个按钮就没了，也不说还有；
// 「42+ · 还有更多，可继续加载」的页面上根本没有加载按钮。
test("撞取数上限：说法和「能不能继续加载」对得上，到底了要说明还有没列出的", () => {
  assert.match(jobsClient, /capped && hasMore \? "还有更多，可继续加载" : ""/);
  assert.match(campusAllJobs, /capped && hasMore \? "还有更多，可继续加载" : ""/);
  for (const [name, src] of [["jobs-client", jobsClient], ["campus-all-jobs", campusAllJobs]]) {
    assert.match(src, /\{!hasMore && !loading && capped && displayJobs\.length > 0 &&/, name);
    // 真实总数已知且已全部取回时不说话；被实时复核藏掉的失效岗不算「没列出来」。
    assert.match(src, /\(exactTotal == null \|\| exactTotal > displayJobs\.length\) && \(/, name);
    assert.match(src, /符合条件的共 \$\{exactTotal\} 个，这里列出了最靠前的/, name);
  }
});

// 现象（线上实测）：筛选弹窗底部「查看 0 个岗位」挂了 2.4 秒才变成「查看 1000+ 个岗位」。
test("筛选弹窗的计数按钮：新结果回来前显示「正在筛选…」", () => {
  assert.match(jobFilters, /\{resultPending \? <span>正在筛选…<\/span> : </);
  assert.match(jobsClient, /resultPending=\{loading\}/);
  assert.match(campusAllJobs, /resultPending=\{loading\}/);
});

// 现象（线上实测）：学历选「博士」，前 60 张卡里 36 张只要求本科 —— 这是「我的学历够得着」的语义
// （创始人拍板），但页面上一个字没说。
test("学历筛选说明它是「我的学历」", () => {
  assert.match(jobFilters, /<PillField label="学历" hint="选你自己的学历：/);
});

test("岗位库 / 对比层：没取到不冒充「没有」", () => {
  assert.match(jobsClient, /displayJobs\.length === 0 && !\(error && !moreFailed\) &&/);
  const compare = read("components/SavedCompare.tsx");
  assert.match(compare, /failure_reason === "fetch_failed"/);
});

// ───────────────────────── 洞察抽屉等待时间 ─────────────────────────

// 现象（线上单请求实测）：点开洞察抽屉要对着骨架屏等 2~3 秒（腾讯 2.26 / 2.34s、美团 3.26s），
// 而同一条链路上最轻的登录接口只要 ~0.6s。根因是接口里五步读 + 一次现查派发全是串行的，
// 函数在香港、Supabase 在悉尼，每多串一步就多一趟跨区往返。
test("洞察接口：互不依赖的读并行，现查派发不挡响应", () => {
  const route = read("app/api/insights/route.ts");
  assert.match(
    route,
    /const \[fullProfileRes, jobRows, itemsRes, firstParty, recruitmentCycles\] = await Promise\.all\(\[/,
  );
  assert.match(route, /after\(async \(\) => \{\s*try \{\s*await maybeDispatchInsightEnrich\(/);
  // 占位 / 派发用画像的规范名：用查询词原文会另建一行空画像，反过来挡住真画像（线上实测踩到过）。
  assert.match(route, /const enrichCompany = profileLight\?\.company \?\? company;/);
  assert.match(route, /maybeDispatchInsightEnrich\(\{ userId: user\.id, company: enrichCompany,/);
  assert.equal(
    /const enrichNow = await maybeDispatchInsightEnrich/.test(route),
    false,
    "派发要读台账、写台账、再调 GitHub（超时 10s），不许再放回响应路径上",
  );
});

// ───────────────────────── 收尾批次（2026-10-10）─────────────────────────

// 现象（线上走查）：卡片上一个 <a> 都没有，「官网详情」和标题都是 <button> + window.open ——
// 右键「在新标签页打开」、中键、复制链接地址全都用不了。
test("岗位卡的标题和「官网详情」是真链接，埋点仍在", () => {
  const anchors = jobCard.match(/<a\s+href=\{job\.jd_url\}\s+target="_blank"\s+rel="noopener noreferrer"\s+onClick=\{handleView\}\s+onAuxClick=\{handleAuxView\}/g) || [];
  assert.equal(anchors.length, 2, "标题 + 官网详情，两处");
  assert.equal(/window\.open\(job\.jd_url/.test(jobCard), false, "打开官网交给链接自己，不再 window.open");
  // 埋点与后台核验没有被顺手删掉
  const fn = jobCard.slice(jobCard.indexOf("function handleView()"), jobCard.indexOf("function handleAuxView("));
  assert.match(fn, /track\("opportunity_official_opened"/);
  assert.match(fn, /track\("job_click"/);
  assert.match(fn, /\/api\/job-actions\/\$\{job\.id\}\/view/);
  assert.match(jobCard, /if \(event\.button === 1\) handleView\(\);/);
});

// 现象（审查发现）：筛选条的按钮在冒泡阶段 stopPropagation，冒泡阶段的「点外面关闭」收不到 ——
// 卡片「更多」菜单开着时去点筛选条，菜单留在那儿。
test("useClickOutside 在捕获阶段监听", () => {
  const hooks = read("lib/ui/hooks.ts");
  const fn = hooks.slice(hooks.indexOf("export function useClickOutside("), hooks.indexOf("export type AnchorAlign"));
  assert.match(fn, /window\.addEventListener\("pointerdown", onPointerDown, true\);/);
  assert.match(fn, /window\.removeEventListener\("pointerdown", onPointerDown, true\);/);
});

// 现象（读码确证）：提示条 5 秒到点就落定；动作请求第 6 秒才失败时卡片回不来，页面却说「已恢复原状态」。
test("推荐页：请求没回来之前不落定乐观移除", () => {
  assert.match(todayClient, /if \(\(inflightRef\.current\.get\(jobId\) \?\? 0\) > 0\) \{[\s\S]*?dispatch\(\{ type: "expireToast", jobId \}\);/);
  assert.match(todayClient, /function handleActionResult\(\{ jobId, ok \}: \{ jobId: string; ok: boolean \}\)/);
  assert.match(todayClient, /if \(awaitingResultRef\.current\.delete\(jobId\)\) \{\s*removedRef\.current\.delete\(jobId\);\s*dispatch\(\{ type: "finalizeRemove", jobId \}\);/);
});

// 现象（审查发现）：JobCard 失败时会再调一次 onActionChange(原来的动作)。原动作非空的卡（关键提醒区里
// 已收藏的岗）失败后，旧实现把这次通知当成「又一次乐观移除」—— 卡片不回来，还提示「已收藏」。
test("推荐页：失败回滚在结果回调里做，不把 JobCard 的回滚通知当成新动作", () => {
  const change = todayClient.slice(todayClient.indexOf("function handleActionChange("), todayClient.indexOf("function handleActionResult("));
  assert.match(change, /if \(removedRef\.current\.has\(jobId\)\) return;/);
  assert.equal(/removeRollback/.test(change), false, "回滚不在 onActionChange 里做");
  const result = todayClient.slice(todayClient.indexOf("function handleActionResult("), todayClient.indexOf("async function undo("));
  assert.match(result, /if \(!ok\) \{[\s\S]*?dispatch\(\{ type: "removeRollback", jobId \}\);\s*setActionFailed\(true\);/);
  // 撤销后重新操作：前一个请求的晚到结果不许动现在这次移除
  assert.match(result, /if \(left > 0\) return;/);
  // 撤销把卡放回队列后，晚到的结果不再碰它
  const undo = todayClient.slice(todayClient.indexOf("async function undo("), todayClient.indexOf("function displayItemsFor("));
  assert.match(undo, /removedRef\.current\.delete\(jobId\);/);
});

// 现象（读码确证）：误点「标记投递」后，「投递记录」页没有任何移除入口（推荐页的撤销只有 5 秒）。
test("投递记录可以移除，且要先确认（整行删除，进展补不回来）", () => {
  const applied = read("app/applied/applied-client.tsx");
  assert.match(applied, /移除记录/);
  assert.match(applied, /确定移除/);
  assert.match(applied, /移除后进展也会一起清掉/);
  assert.match(applied, /method: "PUT",[\s\S]*?body: JSON\.stringify\(\{ action: null \}\)/);
  assert.match(applied, /移除失败，请重试/);
  // 失败不许当成功：只有接口确认 ok 才把卡片拿掉
  const fn = applied.slice(applied.indexOf("async function removeRecord"), applied.indexOf("return (\n    <div>"));
  assert.ok(fn.indexOf("throw new Error") < fn.indexOf("setRemoved("), "先判失败，再移除");
});
