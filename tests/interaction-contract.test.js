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
  assert.match(todayClient, /const toastNode = /);
  assert.equal((todayClient.match(/\{toastNode\}/g) || []).length, 2);
  assert.match(todayClient, /<AllHandled \/>/, "自己处理完的 0 和「没有对口机会」的 0 要分开说");
});

// 现象：动作接口失败时卡片消失又悄悄回来，没有任何说明。
test("推荐页的动作失败要说出来", () => {
  assert.match(todayClient, /onActionResult=\{handleActionResult\}/);
  assert.match(todayClient, /操作失败，已恢复原状态/);
});

// 现象（线上实测）：顶栏切到「海外」，页面上方的说明已经写着「4 个海外岗排在最前」，
// 下面仍是原来那 30 个国内岗 —— useReducer 的初值只在挂载时读一次。
test("推荐页：服务端换了一批机会，队列跟着重置", () => {
  assert.match(todayClient, /feedStampRef\.current === feed\.generated_at/);
  assert.match(todayClient, /dispatch\(\{ type: "reset", sections: feed\.sections \}\)/);
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
  assert.equal(
    /const enrichNow = await maybeDispatchInsightEnrich/.test(route),
    false,
    "派发要读台账、写台账、再调 GitHub（超时 10s），不许再放回响应路径上",
  );
});
