// F8 哨兵：/today 的**前置召回**必须是**后置资格门**可放行集合的超集。
//
// 缺陷原貌（2026-09-08 修）：召回 SQL 只用六个裸词 like title/job_type/jd_url，
// 而后置 checkEligibility → stageState → recruitmentCategory() 认得更多强信号
// （管培生 / 管理培训生 / 留学生专项 / entry-level / new grads …）。于是标题叫「管培生」的
// 在招校招岗：后置判「校招·符合」，前置却根本没召回 → 校招用户在 /today 永远看不见它，
// 同一个岗在 /jobs 页却筛得到（那条链走物化列 recruitment_category）。
//
// 这条测试守的是**方向**：只要 recruitmentCategory(job) 判定为该阶段，召回谓词就必须命中。
// 反方向（召回捞多了）不管——多捞只是多几个候选，后置门照样精筛；漏召回才是丢岗位。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { buildRecallSql } = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "opportunities.ts"));
const { recruitmentCategory } = require("../lib/china-keyword-expansion");

const baseProfile = {
  userId: "u1",
  jobScope: "domestic",
  targetRegions: [],
  targetRoles: ["产品经理"],
  targetKeywords: [],
  excludeKeywords: [],
  targetLocations: [],
  targetCompanies: [],
  targetIndustries: [],
  skills: [],
  experienceStage: "",
  seniority: null,
  highestEducation: null,
  dailyLimit: 20,
};
const SINCE = "2026-08-20T00:00:00.000Z";

/** 取出召回 SQL 实际下发的两组 like 模式（文本组用于 title/job_type，URL 组用于 jd_url）。 */
function recallPatterns(stage) {
  const built = buildRecallSql({ ...baseProfile, experienceStage: stage }, SINCE, 900);
  const arrays = built.params.filter(
    (p) => Array.isArray(p) && p.every((x) => typeof x === "string" && x.startsWith("%")),
  );
  assert.equal(arrays.length, 2, `${stage} 应下发两组 like 模式`);
  return { text: arrays[0], url: arrays[1] };
}

/** 复刻 SQL 侧 `lower(col) like any(array[...])` 的语义（模式两端都是 %，等价于子串包含）。 */
function likeAny(value, patterns) {
  const v = String(value || "").toLowerCase();
  return patterns.some((p) => v.includes(p.replace(/^%|%$/g, "")));
}

function recallHits(job, stage) {
  const { text, url } = recallPatterns(stage);
  return likeAny(job.title, text) || likeAny(job.job_type, text) || likeAny(job.jd_url, url);
}

// 每条都是「后置门会放行、旧召回词表捞不到」的真实形态；标题不含 校招/校园/应届/campus/graduate/届。
const CAMPUS_CASES = [
  { title: "管培生", job_type: null, jd_url: "https://x.com/job/1" },
  { title: "2027 管理培训生（零售方向）", job_type: null, jd_url: "https://x.com/job/2" },
  { title: "留学生专项招聘 - 数据分析", job_type: null, jd_url: "https://x.com/job/3" },
  { title: "Entry-Level Software Engineer", job_type: null, jd_url: "https://x.com/job/4" },
  { title: "Product Manager, New Grads", job_type: null, jd_url: "https://x.com/job/5" },
  { title: "数据分析师", job_type: "管培生", jd_url: "https://x.com/job/6" },
  { title: "运营专员", job_type: null, jd_url: "https://x.com/xiaozhao/job/7" },
];

test("后置判为校招的岗，前置召回必须都能捞到（F8 回归）", () => {
  for (const job of CAMPUS_CASES) {
    assert.equal(
      recruitmentCategory(job),
      "校招",
      `用例本身失效：${job.title} 后置已不判校招，请更新用例而不是放宽召回`,
    );
    assert.ok(
      recallHits(job, "校招"),
      `召回漏掉了后置会放行的校招岗：${JSON.stringify(job)}`,
    );
  }
});

test("后置判为实习的岗，前置召回必须都能捞到（F8 回归）", () => {
  const cases = [
    { title: "暑期实习生 - 后端", job_type: null, jd_url: "https://x.com/job/8" },
    { title: "Data Science Intern", job_type: null, jd_url: "https://x.com/job/9" },
    { title: "分析师", job_type: null, jd_url: "https://x.com/shixi/job/10" },
  ];
  for (const job of cases) {
    assert.equal(recruitmentCategory(job), "实习", `用例失效：${job.title}`);
    assert.ok(recallHits(job, "实习"), `召回漏掉了后置会放行的实习岗：${JSON.stringify(job)}`);
  }
});

test("社招用户不加阶段谓词（默认态，保持最大超集）", () => {
  const built = buildRecallSql({ ...baseProfile, experienceStage: "社招" }, SINCE, 900);
  const arrays = built.params.filter(
    (p) => Array.isArray(p) && p.every((x) => typeof x === "string" && x.startsWith("%")),
  );
  assert.equal(arrays.length, 0, "社招不应下推阶段谓词，否则无明确信号的岗会被前置砍掉");
});
