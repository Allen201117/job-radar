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
// 全算实习 —— 进了抽屉的「类型」占比与当时的「实习集中在 X 月」（后一句同日已不再写，见下方「招聘节奏」一组）。
// 用例全部取自库里 / live 抓到的真实标题。
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
  // 发布日都落在 NOW（2026-06-15）往前 12 个月内：招聘节奏只看这一段（见下方「招聘节奏」一组用例）
  const months = ["2025-07", "2025-08", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"];
  const jobs = [
    // 列判校招、关键词判不出
    ...["09", "09", "09", "10"].map((m) => col("校招", true, { job_type: null, title: "硬件工程师", posted_at: `2025-${m}-05T00:00:00Z` })),
    // 兜底社招铺满 8 个月：要是算进去就是「社招全年滚动」
    ...months.map((ym) => col("社招", false, { job_type: null, title: "Store Team Member", posted_at: `${ym}-05T00:00:00Z` })),
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
  // 真正的计算在 hiringOf / timingOf 里（deriveHiring / deriveTiming 只是把岗位行转成分面再交给它们）
  const body = (name) => {
    const start = src.indexOf(`\nfunction ${name}(`);
    assert.ok(start >= 0, "找不到 " + name);
    return src.slice(start, src.indexOf("\n}\n", start));
  };
  for (const name of ["hiringOf", "timingOf"]) {
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

// ── 招聘节奏（2026-10-11 创始人选定：只认公司写的发布日 + 近 12 个月；社招 / 实习不写「集中在某月」）──
// NOW = 2026-06-15，所以「近 12 个月」= 2025-06-15 ~ 2026-06-15。
const posted = (jobType, ymd, over = {}) => j({ job_type: jobType, posted_at: `${ymd}T04:00:00Z`, ...over });
const timingText = (jobs) => {
  const v = D.deriveTiming(jobs, NOW_ISO);
  return v ? v.content : null;
};

test("deriveTiming 概括校招峰值月 + 社招全年滚动", () => {
  const jobs = [
    posted("校招", "2025-08-05"), posted("校招", "2025-09-05"), posted("校招", "2025-08-20"),
    ...["2025-07", "2025-10", "2025-12", "2026-01", "2026-03", "2026-04"].map((ym) => posted("社招", `${ym}-05`)),
  ];
  const v = D.deriveTiming(jobs, NOW_ISO);
  assert.ok(v);
  assert.equal(v.dimension, "timing");
  assert.match(v.content, /校招集中在 8、9 月/);
  assert.match(v.content, /社招全年滚动/);
});

test("deriveTiming 不足阈值返回 null", () => {
  assert.equal(D.deriveTiming([posted("校招", "2025-08-01")], NOW_ISO), null);
});

test("招聘节奏：没有发布日的岗不参与，不拿我们第一次抓到它的日子充数", () => {
  // 2026-10-11 全库 441,074 个在招岗里 250,773 个没有发布日；旧实现退回 first_seen_at，而我们最早的抓取记录是
  // 2026-06-14 —— 这些岗的月份只可能是 6~10 月，写出来的是「我们哪个月接入 / 抓到的」。
  const crawlOnly = Array.from({ length: 8 }, (_, i) =>
    j({ job_type: "校招", posted_at: null, first_seen_at: `2026-0${(i % 2) + 4}-10T00:00:00Z` }));
  assert.equal(timingText(crawlOnly), null, "8 个校招岗全没有发布日 → 不出卡");
  // 混进带发布日的：只按带发布日的那几个算，首抓月份（4、5 月）不得出现
  const mixed = [...crawlOnly.slice(0, 2), ...Array.from({ length: 5 }, () => posted("校招", "2025-09-03"))];
  assert.match(timingText(mixed), /校招集中在 9 月/);
  assert.doesNotMatch(timingText(mixed), /[45] 月|、/);
});

test("招聘节奏：社招、实习不写「集中在某月」（幸存者偏差回归）", () => {
  // 已关闭的岗每天被物理删除，能读到的只有还在招的 → 越早的月份剩得越少，「峰值月」只是在复述最近挂出的岗多。
  // 同日实测：有这句话的 593 家里 566 家峰值月全在 6~10 月；同一批岗换成我们的首抓日再写一遍，句子一样的只有 24%。
  const social = ["2026-04-02", "2026-04-09", "2026-05-06", "2026-05-13", "2026-05-20", "2026-05-27"].map((d) => posted("社招", d));
  assert.equal(timingText(social), null, "社招只有 4、5 两个月 → 不写「集中在 4、5 月」，也没有别的可写");
  const intern = ["2026-03-02", "2026-03-09", "2026-03-16", "2026-04-06", "2026-04-13"].map((d) => posted("实习", d));
  assert.equal(timingText(intern), null, "实习不写「集中在某月」");
  // 有校招段时卡照出，但里面不带社招 / 实习的「集中」
  const withCampus = [...social, ...intern, ...Array.from({ length: 4 }, () => posted("校招", "2025-09-10"))];
  assert.match(timingText(withCampus), /校招集中在 9 月/);
  assert.doesNotMatch(timingText(withCampus), /社招|实习/);
});

test("招聘节奏：实习铺满全年也不写（只有社招有「全年滚动」）", () => {
  const intern = ["2025-07", "2025-08", "2025-10", "2025-12", "2026-02", "2026-04"].map((ym) => posted("实习", `${ym}-08`));
  assert.equal(timingText(intern), null);
});

test("招聘节奏：只看近 12 个月发布的岗，更早的不算月份也不算「滚动」", () => {
  // 万达：61 个校招岗里 46 个是 2023 年发的，旧实现不分年份照样算进「9、11 月」。
  const stale = [
    ...Array.from({ length: 5 }, () => posted("校招", "2023-11-05")),
    ...Array.from({ length: 5 }, () => posted("校招", "2025-09-05")),
    posted("校招", "2025-10-05"),
  ];
  assert.match(timingText(stale), /校招集中在 9、10 月/);
  assert.doesNotMatch(timingText(stale), /11/);
  // 「全年滚动」要的是近 12 个月里的 6 个不同月份：3 个近的 + 3 个两年前的不算（每月 2 个岗，样本够数）
  const rolling = (yms) => timingText(yms.flatMap((ym) => [posted("社招", `${ym}-05`), posted("社招", `${ym}-20`)]));
  assert.equal(rolling(["2026-01", "2026-02", "2026-03", "2024-04", "2024-05", "2024-06"]), null);
  assert.match(rolling(["2026-01", "2026-02", "2026-03", "2025-10", "2025-11", "2025-12"]), /社招全年滚动/);
  // 窗口两端：正好 365 天前的算，再早一天不算；写在未来的发布日不算
  const edge = (iso) => D.deriveTiming(Array.from({ length: 5 }, () => j({ job_type: "校招", posted_at: iso })), NOW_ISO);
  assert.ok(edge("2025-06-15T00:00:00.000Z"));
  assert.equal(edge("2025-06-14T23:59:59.000Z"), null);
  assert.equal(edge("2026-06-16T00:00:00.000Z"), null);
  // 「现在」解析不出来时窗口不能整个失效（那样所有年份的岗都会放行）
  assert.equal(D.deriveTiming(Array.from({ length: 5 }, () => posted("校招", "2023-09-05")), "not-a-date"), null);
});

test("招聘节奏：校招岗里带发布日的不到一半就不写（不挑着算）", () => {
  // 腾讯：451 个校招岗只有 18 个带发布日，按这 18 个写出来会是「集中在 1、7 月」—— 拿一小撮代表全部。
  const dated = (n) => Array.from({ length: n }, () => posted("校招", "2025-08-05"));
  const undated = (n) => Array.from({ length: n }, () => j({ job_type: "校招", posted_at: null }));
  assert.equal(timingText([...dated(5), ...undated(6)]), null, "5/11 不到一半");
  assert.match(timingText([...dated(5), ...undated(5)]), /校招集中在 8 月/, "正好一半就写");
  // 分母是「判成校招的在招岗」，别的桶没发布日不影响它
  const socialUndated = Array.from({ length: 30 }, () => j({ job_type: "社招", posted_at: null }));
  assert.match(timingText([...dated(5), ...socialUndated]), /校招集中在 8 月/);
});

test("招聘节奏：月份按北京时间取（库里的发布日存的是北京零点）", () => {
  // 2026-10-11 实测：带发布日的 190,159 个岗里 183,522 个存成北京零点；其中 4,930 个是当月 1 号 —— 按 UTC 取月份
  // 会把「9 月 1 日发布」算成 8 月，而校招正好爱在 1 号开。
  const sep1 = Array.from({ length: 5 }, () => j({ job_type: "校招", posted_at: "2025-08-31T16:00:00.000Z" }));
  assert.match(timingText(sep1), /校招集中在 9 月/);
});

test("招聘节奏：写出的岗数与样本量 = 撑起这句话的岗，不含没用上的", () => {
  const jobs = [
    ...Array.from({ length: 4 }, () => posted("校招", "2025-09-05")),
    // 下面这些都不进任何一段：实习、判不出类型的、没发布日的、12 个月以前的
    ...Array.from({ length: 3 }, () => posted("实习", "2026-03-05")),
    ...Array.from({ length: 2 }, () => posted(null, "2026-03-05", { title: "Store Team Member" })),
    j({ job_type: "校招", posted_at: null }),
    posted("校招", "2023-09-05"),
  ];
  const v = D.deriveTiming(jobs, NOW_ISO);
  assert.equal(v.content, "据本平台 4 个带发布日期的在招岗位（近 12 个月内发布）：校招集中在 9 月。");
  assert.equal(v.sample_size, 4);
  assert.equal(v.payload.sample_n, 4);
});

test("招聘节奏：整张卡的最低样本数的是带发布日的岗", () => {
  // 4 个带发布日 + 50 个不带：旧实现按 54 个「有日期」放行，现在不够 5 个
  const jobs = [
    ...Array.from({ length: 4 }, () => posted("校招", "2025-09-05")),
    ...Array.from({ length: 50 }, () => j({ job_type: "社招", posted_at: null })),
  ];
  assert.equal(timingText(jobs), null);
});

test("招聘节奏的实现里不再读 first_seen_at，也不再有社招 / 实习的「集中在」", () => {
  const src = fs.readFileSync(DERIVE_PATH, "utf8");
  const start = src.indexOf("\nfunction timingOf(");
  assert.ok(start >= 0, "找不到 timingOf");
  const body = src.slice(start, src.indexOf("\n}\n", start));
  assert.equal(body.includes("first_seen_at"), false, "招聘节奏又在用首次抓取日了");
  assert.equal(body.includes("byFirstSeen"), false, "招聘节奏又在用首次抓取日了");
  assert.equal(/\$\{[^}]*\}集中在/.test(body), false, "「集中在」只许校招一段写死，不许按桶名拼");
  assert.equal((body.match(/集中在/g) || []).length, 1);
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

// 2026-10-11 线上：Target 的抽屉写「主要在 1000、7000、900」——地点列存的是被逗号劈开的门牌地址
// （根因在抓取端，见 crawler/normalizer.strip_street_address 与 workday adapter 的 _post_location）。
// 抓取端修好后地点是「Minneapolis, MN」「Brooklyn Park, MN」「San Diego, CA」，这里要把多词城市整个取出来。
test("deriveHiring 热门城市：西文多词城市不按空格切，中文照旧按空格 / 短横切", () => {
  const rows = [
    ...Array(3).fill(0).map(() => j({ location: "Brooklyn Park, MN" })),
    ...Array(2).fill(0).map(() => j({ location: "San Diego, CA" })),
    j({ location: "San Jose, CA, USA" }),
  ];
  const cities = D.deriveHiring(rows, NOW_ISO).payload.top_cities;
  assert.deepEqual(cities, [
    { key: "Brooklyn Park", count: 3 },
    { key: "San Diego", count: 2 },
    { key: "San Jose", count: 1 },
  ]);

  const cn = [
    j({ location: "上海市-浦东新区" }), j({ location: "上海 徐汇" }), j({ location: "上海" }),
    j({ location: "北京市·海淀区" }), j({ location: "北京 Beijing" }),
    j({ location: "香港" }), j({ location: "深圳" }),
  ];
  assert.deepEqual(D.deriveHiring(cn, NOW_ISO).payload.top_cities.slice(0, 2), [
    { key: "上海", count: 3 },
    { key: "北京", count: 2 },
  ]);

  // 短横照旧当分隔：博通把层级写成 "USA-Colorado-Fort Collins-4380 Ziegler Road"，不切就每个园区各算一个「城市」
  const dashed = [
    j({ location: "USA-Colorado-Fort Collins-4380 Ziegler Road" }),
    j({ location: "USA-CA San Jose Innovation Drive" }),
    j({ location: "USA-TX Plano Legacy Drive Suite 700" }),
  ];
  assert.deepEqual(D.deriveHiring(dashed, NOW_ISO).payload.top_cities, [{ key: "USA", count: 3 }]);

  // 门牌号不是城市：库里还没被重抓改写的存量行（2026-10-12：Target 约 2,060 个在招岗排在列表 2000 条上限之外，
  // 日常重抓够不着）和对方没写城市的地址，不能再挤进前三。
  const leftovers = [
    ...Array(5).fill(0).map(() => j({ location: "1000, Nicollet, Mall, MinneapolisMN, 55403, 2542" })),
    ...Array(4).fill(0).map(() => j({ location: "1 New York Plaza" })),
    j({ location: "Minneapolis, MN" }),
  ];
  assert.deepEqual(D.deriveHiring(leftovers, NOW_ISO).payload.top_cities, [{ key: "Minneapolis", count: 1 }]);
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

// ---- 取数从「取前 3000 行」改成「库里按全部在招岗数好再回传」（2026-10-11）----
// 现象：在招超过 3,000 的公司，抽屉里的数字是按磁盘位置最靠前的 3,000 行算的（字节跳动写「社招 14%」，全部在招岗是 72%）。
// 逐家对比的数字在 lib/jobs-store/read.ts 的 INSIGHT_FACETS_SQL 上方。
const READ = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "read.ts"));

// 照 INSIGHT_FACETS_SQL 的写法把在招岗位行聚成结果行，只在测试里替库干这一步。
// 真 SQL 的形状由 tests/insight-derive-columns.test.js 钉着；真 SQL 在真库上跑出来的结果与逐行算的是否相同，
// 单测管不到 —— 那是上线前拿新旧两套代码对全部公司逐家比的（数字在引入这条 SQL 的提交说明里）。
function groupLikeSql(jobs) {
  const active = jobs.filter((x) => x.status === "active");
  const rows = [];
  const group = (facet, valuesOf) => {
    const groups = new Map();
    for (const jb of active) {
      const vals = valuesOf(jb).map((v) => (v === undefined ? null : v));
      const key = JSON.stringify(vals);
      if (!groups.has(key)) groups.set(key, { vals, n: 0 });
      groups.get(key).n++;
    }
    for (const { vals, n } of groups.values()) {
      rows.push({ facet, v1: vals[0] ?? null, v2: vals[1] ?? null, v3: vals[2] ?? null, v4: vals[3] ?? null, v5: vals[4] ?? null, n });
    }
  };
  group("title", (jb) => [jb.title]);
  group("location", (jb) => [jb.location]);
  group("experience", (jb) => [jb.experience]);
  group("education", (jb) => [jb.education]);
  group("salary_text", (jb) => [jb.salary_text]);
  group("first_seen_at", (jb) => [jb.first_seen_at]);
  group("type", (jb) => {
    const rc = jb.recruitment_category ?? null;
    const explicit = jb.recruitment_explicit ?? null;
    // SQL：case when recruitment_category in ('校招', '实习', '社招') then null else job_type / title end
    const decided = ["校招", "实习", "社招"].includes(rc);
    return [rc, explicit === null ? null : String(explicit), decided ? null : jb.job_type, decided ? null : jb.title, jb.posted_at];
  });
  return rows;
}

// 一家「什么情况都有」的公司：四种招聘类型 + 列还没算出来的、带 / 不带发布日、窗内 / 窗外、重复标题、空值。
function mixedCompany() {
  const jobs = [];
  const push = (n, over) => {
    for (let i = 0; i < n; i++) jobs.push(j(over));
  };
  const campus = { job_type: "校招", recruitment_category: "校招", recruitment_explicit: true };
  push(7, { ...campus, title: "管培生", location: "上海", posted_at: "2025-09-01T00:00:00+08:00",
    first_seen_at: "2026-03-01T00:00:00.000Z", experience: "应届", education: "本科", salary_text: "10-15K" });
  push(4, { ...campus, title: "算法工程师（校招）", location: "上海市-浦东新区", posted_at: "2025-10-08T00:00:00+08:00",
    first_seen_at: "2026-04-10T08:00:00.000Z", experience: "应届毕业生", education: "硕士", salary_text: "20-30K" });
  push(2, { ...campus, title: "硬件工程师", location: null, posted_at: null, first_seen_at: "2026-05-20T00:00:00.000Z" });
  push(5, { job_type: "实习", recruitment_category: "实习", recruitment_explicit: true, title: "产品运营实习生",
    location: "北京·海淀", posted_at: "2026-03-15T00:00:00+08:00", first_seen_at: "2026-03-16T00:00:00.000Z",
    experience: "不限", education: "本科", salary_text: "200-300元/天" });
  // 有依据的社招：6 个不同月份各放一批（每批岗位数不同）
  ["2025-07", "2025-11", "2026-01", "2026-02", "2026-04", "2026-06"].forEach((ym, i) => {
    push(i + 2, { job_type: "社招", recruitment_category: "社招", recruitment_explicit: true,
      title: i % 2 ? "后端开发工程师" : "销售经理", location: i % 3 ? "深圳" : "北京",
      posted_at: `${ym}-03T00:00:00+08:00`, first_seen_at: `2026-0${(i % 5) + 1}-11T00:00:00.000Z`,
      experience: i % 2 ? "3-5年" : "5年以上", education: i % 2 ? "本科及以上" : "大专",
      salary_text: i % 2 ? "25-40K" : "15000-25000" });
  });
  // 兜底社招：不进占比
  push(6, { job_type: null, recruitment_category: "社招", recruitment_explicit: false, title: "Store Associate",
    location: "Minneapolis, MN", posted_at: "2026-05-01T00:00:00Z", first_seen_at: "2026-05-02T00:00:00.000Z" });
  // 招聘类型列还没算出来：这时才看 job_type / 标题
  push(3, { job_type: null, recruitment_category: null, recruitment_explicit: null, title: "2026届校园招聘-测试工程师",
    location: "杭州", posted_at: "2025-09-20T00:00:00+08:00", first_seen_at: "2026-06-10T00:00:00.000Z" });
  push(2, { job_type: "实习", recruitment_category: null, recruitment_explicit: null, title: "运营专员",
    location: "杭州", posted_at: null, first_seen_at: "2026-06-12T00:00:00.000Z" });
  // 发布日在 12 个月之前
  push(2, { job_type: "社招", recruitment_category: "社招", recruitment_explicit: true, title: "老岗",
    location: "成都", posted_at: "2023-01-01T00:00:00+08:00", first_seen_at: "2026-01-01T00:00:00.000Z" });
  return jobs;
}

test("分面取数：库里聚好的计数算出来的，与逐行算出来的逐字段相同", () => {
  const jobs = mixedCompany();
  const rows = groupLikeSql(jobs);
  // 夹具得真的用到「一组多个岗」，否则权重那条路没被测到
  for (const facet of ["title", "location", "experience", "education", "salary_text", "first_seen_at", "type"]) {
    assert.ok(rows.some((r) => r.facet === facet && r.n > 1), facet + " 分面里没有一组是多个岗");
  }
  const opts = { headcountBand: "1000-5000" };
  const fromFacets = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(rows), NOW, opts);
  const fromRows = D.deriveCompanyInsights(jobs, NOW, opts);
  assert.deepEqual(fromFacets, fromRows);
  // 三张卡、每个指标都真的算出来了（否则上面那条相等是空对空）
  const p = fromFacets.hiring[0].payload;
  assert.equal(p.active_count, jobs.length);
  assert.deepEqual(p.top_cities.map((c) => c.key), ["深圳", "北京", "上海"]);
  assert.ok(p.top_functions.length > 0);
  assert.ok(p.experience_dist && p.education_dist && p.bucket_share);
  assert.equal(typeof p.open_age_days_median, "number");
  assert.equal(p.mix.unknown, 6, "兜底社招 6 个记未知");
  assert.equal(p.mix.campus, 16, "列判校招 13 个 + 列为空时靠标题判出的 3 个");
  assert.equal(p.mix.intern, 7, "列判实习 5 个 + 列为空时靠 job_type 判出的 2 个");
  assert.match(fromFacets.timing[0].content, /校招集中在 9、10 月；社招全年滚动/);
  assert.equal(fromFacets.compensation_intensity[0].payload.sample, 38, "偶数个明示薪资：中位数走「中间两个取平均」那一支");
});

test("分面取数：在招超过 3000 的公司按全部岗位算，不再是「磁盘上靠前的那 3000 行」", () => {
  // 复刻线上的样子：最先写进库的 3,000 行全是实习，后面 9,000 行是有依据的社招。
  const jobs = [];
  for (let i = 0; i < 3000; i++) {
    jobs.push(j({ title: "运营实习生", job_type: "实习", recruitment_category: "实习", recruitment_explicit: true, location: "北京" }));
  }
  for (let i = 0; i < 9000; i++) {
    jobs.push(j({ title: "后端开发工程师", job_type: "社招", recruitment_category: "社招", recruitment_explicit: true, location: "上海" }));
  }
  // 改之前：只拿到前 3,000 行
  const before = D.deriveCompanyInsights(jobs.slice(0, 3000), NOW, { sampleCapped: true }).hiring[0];
  assert.match(before.content, /3000\+ 个在招岗位（以下按其中 3000 个统计）/);
  assert.deepEqual(before.payload.bucket_share, { campus: 0, intern: 100, social: 0 });
  assert.equal(before.payload.top_cities[0].key, "北京");
  // 现在：库里按 12,000 行数好回传（聚合后只有十几行结果）
  const rows = groupLikeSql(jobs);
  assert.ok(rows.length < 20);
  const now = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(rows), NOW).hiring[0];
  assert.match(now.content, /本平台当前收录 12000 个在招岗位，/);
  assert.equal(/\+ 个在招岗位|按其中/.test(now.content), false);
  assert.equal(now.payload.active_count, 12000);
  assert.equal(now.payload.sample_n, 12000);
  assert.deepEqual(now.payload.bucket_share, { campus: 0, intern: 25, social: 75 });
  assert.deepEqual(now.payload.mix, { campus: 0, intern: 3000, social: 9000, unknown: 0 });
  assert.deepEqual(now.payload.top_cities, [{ key: "上海", count: 9000 }, { key: "北京", count: 3000 }]);
});

test("分面取数：结果行回来的先后不影响任何一个数字（库里 group by 不保证顺序）", () => {
  const rows = groupLikeSql(mixedCompany());
  const base = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(rows), NOW);
  const reversed = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows([...rows].reverse()), NOW);
  assert.deepEqual(reversed, base);
  // 再换一种：按计数升序、同计数按取值倒序
  const shuffled = [...rows].sort((a, b) => a.n - b.n || String(b.v1).localeCompare(String(a.v1)));
  assert.deepEqual(D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(shuffled), NOW), base);
});

test("分面取数：少了一个分面 / 多了不认识的分面就报错，不许静默算少", () => {
  const rows = groupLikeSql(mixedCompany());
  assert.throws(() => READ.facetsFromGroupedRows(rows.filter((r) => r.facet !== "location")), /location 合计 0/);
  assert.throws(() => READ.facetsFromGroupedRows(rows.filter((r) => r.facet !== "type")), /对不上/);
  assert.throws(
    () => READ.facetsFromGroupedRows([...rows, { facet: "summary", v1: "x", v2: null, v3: null, v4: null, v5: null, n: 1 }]),
    /不认识的分面/,
  );
  // 一个在招岗都没有：空分面，三张卡都不出
  const empty = READ.facetsFromGroupedRows([]);
  assert.equal(empty.total, 0);
  assert.deepEqual(D.deriveCompanyInsightsFromFacets(empty, NOW), {});
  // 布尔列是按文本回传的：'true' / 'false' / 空 要还原成 true / false / null
  const typed = READ.facetsFromGroupedRows(groupLikeSql([
    j({ recruitment_category: "社招", recruitment_explicit: true }),
    j({ recruitment_category: "社招", recruitment_explicit: false }),
    j({ recruitment_category: null, recruitment_explicit: null, job_type: "校招" }),
  ])).byTypeDate.map(([jb]) => jb.recruitment_explicit);
  assert.deepEqual(typed, [true, false, null]);
});

// 取数 SQL 的 type 分面在招聘类型列是 校招 / 实习 / 社招 时不带回 job_type / 标题。recruitBucket 要是在这三种情况下
// 还去读它们，线上拿到的是空值，判出来的桶会和逐行算的不一样、而且不报错。
test("recruitBucket：招聘类型列是 校招 / 实习 / 社招 时不看 job_type / 标题（取数 SQL 依赖这一条）", () => {
  for (const category of ["校招", "实习", "社招"]) {
    for (const explicit of [true, false, null]) {
      const col = { recruitment_category: category, recruitment_explicit: explicit };
      const bare = D.recruitBucket({ ...col, job_type: null, title: null });
      for (const noise of [
        { job_type: "实习", title: "Software Engineer Intern" },
        { job_type: "校招", title: "2026届校园招聘" },
        { job_type: "社招", title: "资深专家（社会招聘）" },
      ]) {
        assert.equal(D.recruitBucket({ ...col, ...noise }), bare, `${category}/${explicit} 被 ${noise.title} 带偏了`);
      }
    }
  }
});

// 列里出现三个值以外的东西（空；或别的取值 —— 现在库里没有，但没有约束拦着）：recruitBucket 退回看 job_type / 标题，
// SQL 也得照样把两列带回来。条件写的是「不是这三个值」，不是「为空」。
test("招聘类型列不是 校招 / 实习 / 社招 时：退回看 job_type / 标题，取数也把这两列带回来", () => {
  assert.equal(D.recruitBucket({ recruitment_category: null, recruitment_explicit: null, job_type: "实习", title: "运营" }), "intern");
  for (const odd of [null, "", "全职", "校园招聘"]) {
    const col = { recruitment_category: odd, recruitment_explicit: odd === null ? null : true };
    const jobs = [
      j({ ...col, job_type: "校招", title: "管培生" }),
      j({ ...col, job_type: null, title: "数据分析实习生" }),
      j({ ...col, job_type: null, title: "数据分析实习生" }),
    ];
    const rows = groupLikeSql(jobs);
    assert.ok(rows.filter((r) => r.facet === "type").every((r) => r.v4 !== null), JSON.stringify(odd) + "：标题没带回来");
    assert.deepEqual(
      D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(rows), NOW).hiring[0].payload.mix,
      { campus: 1, intern: 2, social: 0, unknown: 0 },
      JSON.stringify(odd),
    );
  }
});

test("取数 SQL 里的三个招聘类型取值与 recruitBucket 认的是同一批", () => {
  const sql = READ.INSIGHT_FACETS_SQL;
  const inLists = Array.from(sql.matchAll(/recruitment_category in \(([^)]+)\)/g), (m) => m[1].replace(/['\s]/g, ""));
  assert.deepEqual(inLists, ["校招,实习,社招", "校招,实习,社招"]);
  assert.equal(/recruitment_category is null/.test(sql), false, "条件不能写成「为空」");
  const src = fs.readFileSync(DERIVE_PATH, "utf8");
  const start = src.indexOf("export function recruitBucket(");
  const body = src.slice(start, src.indexOf("\n}\n", start));
  assert.deepEqual(Array.from(body.matchAll(/recruitment_category === "([^"]+)"/g), (m) => m[1]), ["校招", "实习", "社招"]);
});

// 库里回来的时间是 PG 的文本写法（空格分隔、时区写成 +08 / +00、可能带微秒），不是 ISO。
// 分面那条路把时间列 ::text 回传，和原来连接直接返回的字符串是同一种写法；这里钉住派生解析得了它。
test("分面取数：时间列是 PG 文本写法时，算出来的与 ISO 写法逐字段相同", () => {
  const PAIRS = [
    ["2025-09-01 00:00:00+08", "2025-09-01T00:00:00+08:00"], // 北京零点
    ["2025-08-31 16:00:00+00", "2025-08-31T16:00:00Z"], // 同一时刻的 UTC 写法
    ["2026-03-01 08:30:15.123456+00", "2026-03-01T08:30:15.123Z"], // 带微秒
  ];
  const build = (side) =>
    PAIRS.flatMap((pair) =>
      [1, 2].map(() => j({ job_type: "校招", recruitment_category: "校招", recruitment_explicit: true, posted_at: pair[side], first_seen_at: pair[side] })),
    );
  for (const [pg, iso] of PAIRS) assert.equal(new Date(pg).getTime(), new Date(iso).getTime(), pg);
  const fromPg = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(groupLikeSql(build(0))), NOW);
  const fromIso = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(groupLikeSql(build(1))), NOW);
  assert.deepEqual(fromPg, fromIso);
  // 9 月 1 日北京零点 = 8 月 31 日 UTC 16 点：两种写法都得算成 9 月（4 个），3 月 2 个
  assert.match(fromPg.timing[0].content, /校招集中在 3、9 月/);
  assert.ok(fromPg.hiring[0].payload.open_age_days_median > 0);
});

test("带权中位数 = 把每个值重复写够遍数再取中位数（在架天数 / 薪资带）", () => {
  // 在架天数：1 天 ×3、10 天 ×2、30 天 ×1 → 排开是 1,1,1,10,10,30，中间两个 1 和 10 取平均 5.5、四舍五入 6
  const nowMs = NOW.getTime();
  const at = (days) => new Date(nowMs - days * 86400000).toISOString();
  const spec = [[1, 3], [10, 2], [30, 1]];
  const jobs = spec.flatMap(([days, n]) =>
    Array.from({ length: n }, () => j({ first_seen_at: at(days), salary_text: `${days + 10}-${days + 20}K` })),
  );
  const fromRows = D.deriveCompanyInsights(jobs, NOW);
  const fromFacets = D.deriveCompanyInsightsFromFacets(READ.facetsFromGroupedRows(groupLikeSql(jobs)), NOW);
  assert.equal(fromRows.hiring[0].payload.open_age_days_median, 6);
  assert.equal(fromFacets.hiring[0].payload.open_age_days_median, 6);
  assert.deepEqual(fromFacets.compensation_intensity[0].payload, fromRows.compensation_intensity[0].payload);
  // 薪资下限排开是 11,11,11,20,20,40 → (11 + 20) / 2 = 15.5 → 16；上限同理 26
  assert.deepEqual(fromFacets.compensation_intensity[0].payload, { sample_n: 6, min_k: 16, max_k: 26, sample: 6 });
});
