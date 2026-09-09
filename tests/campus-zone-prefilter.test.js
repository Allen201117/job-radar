// 校招专区 SQL 粗筛必须是 campusAdmission 的超集（2026-09-09 立）。
// 反面教材：粗筛 url 正则没跟上层4 的 moka 后缀放宽，大疆 131/139、中兴 60/60 个「校招」岗在专区里消失。
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts.js");

const read = loadTs(path.resolve(__dirname, "../lib/jobs-store/read.ts"));
const SQL = read.CAMPUS_PREFILTER_SQL;

// 把 SQL 里 `coalesce(j.jd_url,'') ~* '<regex>'` 的正则抠出来在 JS 里跑（PG 与 JS 这段语法一致）。
function urlRegex(col) {
  const m = SQL.match(new RegExp(`coalesce\\(j\\.${col},''\\) ~\\* '([^']+)'`));
  assert.ok(m, `粗筛里必须有 ${col} 的 url 正则`);
  return new RegExp(m[1].replace(/\\\\/g, "\\"), "i");
}

test("粗筛第一条件直接认库里的 recruitment_category（与 JS 分类器同源）", () => {
  assert.match(SQL, /j\.recruitment_category in \('校招','实习'\)/);
});

test("url 正则接受 moka 门户后缀与 internship，不再只认紧跟 / 的令牌", () => {
  const re = urlRegex("jd_url");
  for (const u of [
    "https://app.mokahr.com/campus-recruitment/dji/143359#/job/6e",
    "https://app.mokahr.com/campus_apply/trip/37757#/job/cc48",
    "https://xiaomi.jobs.f.mioffice.cn/internship/position/768334",
    "https://talent.baidu.com/jobs/campus/123",
    "https://x.com/xiaozhao/1",
  ]) assert.ok(re.test(u), u);
  assert.ok(!re.test("https://hr.163.com/job-detail.html?id=78490"), "无门户令牌的 url 不该命中");
});

test("apply_url 也参与粗筛（分类器输入含 apply_url，jd_url 与 apply_url 可能只有一边带门户令牌）", () => {
  const re = urlRegex("apply_url");
  assert.ok(re.test("https://app.mokahr.com/campus_apply/shopee/2962#/job/1"));
});
