// lib/llm.js：换模型省钱 + 真实 token 用量记账（2026-08-27）。
// 以前没有任何地方读 API 返回的 usage，花费只能按字符数瞎估，账户欠费也没人察觉。
const test = require("node:test");
const assert = require("node:assert");
const {
  DEFAULT_MODEL,
  DEFAULT_FALLBACK_MODEL,
  formatUsageLog,
  chatJSON,
} = require("../lib/llm");

function withCapturedLogs(fn) {
  const lines = [];
  const original = console.log;
  console.log = (...args) => lines.push(args.join(" "));
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      console.log = original;
    })
    .then(() => lines);
}

function stubFetch(responses) {
  const calls = [];
  globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(init.body);
    calls.push(body.model);
    const next = responses.shift();
    return {
      ok: next.status === 200,
      status: next.status,
      json: async () => next.payload,
      text: async () => "",
    };
  };
  return calls;
}

test("默认模型：不带 Pro/ 前缀（Pro 只能扣充值余额），主备跨厂商", () => {
  assert.ok(!DEFAULT_MODEL.startsWith("Pro/"));
  assert.ok(!DEFAULT_FALLBACK_MODEL.startsWith("Pro/"));
  assert.notEqual(DEFAULT_MODEL.split("/")[0].toLowerCase(),
    DEFAULT_FALLBACK_MODEL.split("/")[0].toLowerCase());
});

test("formatUsageLog 固定格式，缺 usage 字段也不炸", () => {
  assert.equal(
    formatUsageLog("m/x", { prompt_tokens: 1200, completion_tokens: 40 }, "resume"),
    "[llm-usage] model=m/x tag=resume in=1200 out=40",
  );
  assert.equal(formatUsageLog("m/x", null, ""), "[llm-usage] model=m/x tag=- in=0 out=0");
  assert.equal(formatUsageLog("m/x", { prompt_tokens: "oops" }, "t"),
    "[llm-usage] model=m/x tag=t in=0 out=0");
});

test("chatJSON 把真实 token 数记进日志（可 grep [llm-usage]）", async () => {
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.SILICONFLOW_API_KEY;
  process.env.SILICONFLOW_API_KEY = "test-key";
  try {
    stubFetch([{
      status: 200,
      payload: {
        choices: [{ message: { content: "{\"ok\":true}" } }],
        usage: { prompt_tokens: 900, completion_tokens: 33 },
      },
    }]);
    const lines = await withCapturedLogs(async () => {
      const out = await chatJSON([{ role: "user", content: "x" }], { tag: "resume" });
      assert.deepEqual(out, { ok: true });
    });
    assert.equal(lines.length, 1);
    assert.equal(lines[0], `[llm-usage] model=${DEFAULT_MODEL} tag=resume in=900 out=33`);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.SILICONFLOW_API_KEY;
    else process.env.SILICONFLOW_API_KEY = originalKey;
  }
});

test("降级到备用模型时，用量记的是**实际服务的那个模型**", async () => {
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.SILICONFLOW_API_KEY;
  process.env.SILICONFLOW_API_KEY = "test-key";
  try {
    const calls = stubFetch([
      { status: 429, payload: {} },   // 主模型被挤爆
      {
        status: 200,
        payload: {
          choices: [{ message: { content: "{\"ok\":1}" } }],
          usage: { prompt_tokens: 10, completion_tokens: 5 },
        },
      },
    ]);
    const lines = await withCapturedLogs(() => chatJSON([{ role: "user", content: "x" }]));
    assert.deepEqual(calls, [DEFAULT_MODEL, DEFAULT_FALLBACK_MODEL]);
    assert.equal(lines[0], `[llm-usage] model=${DEFAULT_FALLBACK_MODEL} tag=- in=10 out=5`);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.SILICONFLOW_API_KEY;
    else process.env.SILICONFLOW_API_KEY = originalKey;
  }
});
