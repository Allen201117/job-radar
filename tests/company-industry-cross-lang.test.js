const test = require("node:test");
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const { classifyCompanyIndustry, COMPANY_OVERRIDES } = require("../lib/company-industry.js");

// ============================================================
// 跨语言对拍：lib/company-industry.js（app 侧）与 crawler/company_industry.py（爬虫侧）
// 是同一个判定的两份实现，必须对同一批公司名给出**逐字相同**的结论。
//
// 为什么要这道门：2026-09-03 查「宁德时代被算成互联网」时发现，Python 侧是手工镜像的第二份
// 实现，而 sync 测试只守 overrides JSON、不守关键词规则和匹配策略 —— 两端早就漂了
// （JS 改了词边界和最长匹配，Python 还是裸 substring + 第一个命中）。
// 同一个事实有两份各说各话的实现，就是「demo 味」的典型：能跑，但治理不了。
// ============================================================

const SAMPLES = [
  // 用户实锤 + 子串张冠李戴
  "宁德时代", "京东", "京东方", "BOE 京东方科技集团", "京东物流", "京东科技",
  "网易", "网易云音乐", "网易有道", "腾讯", "腾讯音乐 TME",
  // 英文单词内部子串
  "雅培 Abbott", "ABB 集团", "American Express", "SF Express 顺丰",
  "BioNTech", "Genentech", "CapitaLand", "Intel", "英特尔 Intel",
  // 「科技/智能」通用后缀
  "豪迈科技", "金风科技", "晶澳科技", "金发科技", "容百科技", "拓荆科技",
  "先导智能", "黑芝麻智能", "宇树科技（杭州）有限公司", "某某智能科技", "某某科技股份有限公司",
  // 强信号仍要判得出
  "某某网络科技", "某某信息技术", "某某软件", "某某人工智能", "某某光伏科技",
  "某某半导体科技", "某某生物科技", "某某证券", "某某制药股份", "某某新能源汽车",
  // 长名 / 混排 / 边界
  "浙江吉利控股集团", "新疆特变电工集团", "深圳市汇川技术", "农夫山泉 养生堂",
  "字节跳动", "比亚迪", "顺丰速运", "某某集团", "", "  ",
];

test("JS 与 Python 分类器在样例集上逐条一致", () => {
  const py = path.join(__dirname, "..", "crawler", "company_industry.py");
  assert.ok(fs.existsSync(py), "crawler/company_industry.py 必须存在");
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "crawler"))})
from company_industry import classify_company_industry
names = json.loads(sys.stdin.read())
print(json.dumps([classify_company_industry(n) for n in names], ensure_ascii=False))
`;
  const out = execFileSync("python3", ["-c", script], { input: JSON.stringify(SAMPLES), encoding: "utf8" });
  const pyResults = JSON.parse(out);
  const jsResults = SAMPLES.map((n) => classifyCompanyIndustry(n));
  const diffs = SAMPLES.map((n, i) => [n, jsResults[i], pyResults[i]])
    .filter(([, a, b]) => a !== b)
    .map(([n, a, b]) => `${n || "(空)"}: JS「${a}」≠ Python「${b}」`);
  assert.deepEqual(diffs, [], `两端结论不一致 ${diffs.length} 条：\n${diffs.join("\n")}`);
});

test("必投清单全量公司名上两端一致（覆盖真实口径，不只样例）", () => {
  const domestic = require("../lib/must-apply-list.json");
  const overseas = require("../lib/must-apply-list-overseas.json");
  const names = [];
  for (const src of [domestic, overseas]) {
    for (const [ind, cos] of Object.entries(src)) {
      if (ind.startsWith("_")) continue;
      for (const c of cos || []) names.push(c.name);
    }
  }
  const script = `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, "..", "crawler"))})
from company_industry import classify_company_industry
print(json.dumps([classify_company_industry(n) for n in json.loads(sys.stdin.read())], ensure_ascii=False))
`;
  const pyResults = JSON.parse(
    execFileSync("python3", ["-c", script], { input: JSON.stringify(names), encoding: "utf8" }),
  );
  const diffs = names
    .map((n, i) => [n, classifyCompanyIndustry(n), pyResults[i]])
    .filter(([, a, b]) => a !== b)
    .map(([n, a, b]) => `${n}: JS「${a}」≠ Python「${b}」`);
  assert.deepEqual(diffs, [], `必投清单上两端不一致 ${diffs.length} 条：\n${diffs.join("\n")}`);
});

test("overrides 表内不得有互相包含却行业不同的条目未被最长匹配覆盖", () => {
  // 自检：若 A 是 B 的子串且行业不同，最长匹配必须让 B 胜出（否则 B 会被 A 吃掉）。
  const norm = (s) => String(s).toLowerCase().trim();
  const bad = [];
  for (const [a, catA] of COMPANY_OVERRIDES) {
    for (const [b, catB] of COMPANY_OVERRIDES) {
      const na = norm(a), nb = norm(b);
      if (na === nb || catA === catB || !nb.includes(na)) continue;
      if (classifyCompanyIndustry(b) !== catB) bad.push(`「${b}」应判 ${catB}，实际被「${a}」判成 ${catA}`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});
