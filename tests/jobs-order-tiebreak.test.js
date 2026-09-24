const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

// 凡是「order by → limit / offset」截断，排序键必须以唯一列 id 收尾（2026-09-23 召回 + /jobs 候选，
// 2026-09-24 补 read.ts 与 Supabase 兜底）。爬虫一批入库几百行 first_seen_at 逐字相同，
// 只按它截断时谁进窗口由执行计划决定，offset 翻页会重复 / 漏行。
const ROOT = path.join(__dirname, "..");

function loadRead() {
  const cache = new Map();
  const client = loadTs(path.join(ROOT, "lib", "jobs-store", "client.ts"), cache);
  const read = loadTs(path.join(ROOT, "lib", "jobs-store", "read.ts"), cache);
  const calls = [];
  client.jobsQuery = async (sql, params) => {
    calls.push({ sql, params });
    return [];
  };
  return { read, calls };
}

test("listLatestActive：各求职范围、翻页都按 first_seen_at desc, id 截断，参数不变", async () => {
  const { read, calls } = loadRead();
  await read.listLatestActive(60, 0, null);
  await read.listLatestActive(1000, 5000, { job_scope: "all" });
  await read.listLatestActive(60, 60, { job_scope: "overseas", target_regions: ["US", "SG", "Remote"] });
  await read.listLatestActive(60, 0, null, { region: "SG" });

  assert.equal(calls.length, 4);
  for (const { sql, params } of calls) {
    assert.match(sql, / order by first_seen_at desc, id limit \$(\d+) offset \$(\d+)$/);
    const [, lim, off] = sql.match(/limit \$(\d+) offset \$(\d+)$/);
    assert.equal(Number(lim), params.length - 1);
    assert.equal(Number(off), params.length);
  }
  assert.deepEqual(calls.map((c) => c.params.slice(-2)), [[60, 0], [1000, 5000], [60, 60], [60, 0]]);
});

test("recallByPrefs：limit 截断同样以 id 收尾", async () => {
  const { read, calls } = loadRead();
  await read.recallByPrefs(["深圳"], ["产品"], 200);
  assert.match(calls[0].sql, / order by first_seen_at desc, id limit \$3$/);
  assert.deepEqual(calls[0].params, ["%深圳%", "%产品%", 200]);
});

function sourceFiles(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) sourceFiles(p, out);
    else if (/\.(ts|tsx|js|jsx)$/.test(ent.name)) out.push(p);
  }
  return out;
}

const isComment = (line) => /^\s*(\/\/|\*|\/\*)/.test(line);
const SCAN_DIRS = ["lib", "app", "components"].map((d) => path.join(ROOT, d));

test("全站 SQL 里的 `order by first_seen_at desc` 后面必须紧跟 `, id`", () => {
  const offenders = [];
  for (const file of SCAN_DIRS.flatMap((d) => sourceFiles(d))) {
    fs.readFileSync(file, "utf8").split("\n").forEach((line, i) => {
      if (isComment(line)) return;
      if (/order by first_seen_at desc(?!, id\b)/i.test(line)) {
        offenders.push(`${path.relative(ROOT, file)}:${i + 1}`);
      }
    });
  }
  assert.deepEqual(offenders, [], `缺 id 决胜列：\n${offenders.join("\n")}`);
});

test("Supabase 兜底：.order(\"first_seen_at\") 之后必须紧跟 .order(\"id\")", () => {
  const offenders = [];
  let seen = 0;
  for (const file of SCAN_DIRS.flatMap((d) => sourceFiles(d))) {
    const src = fs.readFileSync(file, "utf8");
    const re = /\.order\(\s*"first_seen_at"[^)]*\)/g;
    let m;
    while ((m = re.exec(src))) {
      seen += 1;
      const rest = src.slice(m.index + m[0].length);
      if (!/^\s*\.order\(\s*"id"/.test(rest)) {
        const line = src.slice(0, m.index).split("\n").length;
        offenders.push(`${path.relative(ROOT, file)}:${line}`);
      }
    }
  }
  // 扫描器自身不能因为改了写法就「一条都扫不到」而假绿
  assert.ok(seen >= 5, `只扫到 ${seen} 处 .order("first_seen_at")，扫描规则可能失效`);
  assert.deepEqual(offenders, [], `缺 id 决胜列：\n${offenders.join("\n")}`);
});
