const test = require("node:test");
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const { deriveCountryCode, deriveJobScope, locationInScope } = require("../lib/geo.js");

// ============================================================
// 跨语言对拍：lib/geo.js（app 写入链）与 crawler/geo.py（爬虫写入链）是同一个「这个岗算国内
// 还是海外」的两份实现，必须对同一批 (location, regions) 给出**逐字相同**的结论。
//
// 为什么要这道门（这次的 bug 本身）：crawler/geo.py 2026-09-04 给 derive_job_scope 加了
// 「地点抽不出国家就按源 regions 兜底」，lib/geo.js 的 deriveJobScope 却还是一个参数 ——
// 同一个裸「远程」岗，爬虫写 overseas，app 的 discovery/search 刷新一次写回 domestic。
// 两端各说各话、还互相覆盖，就是「demo 味」的典型：能跑，但治理不了。
// 逐条断言只能守住想得到的用例；**行为对拍**才守得住「一端加了参数另一端没加」这类漂移。
//
// ⚠️ 样例集刻意不含台湾写法：TW 是**另一处**同族漂移（Python 2026-07-28 就加了 TW token，
// JS 一直没跟上），由 commit c143a6e 单独修 + 单独覆盖，这里不重复。那处合并后可以把
// "Taipei, Taiwan" / "Taiwan, Province of China" 加进 LOCATIONS，本文件不用改别的。
// ============================================================

const LOCATIONS = [
  // 抽不出国家 —— 正是走源 regions 兜底的那一类
  "", "Remote", "远程", "Multiple Locations", "Unknown", "Distributed",
  "Distributed, EMEA", "Ukraine Anywhere", "Santa, ClaraCA", "全国", "海外", "Belarus",
  // 大中华
  "Beijing, China", "北京", "上海", "深圳市", "Hong Kong", "香港", "Macau",
  // 海外（含带国家写法的远程）
  "New York, NY", "Singapore", "Remote - US", "Remote (USA)", "US Remote",
  "Remote - Singapore", "Remote (Singapore)", "Seattle", "United States",
];

const REGION_SETS = [
  null,
  [],
  ["CN"],
  ["US", "SG", "Remote"],
  ["CN", "US", "SG", "Remote"],
  ["Remote"],
  [" CN ", ""],
  ["us"],
];

function runPython() {
  const py = path.join(__dirname, "..", "crawler", "geo.py");
  assert.ok(fs.existsSync(py), "crawler/geo.py 必须存在");
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "crawler"))})
from geo import derive_country_code, derive_job_scope, location_in_scope
locations, region_sets = json.loads(sys.stdin.read())
print(json.dumps({
    "country": [derive_country_code(loc) for loc in locations],
    "scope": [[derive_job_scope(loc, rs) for rs in region_sets] for loc in locations],
    "in_scope": [[location_in_scope(loc, rs) for rs in region_sets] for loc in locations],
}, ensure_ascii=False))
`;
  return JSON.parse(
    execFileSync("python3", ["-c", script], {
      input: JSON.stringify([LOCATIONS, REGION_SETS]),
      encoding: "utf8",
    }),
  );
}

const label = (loc, rs) => `${JSON.stringify(loc)} × regions=${JSON.stringify(rs)}`;

test("deriveCountryCode 两端逐条一致", () => {
  const py = runPython().country;
  const diffs = LOCATIONS.map((loc, i) => [loc, deriveCountryCode(loc), py[i]])
    .filter(([, a, b]) => a !== b)
    .map(([loc, a, b]) => `${JSON.stringify(loc)}: JS「${a}」≠ Python「${b}」`);
  assert.deepEqual(diffs, [], `两端结论不一致 ${diffs.length} 条：\n${diffs.join("\n")}`);
});

test("deriveJobScope 在 location × source regions 全矩阵上两端一致", () => {
  const py = runPython().scope;
  const diffs = [];
  LOCATIONS.forEach((loc, i) => {
    REGION_SETS.forEach((rs, j) => {
      const js = deriveJobScope(loc, rs);
      if (js !== py[i][j]) diffs.push(`${label(loc, rs)}: JS「${js}」≠ Python「${py[i][j]}」`);
    });
  });
  assert.deepEqual(diffs, [], `两端结论不一致 ${diffs.length} 条：\n${diffs.join("\n")}`);
});

test("locationInScope 在同一矩阵上两端一致", () => {
  const py = runPython().in_scope;
  const diffs = [];
  LOCATIONS.forEach((loc, i) => {
    REGION_SETS.forEach((rs, j) => {
      const js = locationInScope(loc, rs);
      if (js !== py[i][j]) diffs.push(`${label(loc, rs)}: JS「${js}」≠ Python「${py[i][j]}」`);
    });
  });
  assert.deepEqual(diffs, [], `两端结论不一致 ${diffs.length} 条：\n${diffs.join("\n")}`);
});
