const test = require("node:test");
const assert = require("node:assert");

const { recordOpsRun, statusFromCounts, shanghaiDateString } = require("../scripts/lib/record-ops-run.js");

test("statusFromCounts: 0/0 -> success", () => {
  assert.equal(statusFromCounts(0, 0), "success");
});

test("statusFromCounts: failed === processed (>0) -> failed", () => {
  assert.equal(statusFromCounts(5, 5), "failed");
});

test("statusFromCounts: 0 < failed < processed -> partial", () => {
  assert.equal(statusFromCounts(5, 2), "partial");
});

test("shanghaiDateString: UTC 19:45 已跨过上海午夜，取次日日期", () => {
  // 2026-09-18T19:45:00Z = 上海 2026-09-19 03:45 —— 必须改 1 的回归钉。
  assert.equal(shanghaiDateString(new Date("2026-09-18T19:45:00Z")), "2026-09-19");
});

test("shanghaiDateString: UTC 上午（上海仍是同一天）", () => {
  assert.equal(shanghaiDateString(new Date("2026-09-18T02:00:00Z")), "2026-09-18");
});

test("recordOpsRun: 缺 SUPABASE_URL 时返回 false、不抛异常、stderr 有一行", async () => {
  const prevUrl = process.env.SUPABASE_URL;
  const prevKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  delete process.env.SUPABASE_URL;
  process.env.SUPABASE_SERVICE_ROLE_KEY = "whatever";
  const lines = [];
  const origError = console.error;
  console.error = (msg) => lines.push(msg);
  try {
    const result = await recordOpsRun("some_module", { a: 1 }, "success");
    assert.equal(result, false);
    assert.equal(lines.length, 1);
    assert.match(lines[0], /跳过台账写入/);
  } finally {
    console.error = origError;
    if (prevUrl === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = prevUrl;
    if (prevKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = prevKey;
  }
});

test("recordOpsRun: 缺 SUPABASE_SERVICE_ROLE_KEY 时同样返回 false、不抛", async () => {
  const prevUrl = process.env.SUPABASE_URL;
  const prevKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = "https://example.supabase.co";
  delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  const origError = console.error;
  console.error = () => {};
  try {
    const result = await recordOpsRun("some_module", {}, "success");
    assert.equal(result, false);
  } finally {
    console.error = origError;
    if (prevUrl === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = prevUrl;
    if (prevKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = prevKey;
  }
});

// 下面几条注入假的 createClient，验证真正的写入路径——不打真网络。
function fakeClientFactory(capture, { insertError } = {}) {
  return () => ({
    from(table) {
      return {
        async insert(row) {
          capture.table = table;
          capture.row = row;
          return { error: insertError ? { message: insertError } : null };
        },
      };
    },
  });
}

test("recordOpsRun: 非法 status 降级为 failed 写入", async () => {
  const prevUrl = process.env.SUPABASE_URL;
  const prevKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_SERVICE_ROLE_KEY = "whatever";
  const capture = {};
  try {
    const result = await recordOpsRun("some_module", { x: 1 }, "not-a-real-status", {
      createClient: fakeClientFactory(capture),
      finishedAt: new Date("2026-09-18T19:45:00Z"),
    });
    assert.equal(result, true);
    assert.equal(capture.table, "ops_runs");
    assert.equal(capture.row.status, "failed");
    assert.equal(capture.row.module, "some_module");
    assert.equal(capture.row.run_date, "2026-09-19"); // 同一次改动的回归钉：写入的 run_date 也要是上海日期
  } finally {
    if (prevUrl === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = prevUrl;
    if (prevKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = prevKey;
  }
});

test("recordOpsRun: insert 报错时返回 false 且不抛", async () => {
  const prevUrl = process.env.SUPABASE_URL;
  const prevKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_SERVICE_ROLE_KEY = "whatever";
  const capture = {};
  const origError = console.error;
  console.error = () => {};
  try {
    const result = await recordOpsRun("some_module", {}, "success", {
      createClient: fakeClientFactory(capture, { insertError: "boom" }),
    });
    assert.equal(result, false);
  } finally {
    console.error = origError;
    if (prevUrl === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = prevUrl;
    if (prevKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = prevKey;
  }
});
