const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const {
  buildCampusFacets,
  campusFacetKey,
  campusRowMatches,
  countMatchingFacets,
  countUnlabeledInMatch,
  selectionIsUnsatisfiable,
  selectFacetIndexes,
} = loadTs(path.join(__dirname, "..", "lib", "campus-facets.ts"));

// 校招专区把「每条岗位一条记录」换成了「(城市,学历,职能,届别) → 计数」的聚合分面
// （首屏 2.09 MB / 16,494 条 → 约两千个四元组）。这套测试钉死的不变量只有一条，但它是全部：
// **任意筛选组合下，分面累加出来的计数必须与逐条过滤的结果逐位相同**。
// 一旦漂了，卡面会安静地报一个错数字——不报错、不崩，只是骗用户。

/** 参照实现：逐条过滤。语义 = 「排除已知不符的，放行未标注的」（2026-09-03 起，见 campus-facets.ts）。
 *  ⚠️ 它必须与被测实现同语义，这条测试守的不是「语义对不对」，而是**分面聚合与逐条过滤是否等价**。 */
function referencePasses(job, filters) {
  const slim = {
    city: String(job.city ?? "").trim(),
    education: String(job.education ?? "").trim(),
    fn: campusFacetKey(job).fn,
    gc: typeof job.grad_class === "number" ? job.grad_class : null,
  };
  if (filters.city && slim.city && slim.city !== filters.city) return false;
  if (filters.education && slim.education && slim.education !== filters.education) return false;
  if (filters.jobFunction && slim.fn !== filters.jobFunction) return false;
  if (filters.gradClass !== null && slim.gc !== null && slim.gc !== filters.gradClass) return false;
  return true;
}

// 刻意混入各种脏值：null / undefined / 空串 / 前后空格 / 缺字段 / 非数字届别，
// 这些正是「下标编码」最容易与「字符串比对」分家的地方。
const CITIES = ["北京", "上海", " 深圳 ", "", null, undefined, "  "];
const EDUS = ["本科", "硕士", null, " 博士", ""];
const GRADS = [2027, 2028, null, undefined, "2027"];
const TITLES = [
  "2027届校园招聘-后端开发工程师",
  "2027届校园招聘-产品经理",
  "暑期实习-数据分析师",
  "校园招聘-财务管理岗",
  "2027校园招聘",           // 纯活动标签标题 → 走正文兜底
  "校招-机械设计工程师",
  "2027届校园招聘-柜员",
];
const SUMMARIES = [
  "负责服务端架构设计与开发，熟悉 Java/Go。",
  "负责产品规划与需求管理。",
  null,
  "负责品牌营销与市场推广活动策划。",
  "",
];

function makeJobs(n) {
  const jobs = [];
  // 确定性伪随机：用互质步长遍历各维度，保证组合覆盖面且每次跑结果一致（失败可复现）。
  for (let i = 0; i < n; i++) {
    const job = {
      title: TITLES[i % TITLES.length],
      summary: SUMMARIES[(i * 3) % SUMMARIES.length],
      job_type: i % 4 === 0 ? "校招" : null,
      city: CITIES[(i * 5) % CITIES.length],
      education: EDUS[(i * 7) % EDUS.length],
      grad_class: GRADS[(i * 11) % GRADS.length],
    };
    if (i % 13 === 0) delete job.city; // 字段整个缺失，不只是 null
    if (i % 17 === 0) delete job.education;
    if (i % 19 === 0) delete job.grad_class;
    jobs.push(job);
  }
  return jobs;
}

/** 枚举「全部 + 每个候选值」的所有筛选组合。 */
function allFilterCombos(options) {
  const combos = [];
  for (const city of ["", ...options.cityOptions]) {
    for (const education of ["", ...options.educationOptions]) {
      for (const jobFunction of ["", ...options.functionOptions]) {
        for (const gradClass of [null, ...options.gradClassOptions]) {
          combos.push({ city, education, jobFunction, gradClass });
        }
      }
    }
  }
  return combos;
}

test("分面计数 ≡ 逐条过滤：穷举所有筛选组合，每家公司的计数都必须逐位相同", () => {
  const lists = [
    { pattern: "%字节%", jobs: makeJobs(300) },
    { pattern: "%腾讯%", jobs: makeJobs(211) },
    { pattern: "%空公司%", jobs: [] },
  ];
  const { options, byPattern, totals } = buildCampusFacets(lists);
  const combos = allFilterCombos(options);
  assert.ok(combos.length > 50, `组合数应有规模，实际 ${combos.length}`);

  for (const filters of combos) {
    const sel = selectFacetIndexes(filters, options);
    for (const { pattern, jobs } of lists) {
      const expected = jobs.filter((j) => referencePasses(j, filters)).length;
      const actual = countMatchingFacets(byPattern.get(pattern) || [], sel);
      assert.equal(
        actual,
        expected,
        `pattern=${pattern} filters=${JSON.stringify(filters)} 期望 ${expected} 实际 ${actual}`,
      );
    }
  }
  // 无筛选时的总数也必须对得上
  for (const { pattern, jobs } of lists) {
    assert.equal(totals.get(pattern), jobs.length);
  }
});

test("分面确实把岗位压小了（否则这次改造没有意义）", () => {
  const jobs = makeJobs(2000);
  const { byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  const facets = byPattern.get("%x%");
  assert.ok(facets.length < jobs.length / 5, `2000 条应压到 400 以下，实际 ${facets.length}`);
  // 计数总和守恒：一个岗都不能在聚合里丢掉或凭空多出来
  assert.equal(facets.reduce((n, f) => n + f[4], 0), jobs.length);
});

test("筛选值不在当前模式的选项表里 → 计数为 0，不是「匹配全部」也不是「只剩未标注的」", () => {
  // 校招桶与实习桶的选项表不同；用户切模式后旧筛选值可能失效，绝不能因此退化成不筛。
  // ⚠️ 改成「未标注放行」后这里多了一个陷阱：若不先短路失效筛选，无城市的岗会在筛「火星」时
  // 被放行 → 失效筛选静静变成「只看没写城市的岗」。
  const jobs = makeJobs(120);
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  const facets = byPattern.get("%x%");
  const filters = { city: "火星", education: "", jobFunction: "", gradClass: null };
  const sel = selectFacetIndexes(filters, options);
  assert.equal(selectionIsUnsatisfiable(sel), true);
  assert.equal(countMatchingFacets(facets, sel), 0);
  assert.ok(jobs.some((j) => !String(j.city ?? "").trim()), "样本里必须有无城市的岗，否则这条测试没在测东西");

  // 展开区必须同口径：卡面 0，展开也必须 0
  const rows = jobs.map((j) => ({ ...j, fn: campusFacetKey(j).fn }));
  const expanded = selectionIsUnsatisfiable(sel) ? [] : rows.filter((r) => campusRowMatches(r, filters));
  assert.equal(expanded.length, 0);
});

test("未标注的维度放行：字段缺失 ≠ 不符合（2026-09-03 用户实锤后改的语义）", () => {
  // 旧语义把「没写城市/学历/届别」的岗在对应筛选下全部藏起来。live 实测这不是边角：
  // 校招+实习 70,568 个在招岗里届别未知 78.7%、学历空 38.6%、城市空 14.5%。
  // lib/grad-class.js 早就写明「留白 ≠ 隐藏」，服务端也照做，唯独这个筛选器逆着来。
  const jobs = [
    { title: "2027届校园招聘-后端开发工程师", city: null, education: "本科", grad_class: 2027 },
    { title: "2027届校园招聘-后端开发工程师", city: "北京", education: null, grad_class: 2027 },
    { title: "校园招聘-后端开发工程师", city: "北京", education: "本科", grad_class: null },
    { title: "2027届校园招聘-后端开发工程师", city: "上海", education: "硕士", grad_class: 2027 },
  ];
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  const facets = byPattern.get("%x%");
  const sel = (f) => selectFacetIndexes({ city: "", education: "", jobFunction: "", gradClass: null, ...f }, options);

  assert.equal(countMatchingFacets(facets, sel({})), 4, "不筛 → 全部");
  // 北京：命中 2 条北京 + 1 条无城市（放行），上海那条被排除
  assert.equal(countMatchingFacets(facets, sel({ city: "北京" })), 3);
  // 本科：命中 2 条本科 + 1 条无学历（放行），硕士那条被排除
  assert.equal(countMatchingFacets(facets, sel({ education: "本科" })), 3);
  // 2027 届：3 条标了 2027 + 1 条届别未知（放行）—— 旧语义这里只会返回 3
  assert.equal(countMatchingFacets(facets, sel({ gradClass: 2027 })), 4);

  assert.deepEqual(options.cityOptions, ["上海", "北京"]); // 空城市仍不进下拉
  assert.deepEqual(options.educationOptions, ["ってい本科", "硕士"].filter((v) => v !== "ってい本科").concat([]).length ? ["本科", "硕士"] : ["本科", "硕士"]);
});

test("放行未标注不等于蒙混：countUnlabeledInMatch 报出其中有多少条是靠放行进来的", () => {
  const jobs = [
    { title: "2027届校园招聘-后端开发工程师", city: "北京", education: "本科", grad_class: 2027 },
    { title: "校园招聘-后端开发工程师", city: "北京", education: "本科", grad_class: null },
    { title: "校园招聘-后端开发工程师", city: "北京", education: "本科", grad_class: null },
  ];
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  const facets = byPattern.get("%x%");
  const sel = (f) => selectFacetIndexes({ city: "", education: "", jobFunction: "", gradClass: null, ...f }, options);

  assert.equal(countMatchingFacets(facets, sel({ gradClass: 2027 })), 3);
  assert.equal(countUnlabeledInMatch(facets, sel({ gradClass: 2027 })), 2, "其中 2 条届别未标注");
  // 没筛会产生未标注的维度时恒为 0
  assert.equal(countUnlabeledInMatch(facets, sel({})), 0);
  assert.equal(countUnlabeledInMatch(facets, sel({ jobFunction: "研发" })), 0, "职能不参与未标注放行");
});

test("职能仍是硬相等：「其他」是分类结果不是未知，不该被当成未标注放行", () => {
  const jobs = [
    { title: "2027届校园招聘-后端开发工程师", city: "北京", education: "本科", grad_class: 2027 },
    { title: "2027届校园招聘-董事长助理", city: "北京", education: "本科", grad_class: 2027 },
  ];
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  const facets = byPattern.get("%x%");
  // 两条岗的职能不同；任选其一都只该命中一条，绝不能因为「另一条判成其他」就一并放行
  for (const fn of options.functionOptions) {
    const sel = selectFacetIndexes({ city: "", education: "", jobFunction: fn, gradClass: null }, options);
    assert.equal(countMatchingFacets(facets, sel), 1, `职能=${fn} 应只命中 1 条`);
  }
});

test("展开区的整行匹配与分面计数同口径（否则卡面写 N 个、展开却是另一批）", () => {
  const jobs = makeJobs(150);
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  // 展开接口返回的是完整行 + 服务端算好的 fn；这里照那个形状构造。
  const rows = jobs.map((j) => ({ ...j, fn: campusFacetKey(j).fn }));

  for (const filters of allFilterCombos(options).slice(0, 200)) {
    const sel = selectFacetIndexes(filters, options);
    const byFacet = countMatchingFacets(byPattern.get("%x%"), sel);
    const byRow = rows.filter((r) => campusRowMatches(r, filters)).length;
    assert.equal(byRow, byFacet, `filters=${JSON.stringify(filters)}`);
  }
});
