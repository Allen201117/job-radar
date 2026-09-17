// /today 召回「正文按需传」的契约（2026-09-18）。
//
// 只给「有机会通过职能门」的候选行传 300 字截断正文，其余传 NULL —— 因为职能门必拒的行
// 其 MatchFacts 连同 skillsHit 一起被丢弃，正文不可能改变任何结果（论证见
// lib/jobs-store/opportunities.candidateSummaryExpr）。真库实测：机械@广东 1,794 行里 710 行
// 职能门必拒，整条召回 1,905 kB → 1,377 kB。
//
// 这条测试守四个**少一个就不再是等价变换**的口子，以及一个「拒绝原因不许漂」的不变量：
//   ① job_function 为 NULL / 空 / 「其他」照传（职能门对这三种放行，且列为空时要靠正文现算职能）；
//   ② 批量门店公司照传（bulkStoreGroupKey 拿正文当折叠键，抽走会让 counts.screened 漂）；
//   ③ 用户没填目标岗位（职能集为空）→ 整条门不生效，一行都不许省；
//   ③b 用户配了 exclude_keywords → 整条门不生效。职能门 2026-09-18 起不再一票否决
//      （标题自判职能相符 + 标题字面 exact 会放行），被省掉正文的行有机会展示，而排除词
//      只出现在正文时就看不见了 ——「命中排除词一律不入选」是产品红线，不能靠运气；
//   ④ summary_len 恒随行返回，summaryOk/summaryLong 认它 —— 否则职能门必拒的行会被记成
//      thin_summary 而不是 role_mismatch。
const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { buildRecallSql } = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "opportunities.ts"));
const { computeMatchFacts } = loadTs(path.join(__dirname, "..", "lib", "opportunities", "eligibility.ts"));
const { BULK_STORE_COMPANIES } = loadTs(path.join(__dirname, "..", "lib", "bulk-store-dedup.ts"));

const SINCE = "2026-09-11T00:00:00.000Z";
const baseProfile = {
  userId: "u1", jobScope: "domestic", targetRegions: [],
  targetRoles: ["产品经理"], targetKeywords: [], excludeKeywords: [],
  targetLocations: [], targetCompanies: [], targetIndustries: [], skills: [],
  experienceStage: "", seniority: null, highestEducation: null, dailyLimit: 20,
};

function build(profile) {
  return buildRecallSql(profile, SINCE, 900);
}

test("正文门：职能判得出的画像 → CASE 表达式带齐三个放行口子", () => {
  const { sql, params } = build(baseProfile);
  assert.match(sql, /case when job_function is null or job_function = '' or job_function = '其他'/);
  assert.match(sql, /job_function = any\(\$\d+::text\[\]\)/);
  assert.match(sql, /company ilike any\(array\(select '%' \|\| c \|\| '%' from unnest\(\$\d+::text\[\]\) c\)\)/);
  // 目标职能与批量门店公司都以参数下发（不拼字符串）
  assert.ok(params.some((p) => Array.isArray(p) && p.includes("产品")), "目标职能集必须作为参数下发");
  assert.ok(
    params.some((p) => Array.isArray(p) && BULK_STORE_COMPANIES.every((c) => p.includes(c))),
    "批量门店公司必须作为参数下发（且元素不带 %，否则会被阶段谓词哨兵误认成 like 模式组）",
  );
});

test("正文门：用户没填目标岗位（职能集为空）→ 一行都不省，全传", () => {
  const { sql } = build({ ...baseProfile, targetRoles: [], targetKeywords: ["Python"] });
  assert.ok(!sql.includes("case when job_function is null"), "职能集为空时不许挂正文门");
  assert.match(sql, /left\(btrim\(summary\), 300\) as summary/);
});

test("正文门：用户配了排除词 → 一行都不省，全传（排除词要看正文，是产品红线）", () => {
  const { sql } = build({ ...baseProfile, excludeKeywords: ["外包"] });
  assert.ok(!sql.includes("case when job_function is null"), "有排除词时不许挂正文门");
  assert.match(sql, /left\(btrim\(summary\), 300\) as summary/);
});

test("正文门：RECALL_SUMMARY_GATE=off 退回全传（运维开关 + 对拍尺子）", () => {
  const prev = process.env.RECALL_SUMMARY_GATE;
  process.env.RECALL_SUMMARY_GATE = "off";
  try {
    const { sql } = build(baseProfile);
    assert.ok(!sql.includes("case when job_function is null"));
    assert.match(sql, /left\(btrim\(summary\), 300\) as summary/);
  } finally {
    if (prev === undefined) delete process.env.RECALL_SUMMARY_GATE;
    else process.env.RECALL_SUMMARY_GATE = prev;
  }
});

test("summary_len 恒随行返回（两种形态都要有）", () => {
  assert.match(build(baseProfile).sql, /char_length\(btrim\(summary\)\) as summary_len/);
  assert.match(
    build({ ...baseProfile, targetRoles: [], targetKeywords: ["Python"] }).sql,
    /char_length\(btrim\(summary\)\) as summary_len/,
  );
});

test("正文被省掉的行，拒绝原因仍是 role_mismatch 而不是 thin_summary", () => {
  const profile = { ...baseProfile, targetRoles: ["产品经理"] };
  const now = new Date("2026-09-18T00:00:00Z");
  const job = {
    id: "j1", status: "active",
    company: "某公司", title: "高级后端开发工程师",
    summary: null, summary_len: 800, // ← 正文被职能门省掉，但长度随行带回
    job_function: "研发", recruitment_category: "社招", recruitment_explicit: true,
    location: "北京", last_seen_at: now.toISOString(), first_seen_at: now.toISOString(),
  };
  const facts = computeMatchFacts(job, profile, undefined, { primary: null, viewed: false }, now);
  assert.equal(facts.summaryOk, true, "summaryOk 必须认 summary_len，不能因 summary=null 判成薄卡");
  assert.equal(facts.summaryLong, true);
  assert.equal(facts.roleTier, null, "职能门必拒 → roleTier 为 null");
});

test("没有 summary_len 的调用方（Supabase 兜底 / 单测）行为不变", () => {
  const now = new Date("2026-09-18T00:00:00Z");
  const short = computeMatchFacts(
    { id: "j2", status: "active", company: "C", title: "T", summary: "太短" },
    baseProfile, undefined, { primary: null, viewed: false }, now,
  );
  assert.equal(short.summaryOk, false);
});
