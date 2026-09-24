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

// ── /campus 抽屉：getCampusCompanyJobs 在 JS 里 sort(compareCampusJobs) 再 slice(offset, offset+limit) ──
// 轻查询没有 order by（排序键 deadline 是 text，下推不了，见函数上方 ⚠️），行序由执行计划决定；
// 抽屉「加载更多」每页一次请求，所以两次请求拿到的行序可以不同 → 并列块必须靠 id 定序。
function seededShuffle(arr, seed) {
  let s = seed >>> 0;
  const rand = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function uuidOf(i) {
  const h = require("node:crypto").createHash("md5").update(`campus-tie-${i}`).digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-8${h.slice(17, 20)}-${h.slice(20, 32)}`;
}

function loadCampusRead(lightRows) {
  const cache = new Map();
  // requestSafeCache 底下是 next/cache 的 unstable_cache，离开 Next 运行时会抛 → 公司名缓存直接透传。
  cache.set(path.join(ROOT, "lib", "request-safe-cache.ts"), { exports: { requestSafeCache: (fn) => fn } });
  const client = loadTs(path.join(ROOT, "lib", "jobs-store", "client.ts"), cache);
  const read = loadTs(path.join(ROOT, "lib", "jobs-store", "read.ts"), cache);
  let lightCalls = 0;
  client.jobsQuery = async (sql, params) => {
    if (/where j\.id = any\(\$1::uuid\[\]\)/.test(sql)) {
      const ids = new Set(params[0]);
      return seededShuffle(lightRows.filter((r) => ids.has(r.id)), 99).map((r) => ({ ...r }));
    }
    if (/and j\.company = any\(\$1::text\[\]\)/.test(sql)) {
      lightCalls += 1; // 每次请求换一种行序 = 换了一个执行计划
      return seededShuffle(lightRows, lightCalls).map((r) => ({ ...r }));
    }
    if (/with recursive t as/.test(sql)) return [{ company: "字节跳动" }];
    throw new Error(`意外的 SQL：${sql.trim().slice(0, 80)}`);
  };
  return read;
}

test("getCampusCompanyJobs：并列行（同截止日 / 同一批首见）跨请求翻页不重复、不漏、顺序确定", async () => {
  const batch = "2026-09-23 02:00:00.123456+00"; // 同一事务入库，逐字相同
  const lightRows = Array.from({ length: 40 }, (_, i) => ({
    id: uuidOf(i),
    company: "字节跳动",
    grad_class: null,
    deadline: i < 16 ? "2026-10-31" : null,
    first_seen_at: batch,
    recruitment_category: "校招",
    job_function: "研发",
    city: "北京",
    education: "本科",
    title: `后端开发工程师-${i}`,
    job_type: null,
  }));
  const read = loadCampusRead(lightRows);
  const list = [{ name: "字节跳动", pattern: "%字节跳动%" }];
  const limit = 7;
  const seen = [];
  for (let offset = 0; offset < lightRows.length; offset += limit) {
    const { jobs, total } = await read.getCampusCompanyJobs(list, "%字节跳动%", "campus", { offset, limit });
    assert.equal(total, lightRows.length);
    seen.push(...jobs.map((j) => j.id));
  }
  const dup = seen.length - new Set(seen).size;
  const missing = lightRows.filter((r) => !seen.includes(r.id)).length;
  assert.deepEqual({ dup, missing }, { dup: 0, missing: 0 });
  // 顺序 = 有截止的块在前、无截止的块在后，块内按 id 升序（与 SQL `first_seen_at desc, id` 同向）
  const byId = (rows) => rows.map((r) => r.id).sort();
  assert.deepEqual(seen, [...byId(lightRows.slice(0, 16)), ...byId(lightRows.slice(16))]);
});

test("getCampusCompanyJobs：按游标翻页，两次请求之间有岗下架 / 新岗入库也不漏不重，hasMore 由服务端给", async () => {
  const batch = "2026-09-23 02:00:00.123456+00";
  const mk = (i, deadline) => ({
    id: uuidOf(i), company: "字节跳动", grad_class: null, deadline, first_seen_at: batch,
    recruitment_category: "校招", job_function: "研发", city: "北京", education: "本科",
    title: `后端开发工程师-${i}`, job_type: null,
  });
  const list = [{ name: "字节跳动", pattern: "%字节跳动%" }];
  const limit = 7;
  for (const change of ["remove", "insert"]) {
    const lightRows = Array.from({ length: 40 }, (_, i) => mk(i, i < 16 ? "2026-10-31" : null));
    const read = loadCampusRead(lightRows); // mock 读的是同一个数组，原地改动 = 两次请求之间库变了
    const stable = new Set(lightRows.map((r) => r.id));
    const seen = [];
    let after = null;
    let offset = 0;
    let hasMore = true;
    for (let req = 0; hasMore; req++) {
      const res = await read.getCampusCompanyJobs(list, "%字节跳动%", "campus", { offset, after, limit });
      seen.push(...res.jobs.map((j) => j.id));
      offset += res.jobs.length;
      after = { id: res.jobs.at(-1).id, deadline: res.jobs.at(-1).deadline, first_seen_at: res.jobs.at(-1).first_seen_at };
      hasMore = res.hasMore;
      if (req === 0 && change === "remove") {
        const gone = res.jobs[0].id;
        stable.delete(gone);
        lightRows.splice(lightRows.findIndex((r) => r.id === gone), 1);
      }
      if (req === 0 && change === "insert") lightRows.push(mk(999, "2026-09-30"));
    }
    const dup = seen.length - new Set(seen).size;
    const missing = [...stable].filter((id) => !seen.includes(id)).length;
    assert.deepEqual({ change, dup, missing }, { change, dup: 0, missing: 0 });
  }
});

test("/campus 抽屉「加载更多」必须带游标、按 id 合并去重、按服务端 hasMore 判下一页", () => {
  const client = fs.readFileSync(path.join(ROOT, "app", "campus", "campus-client.tsx"), "utf8");
  assert.match(client, /loadPage\(card\.pattern, loadedCount, campusCursorOf\(/, "加载更多必须把上一页最后一个岗当游标传");
  assert.match(client, /JSON\.stringify\(\{ pattern, mode, offset, after,/, "请求体必须带 after");
  assert.match(client, /incoming\.filter\(\(j: any\) => !have\.has\(j\.id\)\)/, "累计分页必须按 id 去重");
  assert.match(client, /const hasMore = !!page && page\.hasMore;/, "下一页只认服务端 hasMore（下架后 total 与已加载数对不上）");
  const route = fs.readFileSync(path.join(ROOT, "app", "api", "campus-zone", "jobs", "route.ts"), "utf8");
  assert.match(route, /const after = parseCampusCursor\(b\.after\)/);
  assert.match(route, /offset,\s*after,\s*limit: PAGE_SIZE/);
});
