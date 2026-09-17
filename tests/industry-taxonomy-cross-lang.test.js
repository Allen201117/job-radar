const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { loadTs } = require("./_load-ts");

// ============================================================
// 跨语言对拍：lib/industry-taxonomy.ts（app 侧）与 crawler/industry_taxonomy.py（爬虫侧）
// 必须读同一份 lib/industry-taxonomy.json 并对同一批 industry 原始写法给出逐字相同的结论。
//
// 为什么要这道门：company-industry.js / company_industry.py 的教训——两端各写一份实现，
// 改一边不改另一边就漂了，且很久没人发现（tests/company-industry-cross-lang.test.js 的门禁
// 说明）。这次两端都只是「读同一个 JSON」，理论上不会漂，但门禁本身也要覆盖「有没有真的在读
// 同一份数据」——如果哪端不小心复制了一份内嵌拷贝，这个测试会先坏给你看。
//
// 全量对拍（433 条 mapping key 全跑），不抽样——按项目「验证要扫全集」的规矩。
// ============================================================

const json = require("../lib/industry-taxonomy.json");
const T = loadTs(path.join(__dirname, "..", "lib", "industry-taxonomy.ts"));

function classifyViaPython(rawList) {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "crawler"))})
from industry_taxonomy import classify_industry
names = json.loads(sys.stdin.read())
print(json.dumps([classify_industry(n) for n in names], ensure_ascii=False))
`;
  const out = execFileSync("python3", ["-c", script], { input: JSON.stringify(rawList), encoding: "utf8" });
  return JSON.parse(out);
}

test("JS 与 Python 对全部 433 条 mapping key 给出逐条一致的 industry_group", () => {
  const rawKeys = Object.keys(json.mapping);
  assert.ok(rawKeys.length > 400, "mapping 条目数不应显著少于普查得到的 433 条");
  const pyResults = classifyViaPython(rawKeys);
  const jsResults = rawKeys.map((k) => T.classifyIndustry(k));
  const diffs = rawKeys
    .map((k, i) => [k, jsResults[i], pyResults[i]])
    .filter(([, a, b]) => a !== b)
    .map(([k, a, b]) => `${k}: JS「${a}」≠ Python「${b}」`);
  assert.deepEqual(diffs, [], `两端结论不一致 ${diffs.length} 条：\n${diffs.join("\n")}`);
});

test("JS 与 Python 对边界输入（空值/未收录/空白）也一致", () => {
  const edgeCases = [null, "", "   ", "从未见过的写法·xyz123", "半导体", "游戏"];
  const pyResults = classifyViaPython(edgeCases.map((v) => (v === null ? "" : v)));
  // Python 侧传 null 会被 json 编码成字符串 ""；用未收录空串验证「空值→None」这条边界即可，
  // 真正的 null 语义已由 tests/industry-taxonomy.test.js 的 T.classifyIndustry(null) 单独覆盖。
  const jsResults = edgeCases.map((v) => T.classifyIndustry(v === null ? "" : v));
  assert.deepEqual(jsResults, pyResults);
});

test("JS 与 Python 暴露的 version / groups / otherGroup 一致", () => {
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "crawler"))})
import industry_taxonomy as it
print(json.dumps({"version": it.version(), "groups": it.groups(), "other": it.other_group()}, ensure_ascii=False))
`;
  const out = execFileSync("python3", ["-c", script], { encoding: "utf8" });
  const py = JSON.parse(out);
  assert.equal(T.INDUSTRY_TAXONOMY_VERSION, py.version);
  assert.deepEqual(T.INDUSTRY_GROUPS, py.groups);
  assert.equal(T.OTHER_INDUSTRY_GROUP, py.other);
});
