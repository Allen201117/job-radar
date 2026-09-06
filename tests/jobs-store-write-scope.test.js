const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const ROOT = path.join(__dirname, "..");

// ============================================================
// app 写入链（lib/jobs-store/write.ts）的求职范围契约。守两条不变量：
//
// ① 有源 regions 就必须喂给 deriveJobScope —— 与 crawler/normalizer 同口径。
//    否则外企 ATS 的裸「远程」岗按默认落 domestic，混进用户的「国内」筛选结果。
// ② 拿不出依据时**不许写** job_scope —— discovery 那条链写 source_id=null、没有 sources 行
//    可查，它算出来的 'domestic' 是默认值不是结论；job_scope 又在 UPDATE_DATA_COLS 里，
//    让它盖掉库里爬虫按 regions 算好的 overseas = 刷一次就把海外岗打回国内看板
//    （2026-09-05 香港库实测这批在招 16,159 个）。
//
// 直接跑真实的 upsertJob，只把数据库那一层换成假的 —— 断言真实发出的 SQL 与绑定值，
// 而不是对源码做正则匹配（正则守不住「行为变了但字面还在」）。
// ============================================================

function loadWriteWithFakeDb({ existingId = null } = {}) {
  const calls = [];
  const cache = new Map();
  cache.set(path.join(ROOT, "lib", "jobs-store", "client.ts"), {
    exports: {
      jobsQuery: async (sql, vals) => {
        calls.push({ sql, vals });
        if (/^\s*select id, status from jobs/.test(sql)) {
          return existingId ? [{ id: existingId, status: "active" }] : [];
        }
        return [{ id: existingId || "00000000-0000-0000-0000-000000000001" }];
      },
    },
  });
  const mod = loadTs(path.join(ROOT, "lib", "jobs-store", "write.ts"), cache);
  return { mod, calls };
}

const findCall = (calls, re) => calls.find((c) => re.test(c.sql));

// 从真实 SQL 里解析某一列绑到第几个占位符再取值：不硬编码列序，改列表也不会假绿。
function insertValue(call, col) {
  // ⚠️ values 列表里有 gen_random_uuid()，不能用 [^)]* 收尾，得贪到 ") returning"。
  const cols = /insert into jobs \(([^)]*)\) values \(([\s\S]*)\) returning /.exec(call.sql);
  assert.ok(cols, "解析不出 insert 语句");
  const names = cols[1].split(",").map((s) => s.trim());
  const slots = cols[2].split(",").map((s) => s.trim());
  const i = names.indexOf(col);
  assert.ok(i >= 0, `insert 列表里没有 ${col}`);
  const m = /^\$(\d+)$/.exec(slots[i]);
  assert.ok(m, `${col} 不是占位符而是字面量 ${slots[i]}`);
  return call.vals[Number(m[1]) - 1];
}

function updateBinding(call, col) {
  // 取到「下一列的 x = 」为止：COALESCE(...) 自己带逗号，按逗号切会切碎。
  const m = new RegExp(`\\b${col} = ([\\s\\S]*?)(?=, [a-z_]+ = )`).exec(call.sql);
  assert.ok(m, `update 语句里没有 ${col}`);
  const slot = /\$(\d+)/.exec(m[1]);
  assert.ok(slot, `${col} 没有绑定占位符：${m[1]}`);
  return { clause: m[1].trim(), value: call.vals[Number(slot[1]) - 1] };
}

const baseJob = { company: "Acme", title: "Staff Engineer", jd_url: "https://boards.example.com/jobs/1" };

test("插入：海外源（regions 不含 CN）的裸「远程」判 overseas", async () => {
  const { mod, calls } = loadWriteWithFakeDb();
  await mod.upsertJob({ ...baseJob, location: "远程", source_regions: ["US", "SG", "Remote"] });
  assert.equal(insertValue(findCall(calls, /^insert into jobs/), "job_scope"), "overseas");
});

test("插入：源含 CN 的裸「远程」仍判 domestic（宁可漏判不可错杀）", async () => {
  const { mod, calls } = loadWriteWithFakeDb();
  await mod.upsertJob({ ...baseJob, location: "远程", source_regions: ["CN", "US", "SG", "Remote"] });
  assert.equal(insertValue(findCall(calls, /^insert into jobs/), "job_scope"), "domestic");
});

test("插入：拿不到源 regions 时维持旧默认 domestic", async () => {
  const { mod, calls } = loadWriteWithFakeDb();
  await mod.upsertJob({ ...baseJob, location: "远程" });
  assert.equal(insertValue(findCall(calls, /^insert into jobs/), "job_scope"), "domestic");
});

test("更新：有源 regions 作依据时照常写入 overseas", async () => {
  const { mod, calls } = loadWriteWithFakeDb({ existingId: "11111111-1111-1111-1111-111111111111" });
  await mod.upsertJob({ ...baseJob, location: "远程", source_regions: ["US", "SG", "Remote"] });
  const b = updateBinding(findCall(calls, /^update jobs set/), "job_scope");
  assert.equal(b.value, "overseas");
});

test("更新：拿不出依据时把 job_scope 传 null + COALESCE 回退，绝不覆盖库里已判好的值", async () => {
  // 这条就是 discovery 那条链（source_id=null、地点是裸「远程」）踩的形状。
  const { mod, calls } = loadWriteWithFakeDb({ existingId: "11111111-1111-1111-1111-111111111111" });
  await mod.upsertJob({ ...baseJob, location: "远程", source_id: null });
  const b = updateBinding(findCall(calls, /^update jobs set/), "job_scope");
  assert.equal(b.value, null, "无依据时必须传 null，否则默认值会盖掉爬虫的结论");
  assert.match(b.clause, /^COALESCE\(\$\d+, job_scope\)$/);
});

test("更新：源 regions 含 CN + 地点判不出国家 —— 那是穿过 regions 落到兜底，不算依据", async () => {
  // ⚠️ 这条最容易写错：拿到了 regions ≠ regions 给出了结论。regions 含 CN 时函数是**穿过**
  // 那个分支落到末尾兜底的，结论仍是默认 domestic。库里 2,001 个在招岗地点写成
  // "Toronto, Canada" / "Warsaw, …, PL"（国别码还没进词表）、已判 overseas，
  // 拿这个默认值去盖就是把真海外岗打回国内。
  const { mod, calls } = loadWriteWithFakeDb({ existingId: "11111111-1111-1111-1111-111111111111" });
  await mod.upsertJob({ ...baseJob, location: "Toronto, Canada", source_regions: ["CN", "US", "SG", "Remote"] });
  const b = updateBinding(findCall(calls, /^update jobs set/), "job_scope");
  assert.equal(b.value, null);
  assert.match(b.clause, /^COALESCE\(\$\d+, job_scope\)$/);
});

test("更新：地点本身能抽出国家时，它就是依据，照常覆写", async () => {
  const { mod, calls } = loadWriteWithFakeDb({ existingId: "11111111-1111-1111-1111-111111111111" });
  await mod.upsertJob({ ...baseJob, location: "Beijing, China" });
  assert.equal(updateBinding(findCall(calls, /^update jobs set/), "job_scope").value, "domestic");

  const second = loadWriteWithFakeDb({ existingId: "11111111-1111-1111-1111-111111111111" });
  await second.mod.upsertJob({ ...baseJob, location: "New York, NY" });
  assert.equal(updateBinding(findCall(second.calls, /^update jobs set/), "job_scope").value, "overseas");
});

test("source_regions 是非列字段，绝不能漏进 SQL 或绑定值", async () => {
  const { mod, calls } = loadWriteWithFakeDb();
  await mod.upsertJob({ ...baseJob, location: "远程", source_regions: ["US", "SG", "Remote"] });
  for (const c of calls) {
    assert.doesNotMatch(c.sql, /source_regions/);
    for (const v of c.vals || []) assert.ok(!Array.isArray(v), `绑定值里混进了数组：${JSON.stringify(v)}`);
  }
});
