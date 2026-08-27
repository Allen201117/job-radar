// 召回阶段谓词 ←→ 分区索引谓词 的对齐哨兵。
//
// 背景（2026-08-27）：/today 召回的方向层慢，是因为 tsquery 命中十几万行后还要逐行堆扫
// 才能应用招聘阶段过滤（title/job_type/jd_url 三个 like，走不了索引）。修法是在香港库上建
// 两个分区 GIN（jobs_search_doc_campus_gin / jobs_search_doc_intern_gin），谓词写成
// jobs-db/schema.sql 里的 job_stage_match(...)。实测同一条召回 3.2–5.6s → 0.3–0.5s。
//
// ⚠️ 它靠的是「Postgres 把 immutable 简单 SQL 函数内联后，索引谓词与召回 SQL 的 where 子句
// 结构完全相同」才匹配得上。所以两边的 like 模式**必须逐字一致**——一旦漂移，planner 会
// 静默不用这个索引：不报错、不出错、只是又慢回去。没有这条测试就没人会发现。
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { buildRecallSql } = loadTs(path.join(__dirname, "..", "lib", "jobs-store", "opportunities.ts"));
const SCHEMA = fs.readFileSync(path.join(__dirname, "..", "jobs-db", "schema.sql"), "utf8");

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

/** 召回 SQL 把阶段模式作为 text[] 参数下发；取出这一对（文本模式组、URL 模式组）。 */
function recallStagePatterns(stage) {
  const built = buildRecallSql({ ...baseProfile, experienceStage: stage }, SINCE, 900);
  const arrays = built.params.filter(
    (p) => Array.isArray(p) && p.every((x) => typeof x === "string" && x.startsWith("%")),
  );
  assert.equal(arrays.length, 2, `${stage} 应下发两组 like 模式（文本 + URL）`);
  return { text: arrays[0], url: arrays[1] };
}

/** 从 schema.sql 的 job_stage_match 里取出某个分支的三组 array[...] 字面量。 */
function schemaStagePatterns(branch) {
  const fn = SCHEMA.split("create or replace function job_stage_match")[1];
  assert.ok(fn, "schema.sql 里必须有 job_stage_match（分区索引的谓词来源）");
  const body = fn.split("$function$")[1];
  const branchBody = body.split(`when '${branch}' then`)[1];
  assert.ok(branchBody, `job_stage_match 缺 '${branch}' 分支`);
  const upToNext = branchBody.split(/\n\s*when |\n\s*else /)[0];
  const arrays = [...upToNext.matchAll(/array\[([^\]]*)\]/g)].map((m) =>
    m[1].split(",").map((s) => s.trim().replace(/^'|'$/g, "")),
  );
  assert.equal(arrays.length, 3, `${branch} 分支应有三组模式（title / job_type / jd_url）`);
  return { title: arrays[0], jobType: arrays[1], url: arrays[2] };
}

for (const [stage, branch] of [["校招", "campus"], ["实习", "intern"]]) {
  test(`${stage} 召回谓词与 ${branch} 分区索引谓词逐字一致（漂移会让索引被静默忽略）`, () => {
    const recall = recallStagePatterns(stage);
    const schema = schemaStagePatterns(branch);
    // 召回 SQL 里 title 与 job_type 共用同一组文本模式，索引谓词也必须两处都用它
    assert.deepEqual(schema.title, recall.text, `${branch}: title 模式漂移`);
    assert.deepEqual(schema.jobType, recall.text, `${branch}: job_type 模式漂移`);
    assert.deepEqual(schema.url, recall.url, `${branch}: jd_url 模式漂移`);
  });
}

test("两个分区 GIN 索引都建在 job_stage_match 上（否则谓词匹配不成立）", () => {
  for (const [name, branch] of [
    ["jobs_search_doc_campus_gin", "campus"],
    ["jobs_search_doc_intern_gin", "intern"],
  ]) {
    const line = SCHEMA.split("\n").join(" ").match(new RegExp(`create index if not exists ${name}[^;]*;`));
    assert.ok(line, `schema.sql 缺索引 ${name}`);
    assert.match(line[0], /using gin \(search_doc\)/, `${name} 必须是 search_doc 的 GIN`);
    assert.match(line[0], /status = 'active'/, `${name} 谓词必须含 status='active'`);
    assert.match(
      line[0],
      new RegExp(`job_stage_match\\(title, job_type, jd_url, '${branch}'\\)`),
      `${name} 谓词必须用 job_stage_match(..., '${branch}')`,
    );
  }
});
