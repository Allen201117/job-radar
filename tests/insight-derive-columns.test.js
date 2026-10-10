// 洞察派生只取它真正读的列 —— 两个方向都要守：
//   · 少取：insight-derive 读了某列、取数却没带它 → 那一列恒为 undefined，对应维度静默算不出来；
//   · 多取：把整段职位描述（summary）带回来 → 大公司一次搬 3000 行正文，洞察抽屉白等 1 秒多。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

const derive = read("lib/insight-derive.ts");
const store = read("lib/jobs-store/read.ts");

function selectedColumns() {
  const m = /export const INSIGHT_DERIVE_COLUMNS =\s*"([^"]+)"/.exec(store);
  assert.ok(m, "找不到 INSIGHT_DERIVE_COLUMNS");
  return m[1].split(",").map((c) => c.trim());
}

// insight-derive 里对岗位行的属性访问：全部写成 jb.<列名>（文件内约定）。
function columnsReadByDerive() {
  return [...new Set(Array.from(derive.matchAll(/\bjb\.([a-z_]+)\b/g), (m) => m[1]))].sort();
}

test("派生读到的每一列都在取数列表里（少取会让维度静默算不出来）", () => {
  const selected = new Set(selectedColumns());
  const readCols = columnsReadByDerive();
  assert.ok(readCols.length >= 6, "扫描没扫到东西，正则可能失效：" + readCols.join(","));
  const missing = readCols.filter((c) => !selected.has(c));
  assert.deepEqual(missing, [], "insight-derive 读了这些列，但 INSIGHT_DERIVE_COLUMNS 没取：" + missing.join(", "));
});

test("取数列表里没有派生用不到的列（尤其不带正文）", () => {
  const readCols = new Set(columnsReadByDerive());
  // company 不经 jb. 访问：它是 where 条件用的归属列，留着便于排查。
  const extra = selectedColumns().filter((c) => c !== "company" && !readCols.has(c));
  assert.deepEqual(extra, [], "这些列取回来了但没人读：" + extra.join(", "));
  assert.equal(selectedColumns().includes("summary"), false);
});

test("洞察派生的取数走窄列，不再用全量 JOB_COLUMNS", () => {
  const fn = store.slice(store.indexOf("export async function activeJobsByCompanies"));
  const body = fn.slice(0, fn.indexOf("\n}\n"));
  assert.match(body, /select \$\{INSIGHT_DERIVE_COLUMNS\} from jobs where status = 'active' and company = any\(\$1::text\[\]\) limit \$2/);
  assert.equal(/JOB_COLUMNS\}/.test(body.replace("INSIGHT_DERIVE_COLUMNS}", "")), false);
});
