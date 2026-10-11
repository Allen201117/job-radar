const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

// insight-derive 运行时 import 了岗位库的职能分类器（./china-keyword-expansion），
// 要用会按源文件所在目录解析相对 import 的加载器。
const DERIVE_PATH = path.join(__dirname, "..", "lib", "insight-derive.ts");
const D = loadTs(DERIVE_PATH);
const { classifyJobFunction } = require("../lib/china-keyword-expansion.js");

const NOW = new Date("2026-06-15T00:00:00.000Z");
const NOW_ISO = NOW.toISOString();

// 构造一行最小 Job（按 lib/types.ts Job 形状），用 over 覆盖关心的字段
function j(over = {}) {
  return {
    id: "x", source_id: null, company: "测试公司", title: "工程师",
    location: "北京", job_type: "社招", summary: null, jd_url: "https://e.com/1",
    apply_url: null, salary_text: null, posted_at: null, experience: null,
    education: null, deadline: null, first_seen_at: "2026-06-01T00:00:00.000Z",
    last_seen_at: "2026-06-01T00:00:00.000Z", status: "active",
    content_hash: null, created_at: "2026-06-01T00:00:00.000Z", ...over,
  };
}

test("bucketExperience 归桶：覆盖中文常见表述 + 边界", () => {
  assert.equal(D.bucketExperience("经验不限"), "不限");
  assert.equal(D.bucketExperience("不要求工作经验"), "不限");
  assert.equal(D.bucketExperience("应届毕业生"), "应届");
  assert.equal(D.bucketExperience("1-3年工作经验"), "1-3年");
  assert.equal(D.bucketExperience("3-5年"), "3-5年");
  assert.equal(D.bucketExperience("5-10年工作经验"), "5-10年");
  assert.equal(D.bucketExperience("10年以上"), "10年+");
  assert.equal(D.bucketExperience("5年以上"), "3-5年");
  assert.equal(D.bucketExperience("3年以上"), "1-3年");
  assert.equal(D.bucketExperience(null), null);
  assert.equal(D.bucketExperience(""), null);
});

test("bucketEducation 归桶：覆盖中文常见表述", () => {
  assert.equal(D.bucketEducation("不限学历"), "不限");
  assert.equal(D.bucketEducation("博士及以上"), "博士");
  assert.equal(D.bucketEducation("硕士研究生"), "硕士");
  assert.equal(D.bucketEducation("本科及以上"), "本科");
  assert.equal(D.bucketEducation("大专"), "大专");
  assert.equal(D.bucketEducation(null), null);
  assert.equal(D.bucketEducation(""), null);
});

test("classifyRecruitment 按关键词归三桶（保守：无明确关键词 = unknown）", () => {
  assert.equal(D.classifyRecruitment("实习", "数据分析实习生"), "intern");
  assert.equal(D.classifyRecruitment("校招", "2026届校园招聘-后端"), "campus");
  assert.equal(D.classifyRecruitment("应届", "应届生-算法"), "campus");
  assert.equal(D.classifyRecruitment("社招", "高级后端工程师"), "social");
  assert.equal(D.classifyRecruitment(null, "Software Engineer Intern"), "intern");
  assert.equal(D.classifyRecruitment(null, "资深产品经理"), "unknown");
});

// 回归（2026-10-11）：旧正则 /实习|intern|internship/ 是裸子串，Internal / International / Internals
// 全算实习 —— 进了抽屉的「类型」占比与「实习集中在 X 月」。用例全部取自库里 / live 抓到的真实标题。
test("classifyRecruitment：intern 只认整词，Internal / International / Internals 不是实习", () => {
  for (const title of [
    "Senior Analyst - Internal Audit",
    "Software Developer - Internal Compute Frameworks (Python)",
    "Principal Software Engineer - Query Engine, Database Internals - Elasticsearch",
    "Internal Auditor - APAC Regulatory & Financial Operations",
    "Warehouse and Logistics Manager - International",
    "International Legal Counsel",
    "Senior Manager, International Marketing, Migraine Prevention",
    "Product Designer, Internal Tools",
    "Network Development Engineer II, AWS Internet Edge",
    "Internal", // 大陆集团真有岗位标题就叫这个
  ]) {
    assert.notEqual(D.classifyRecruitment(null, title), "intern", title);
  }
  // 不是实习之后要落到它真正的桶，而不是一律 unknown：这条靠 Graduate 判校招。
  assert.equal(
    D.classifyRecruitment(null, "Internal Control Business Partner Graduate (Internal Control) - 2027 Start"),
    "campus",
  );
  // job_type 同一条规则：部门 / 类别名里的 Internal 不是实习（西门子的 job_type 就叫 Internal Services）。
  assert.notEqual(D.classifyRecruitment("Internal Services", "(SSLS) GA Specialist 总务专员 闵行"), "intern");
});

// 反方向：收紧之后真实习一个都不许漏（单复数 / internship / 贴着汉字、标点的写法）。
test("classifyRecruitment：整词收紧后真实习写法照旧判实习", () => {
  for (const title of [
    "IATD AE Lab Testing Summer Intern",
    "Machine Learning Researcher - Intern",
    "Internship",
    "Engineering Summer Interns 2027",
    "Boeing Summer 2027 Internship Program (Paid)",
    "Business, Marketing & Creative Masters Internships",
    "商务intern", // 贴着汉字：JS 的 \b 认，这类岗不能丢
    "后端开发工程师（TripoStudio核心Intern）",
    "数据分析实习生",
    "Internal Audit Intern", // 构造：两个词同时出现时以整词 Intern 为准
  ]) {
    assert.equal(D.classifyRecruitment(null, title), "intern", title);
  }
  // job_type 自报（库里含 intern 的 job_type 只有 Intern 与 Internal Services 两种取值）
  assert.equal(D.classifyRecruitment("Intern", "Data Analyst"), "intern");
  assert.equal(D.classifyRecruitment("项目实习", "Project Intern_Compliance team(J19369)"), "intern");
  // 已知边界：下划线 / 数字在正则里算词字符，Intern_Compliance、Intern3D 单看标题不认（上一行靠的是 job_type 的「实习」）。
  // 与岗位库的整词正则是同一个边界；全库这种写法 3 行，都另写了「实习」二字。要放宽就两处一起放。
  assert.equal(D.classifyRecruitment(null, "Project Intern_Compliance team(J19369)"), "unknown");
});

// 判实习的整词正则在岗位库（china-keyword-expansion）里也有一份。两处各改各的 = 抽屉与岗位库筛选对同一个岗说法不同。
test("实习整词正则与岗位库是同一条", () => {
  const WORD = String.raw`\bintern(?:ship)?s?\b`;
  assert.ok(fs.readFileSync(DERIVE_PATH, "utf8").includes(`/实习|${WORD}/`), "insight-derive 的实习正则变了");
  const lib = fs.readFileSync(path.join(__dirname, "..", "lib", "china-keyword-expansion.js"), "utf8");
  assert.ok(lib.includes(`/实习|${WORD}/i`), "岗位库 sourceDeclaredCategory 的实习正则变了，这里要跟着核一遍");
});

test("deriveHiring：标题里的 Internal / International 不得进「实习」占比", () => {
  const jobs = [
    j({ job_type: null, title: "Senior Analyst - Internal Audit" }),
    j({ job_type: null, title: "International Legal Counsel" }),
    j({ job_type: null, title: "Senior Software Engineer - Database Engine Internals" }),
    j({ job_type: "社招", title: "后端工程师" }),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.equal(v.payload.mix.intern, 0);
  assert.equal(v.payload.bucket_share.intern, 0);
  assert.equal(v.payload.bucket_share.social, 100);
});

// ── 三桶认岗位库那一列（2026-10-11 创始人选定：兜底社招不计入） ──────────────────────────────
// 列的两个字段：recruitment_category（社招 / 校招 / 实习，没算出来是 null）、recruitment_explicit（有没有明确依据）。
const col = (cat, explicit, over = {}) => j({ recruitment_category: cat, recruitment_explicit: explicit, ...over });

test("recruitBucket：列判校招 / 实习就照列，哪怕 job_type 和标题里一个关键词都没有", () => {
  // 靠校招门户 url 判出来的校招：读时派生取不到 url，关键词判法只能给 unknown
  const campus = col("校招", true, { job_type: null, title: "硬件工程师" });
  assert.equal(D.classifyRecruitment(campus.job_type, campus.title), "unknown");
  assert.equal(D.recruitBucket(campus), "campus");
  // 按来源频道标注的实习
  assert.equal(D.recruitBucket(col("实习", true, { job_type: "市场营销类", title: "海外电商运营" })), "intern");
});

test("recruitBucket：列判社招且有依据 → 社招，来源把它标成校招 / 实习也不改", () => {
  // 来源标校招、正文写了年限，岗位库的经验门判成社招
  const labelled = col("社招", true, { job_type: "校招", title: "高级机械工程师" });
  assert.equal(D.classifyRecruitment(labelled.job_type, labelled.title), "campus");
  assert.equal(D.recruitBucket(labelled), "social");
  // 实习频道里挂的蓝领社招岗
  assert.equal(D.recruitBucket(col("社招", true, { job_type: "操作职系 实习", title: "电工" })), "social");
  // job_type 填的是职能：没有任何关键词，但列有依据
  assert.equal(D.recruitBucket(col("社招", true, { job_type: "直营事业部", title: "销售顾问" })), "social");
});

test("recruitBucket：兜底社招（列判社招但没有依据）记 unknown，不回头看关键词", () => {
  assert.equal(D.recruitBucket(col("社招", false, { job_type: null, title: "Store Team Member" })), "unknown");
  // 标题里有 Graduate / Professional 这类关键词也一样：列已经判过，这里不再另判一遍
  assert.equal(D.recruitBucket(col("社招", false, { job_type: null, title: "Graduate Analyst 2027" })), "unknown");
  assert.equal(D.recruitBucket(col("社招", false, { job_type: null, title: "Professional Services Lead" })), "unknown");
  // 只认明确的 true：依据那一列缺失 / 为 null 时不当成有依据
  assert.equal(D.recruitBucket(col("社招", null, { job_type: null, title: "销售顾问" })), "unknown");
  assert.equal(D.recruitBucket(j({ recruitment_category: "社招", job_type: null, title: "销售顾问" })), "unknown");
});

test("recruitBucket：列还没算出来（null / 没取到 / 值域外）退回关键词判法", () => {
  for (const cat of [null, undefined, "", "全职"]) {
    assert.equal(D.recruitBucket(col(cat, null, { job_type: null, title: "数据分析实习生" })), "intern", String(cat));
    assert.equal(D.recruitBucket(col(cat, null, { job_type: "校园招聘", title: "后端工程师" })), "campus", String(cat));
    assert.equal(D.recruitBucket(col(cat, null, { job_type: "社招", title: "后端工程师" })), "social", String(cat));
    assert.equal(D.recruitBucket(col(cat, null, { job_type: null, title: "资深产品经理" })), "unknown", String(cat));
    // 退路里的整词规则照旧
    assert.equal(D.recruitBucket(col(cat, null, { job_type: null, title: "International Legal Counsel" })), "unknown", String(cat));
  }
});

test("deriveHiring：占比只在「列判得出」的岗里算，兜底社招不进分母", () => {
  const jobs = [
    ...Array.from({ length: 2 }, () => col("校招", true, { job_type: null, title: "硬件工程师" })),
    ...Array.from({ length: 6 }, () => col("社招", true, { job_type: "直营事业部", title: "销售顾问" })),
    ...Array.from({ length: 12 }, () => col("社招", false, { job_type: null, title: "Store Team Member" })),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.deepEqual(v.payload.mix, { campus: 2, intern: 0, social: 6, unknown: 12 });
  assert.deepEqual(v.payload.bucket_share, { campus: 25, intern: 0, social: 75 });
  // 在招总数不受影响：兜底社招照样是在招岗
  assert.equal(v.payload.active_count, 20);
});

test("deriveHiring：来源整批标成校招、列判社招的公司，不再写成「校招 100%」", () => {
  const jobs = [
    ...Array.from({ length: 9 }, () => col("社招", true, { job_type: "校招", title: "高级电气工程师" })),
    col("校招", true, { job_type: "校招", title: "2027届校园招聘-研发" }),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.deepEqual(v.payload.bucket_share, { campus: 10, intern: 0, social: 90 });
});

test("deriveHiring：全是兜底社招时不输出占比（没有一个岗判得出）", () => {
  const jobs = Array.from({ length: 5 }, () => col("社招", false, { job_type: null, title: "Store Team Member" }));
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.equal(v.payload.mix.unknown, 5);
  assert.equal(v.payload.bucket_share, undefined);
});

test("deriveTiming 与占比用同一个三桶：认列，兜底社招的月份不算", () => {
  const months = ["01", "02", "03", "04", "05", "06", "07", "08"];
  const jobs = [
    // 列判校招、关键词判不出
    ...["09", "09", "09", "10"].map((m) => col("校招", true, { job_type: null, title: "硬件工程师", posted_at: `2026-${m}-05T00:00:00Z` })),
    // 兜底社招铺满 8 个月：要是算进去就是「社招全年滚动」
    ...months.map((m) => col("社招", false, { job_type: null, title: "Store Team Member", posted_at: `2026-${m}-05T00:00:00Z` })),
  ];
  const v = D.deriveTiming(jobs, NOW_ISO);
  assert.match(v.content, /校招集中在 9、10 月/);
  assert.doesNotMatch(v.content, /社招/);
  // 换成有依据的社招，同样的月份就该出「全年滚动」
  const explicit = jobs.map((jb) => (jb.recruitment_explicit === false ? { ...jb, recruitment_explicit: true } : jb));
  assert.match(D.deriveTiming(explicit, NOW_ISO).content, /社招全年滚动/);
});

test("占比与招聘节奏都经 recruitBucket，没有哪一处还直接用关键词判法", () => {
  const src = fs.readFileSync(DERIVE_PATH, "utf8");
  const body = (name) => {
    const start = src.indexOf(`export function ${name}(`);
    assert.ok(start >= 0, "找不到 " + name);
    return src.slice(start, src.indexOf("\n}\n", start));
  };
  for (const name of ["deriveHiring", "deriveTiming"]) {
    assert.match(body(name), /recruitBucket\(jb\)/, name);
    assert.equal(body(name).includes("classifyRecruitment("), false, name + " 里还在直接调关键词判法");
  }
  // 关键词判法只剩 recruitBucket 这一个调用方（定义 1 处 + 调用 1 处）
  assert.equal(src.match(/classifyRecruitment\(/g).length, 2);
});

test("parseSalaryText 只解析明示月薪区间；歧义/无值返回 null", () => {
  assert.deepEqual(D.parseSalaryText("15-30K"), { minK: 15, maxK: 30 });
  assert.deepEqual(D.parseSalaryText("15k-30k"), { minK: 15, maxK: 30 });
  assert.deepEqual(D.parseSalaryText("20-40千/月"), { minK: 20, maxK: 40 });
  assert.deepEqual(D.parseSalaryText("15000-30000"), { minK: 15, maxK: 30 });
  assert.equal(D.parseSalaryText("面议"), null);
  assert.equal(D.parseSalaryText("官网未披露"), null);
  assert.equal(D.parseSalaryText(null), null);
  assert.equal(D.parseSalaryText("15-30万"), null); // 年/月歧义，保守跳过
});

test("deriveSalaryBand 聚合明示薪资（>=5 才出，否则 null）", () => {
  const jobs = [
    j({ salary_text: "15-25K" }), j({ salary_text: "20-30K" }),
    j({ salary_text: "18-28K" }), j({ salary_text: "25-35K" }),
    j({ salary_text: "面议" }), j({ salary_text: "22000-32000" }),
  ];
  const v = D.deriveSalaryBand(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "compensation_intensity");
  assert.equal(v.grade, "fact");
  assert.equal(v.derived, true);
  assert.equal(v.payload.sample, 5);
  assert.match(v.content, /K/);
});

test("deriveSalaryBand 不足阈值返回 null", () => {
  assert.equal(D.deriveSalaryBand([j({ salary_text: "15-25K" })], NOW_ISO), null);
});

test("deriveTiming 概括校招峰值月 + 社招全年滚动", () => {
  const jobs = [
    j({ job_type: "校招", posted_at: "2026-08-05T00:00:00Z" }),
    j({ job_type: "校招", posted_at: "2026-09-05T00:00:00Z" }),
    j({ job_type: "校招", posted_at: "2026-08-20T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-01-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-03-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-04-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-07-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-10-05T00:00:00Z" }),
    j({ job_type: "社招", posted_at: "2026-12-05T00:00:00Z" }),
  ];
  const v = D.deriveTiming(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "timing");
  assert.match(v.content, /校招集中在 8、9 月/);
  assert.match(v.content, /社招全年滚动/);
});

test("deriveTiming 不足阈值返回 null", () => {
  assert.equal(D.deriveTiming([j({ posted_at: "2026-08-01T00:00:00Z" })], NOW_ISO), null);
});

test("deriveHiring 概括在招规模/城市/方向（排除非 active）", () => {
  const jobs = [
    j({ status: "active", location: "北京", title: "后端工程师" }),
    j({ status: "active", location: "北京·海淀", title: "前端工程师" }),
    j({ status: "active", location: "上海", title: "产品经理" }),
    j({ status: "expired", location: "深圳", title: "测试" }),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "hiring");
  assert.equal(v.derived, true);
  assert.equal(v.payload.active_count, 3);
  assert.match(v.content, /本平台当前收录 3 个在招岗位/);
  assert.match(v.content, /北京/);
});

// 调用方只取前 N 行做样本、且取满了：N 是取数上限，不是这家公司的在招岗位数。
// 现象（2026-10-10 走查）：字节跳动在招 2 万多个，抽屉里写「本平台当前收录 3000 个在招岗位」。
test("deriveHiring：样本取满上限时写「N+」并说明是按样本统计", () => {
  const jobs = [
    j({ status: "active", location: "北京", title: "后端工程师" }),
    j({ status: "active", location: "北京·海淀", title: "前端工程师" }),
    j({ status: "active", location: "上海", title: "产品经理" }),
  ];
  const capped = D.deriveHiring(jobs, NOW_ISO, { sampleCapped: true });
  assert.match(capped.content, /本平台当前收录 3\+ 个在招岗位（以下按其中 3 个统计）/);
  // 反方向：没取满时一个字都不许多
  const exact = D.deriveHiring(jobs, NOW_ISO, { sampleCapped: false });
  assert.match(exact.content, /本平台当前收录 3 个在招岗位，/);
  assert.equal(/\+ 个在招岗位/.test(exact.content), false);
  // 聚合入口要把这个开关传下去
  const all = D.deriveCompanyInsights(jobs, new Date(NOW_ISO), { sampleCapped: true });
  assert.match(all.hiring[0].content, /3\+ 个在招岗位/);
});

// 「热门方向」此前用本文件私有的 8 条正则、按顺序取第一个命中：`\bai\b` 排最前、「工程师」算研发。
// 2026-10-11 全库 441,589 个在招岗对拍：AI产品经理算成算法（2,608）、机械 / 电气工程师算成研发（21,395）、
// 销售工程师算成研发（1,209）、一半的岗（217,781）判不出方向；1,445 家公司里 679 家的第一方向因此不同。
// 现在与洞察库的职能分布、岗位库筛选共用同一个分类器。
test("deriveHiring 热门方向：按岗位名判，不被 AI / 工程师 这类词带偏", () => {
  const titles = [
    "AI产品经理", "AI产品经理-抖音电商", "产品经理",
    "产品运营", "产品运营经理",
    "机械工程师", "高级机械工程师",
    "销售工程师",
  ];
  const v = D.deriveHiring(titles.map((title) => j({ title })), NOW_ISO);
  assert.deepEqual(v.payload.top_functions, [
    { key: "产品", count: 3 },
    { key: "生产制造", count: 2 },
    { key: "运营", count: 2 },
  ]);
  assert.match(v.content, /热门方向 产品、生产制造、运营/);
});

// 「岗位名 - 业务线」按岗位名判，尾巴里的词不算数（爬虫 2026-10-11 起入库保留「 - 」后面的内容）。
// 旧规则的两种错法：`\bai\b` 排最前 →「产品经理 - AI平台」算成算法；「研发」排在运营前 →「增长运营 - 研发效能」算成研发。
// 第三种是换成分类器之后要防的：分类器对不分段的标题取「最靠后命中」，尾巴「用户增长」会把研发岗带成运营，
// 靠它的「分段标题先看第一段」挡住（规则本身的用例在 tests/classify-job-function.test.js）。
test("deriveHiring 热门方向：「岗位名 - 业务线」按岗位名判", () => {
  const jobs = [
    j({ title: "产品经理 - AI平台" }),
    j({ title: "增长运营 - 研发效能" }),
    j({ title: "增长运营 - 研发效能" }),
    j({ title: "Agent研发工程师 - 抖音用户增长" }),
    j({ title: "Software Engineer - Growth" }),
    j({ title: "Software Engineer - Growth" }),
  ];
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.deepEqual(v.payload.top_functions, [
    { key: "研发", count: 3 },
    { key: "运营", count: 2 },
    { key: "产品", count: 1 },
  ]);
});

// 契约：洞察派生不许再有自己的职能词表。岗位库的分类器怎么判，这里就怎么数
// （判不出 =「其他」不进热门方向）。期望值故意用分类器现算：它改规则，这里自动跟上，抽屉不另判一遍。
test("deriveHiring 热门方向 = 岗位库分类器逐岗判完后的前三名", () => {
  const titles = [
    "后端工程师", "Senior Sales Engineer", "客户经理", "柜员", "结构工程师", "算法工程师",
    "Machine Learning Engineer", "财务分析", "Agent研发工程师 - 抖音用户增长", "Software Engineer - Growth",
    "置业顾问", "2027届管培生", "Internal Auditor - APAC Regulatory & Financial Operations",
  ];
  const counts = new Map();
  for (const title of titles) {
    const fn = classifyJobFunction({ title });
    if (fn !== "其他") counts.set(fn, (counts.get(fn) || 0) + 1);
  }
  assert.ok(counts.size >= 4, "用例退化了：要有被挤出前三的方向，才验得出「取的是前三名」");
  const expected = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .slice(0, 3)
    .map(([key, count]) => ({ key, count }));
  const v = D.deriveHiring(titles.map((title) => j({ title })), NOW_ISO);
  assert.deepEqual(v.payload.top_functions, expected);
});

// 并列时谁排前、谁被挤出前三，不许看行的先后：线上取数没有 order by，行序 = 堆物理顺序，
// 岗位一被改写就变 —— 同一家公司刷新两次，「热门方向」「主要城市」的第三名会换人。
test("deriveHiring 热门方向 / 城市：并列时结果与行的先后无关", () => {
  const rows = [
    j({ title: "产品经理", location: "杭州" }),
    j({ title: "后端工程师", location: "北京" }),
    j({ title: "销售工程师", location: "上海" }),
    j({ title: "柜员", location: "成都" }),
  ];
  const a = D.deriveHiring(rows, NOW_ISO).payload;
  const b = D.deriveHiring([...rows].reverse(), NOW_ISO).payload;
  assert.deepEqual(a.top_functions, b.top_functions);
  assert.deepEqual(a.top_cities, b.top_cities);
  // 并列按名称的码点升序定序（不用 localeCompare：它随运行环境的 ICU 版本变）。
  assert.deepEqual(a.top_functions.map((f) => f.key), ["产品", "研发", "金融业务"]);
  assert.deepEqual(a.top_cities.map((c) => c.key), ["上海", "北京", "成都"]);
});

test("deriveHiring 不足阈值返回 null", () => {
  assert.equal(D.deriveHiring([j(), j()], NOW_ISO), null);
});

// ---- 招聘大小年 / HC 强度信号 ----
test("classifyHiringSignal 趋势分级 expanding/steady/tightening", () => {
  assert.equal(D.classifyHiringSignal(100, 30).momentum, "expanding");
  assert.equal(D.classifyHiringSignal(100, -30).momentum, "tightening");
  assert.equal(D.classifyHiringSignal(100, 5).momentum, "steady");
  // F4：无趋势 → unknown，**不许**退化成「平稳」。「平稳」是有内容的结论，说它需要基线。
  assert.equal(D.classifyHiringSignal(100, null).momentum, "unknown");
});

test("classifyHiringSignal 相对规模强度（需 headcountBand）", () => {
  assert.equal(D.classifyHiringSignal(200, 0, "5000-1万").intensity, "high"); // ≈0.027
  assert.equal(D.classifyHiringSignal(50, 0, "5000-1万").intensity, "mid"); // ≈0.0067
  assert.equal(D.classifyHiringSignal(20, 0, "5000-1万").intensity, "low"); // ≈0.0027
  assert.equal(D.classifyHiringSignal(200, 0).intensity, undefined); // 无规模档→不给强度
  assert.equal(D.classifyHiringSignal(200, 0, "未知档").intensity, undefined);
});

test("deriveHiring payload 含 experience_dist/education_dist/bucket_share/open_age_days_median（样本足够时）", () => {
  // 构造 10 个有 experience + education 字段的岗，触发分布输出
  const jobs = Array.from({ length: 12 }, (_, i) =>
    j({
      status: "active",
      experience: i < 6 ? "3-5年" : "1-3年",
      education: i < 8 ? "本科及以上" : "硕士研究生",
      job_type: i < 4 ? "校招" : "社招",
      first_seen_at: `2026-05-${String(i + 1).padStart(2, "0")}T00:00:00Z`,
    }),
  );
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.ok(v, "应有 hiring 洞察");
  const p = v.payload;
  // 经验分布
  assert.ok(p.experience_dist, "应有 experience_dist");
  assert.ok(typeof p.experience_dist["3-5年"] === "number", "3-5年桶有值");
  // 学历分布
  assert.ok(p.education_dist, "应有 education_dist");
  assert.ok(typeof p.education_dist["本科"] === "number", "本科桶有值");
  // 占比
  assert.ok(p.bucket_share, "应有 bucket_share");
  assert.ok(typeof p.bucket_share.social === "number");
  // 在架时长
  assert.ok(typeof p.open_age_days_median === "number", "应有 open_age_days_median");
  assert.ok(p.open_age_days_median > 0);
});

test("deriveHiring payload 样本不足时不输出 experience_dist/education_dist", () => {
  // 只有 3 个岗且无 experience/education，不触发分布
  const jobs = [1, 2, 3].map(() => j({ status: "active", experience: null, education: null }));
  const v = D.deriveHiring(jobs, NOW_ISO);
  assert.ok(v, "应有 hiring 洞察（count≥3）");
  assert.equal(v.payload.experience_dist, undefined);
  assert.equal(v.payload.education_dist, undefined);
});

test("deriveHiring 带 hiring_signal + 信号写进正文", () => {
  const jobs = [1, 2, 3, 4, 5, 6, 7, 8].map(() => j({ status: "active" }));
  const v = D.deriveHiring(jobs, NOW_ISO, { headcountBand: "5000-1万" });
  assert.ok(v.payload.hiring_signal, "payload 带 hiring_signal");
  assert.equal(typeof v.payload.hiring_signal.momentum, "string");
  assert.match(v.content, /招聘信号/);
});

test("deriveCompanyInsights 只返回算得出的维度", () => {
  const jobs = [1, 2, 3, 4, 5, 6].map((i) =>
    j({ status: "active", salary_text: "15-25K", job_type: "社招", title: "后端工程师",
        location: "北京", posted_at: `2026-0${i}-05T00:00:00Z` }),
  );
  const out = D.deriveCompanyInsights(jobs, NOW);
  assert.ok(out.compensation_intensity, "应有薪资带");
  assert.ok(out.hiring, "应有招聘动态");
  assert.ok(out.timing, "社招覆盖 1–6 月（6 个不同月）→ 全年滚动");
  assert.equal(out.compensation_intensity[0].derived, true);
});

test("deriveCompanyInsights 空数据返回空对象", () => {
  assert.deepEqual(D.deriveCompanyInsights([], NOW), {});
});

// ---- F4 回归：幸存者偏差不得再造出「招聘扩张」 ----
test("只关闭旧岗、一个新岗都没发，不得算出扩张（F4 回归）", () => {
  // 复刻审查反例：两个 30 天窗口各真实发布 30 个岗（真实趋势 0%），
  // 然后把旧窗关掉 27 个。旧实现只看当前 active，算出 +900% 扩张并推出「HC 较充足」。
  const nowMs = new Date(NOW_ISO).getTime();
  const D30 = 30 * 86400000;
  const jobs = [];
  for (let i = 0; i < 30; i++) {
    jobs.push(j({ status: "active", first_seen_at: new Date(nowMs - D30 / 2).toISOString() }));
  }
  for (let i = 0; i < 3; i++) {
    jobs.push(j({ status: "active", first_seen_at: new Date(nowMs - D30 * 1.5).toISOString() }));
  }
  const v = D.deriveHiring(jobs, NOW_ISO, { headcountBand: "5000-1万" });
  assert.ok(v);
  assert.equal(v.payload.hiring_signal.trend, null, "读时派生不得自产趋势");
  assert.equal(v.payload.hiring_signal.momentum, "unknown");
  assert.doesNotMatch(v.content, /扩张|增加/, "不得宣称扩张");
  assert.doesNotMatch(v.content, /HC|窗口|竞争/, "不得从岗位条数外推 HC/投递窗口/竞争强度");
});

test("趋势只接受外部快照注入（F4 回归）", () => {
  const jobs = [j({ status: "active" }), j({ status: "active" }), j({ status: "active" })];
  const injected = D.deriveHiring(jobs, NOW_ISO, { trendPct: 40 });
  assert.equal(injected.payload.hiring_signal.trend, 40);
  assert.equal(injected.payload.hiring_signal.momentum, "expanding");
  // 措辞必须限定在「本平台收录」范围内，不能说成企业行为
  assert.match(injected.content, /本平台收录的在招岗位数近月明显增加/);
});
