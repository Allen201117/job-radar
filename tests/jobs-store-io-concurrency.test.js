// 香港 jobs 库连接池的预读并发（effective_io_concurrency，2026-10-12）。
// 库上默认值是 1：位图堆扫描回表时一次只等一块盘读，数据不在缓存里的查询（/today 现跑召回、/jobs 登录搜索取候选）
// 冷的时候要几秒；本池的连接建立时就带上 64（实测数字在 lib/jobs-store/client.ts 的 JOBS_IO_CONCURRENCY 上方）。
// 这里钉三件事：① 默认真的带上了，且是连接启动参数（不是事后 set）；② 开关写错不会把连接搞挂；③ 驱动确实把它送出去。
const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const ROOT = path.join(__dirname, "..");
const client = loadTs(path.join(ROOT, "lib", "jobs-store", "client.ts"));

function quietly(fn) {
  const warn = console.warn;
  const seen = [];
  console.warn = (...args) => seen.push(args.join(" "));
  try {
    return { value: fn(), warnings: seen };
  } finally {
    console.warn = warn;
  }
}

test("默认：连接启动参数带 effective_io_concurrency=64", () => {
  assert.equal(client.JOBS_IO_CONCURRENCY, 64);
  assert.equal(client.jobsSessionOptions({}), "-c effective_io_concurrency=64");
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: "" }), "-c effective_io_concurrency=64");
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: "   " }), "-c effective_io_concurrency=64");
});

test("环境变量：off 关掉（不带参数 = 库的默认值），1~1000 的整数改用该值", () => {
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: "off" }), undefined);
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: " OFF " }), undefined);
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: "16" }), "-c effective_io_concurrency=16");
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: "1" }), "-c effective_io_concurrency=1");
  assert.equal(client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: "1000" }), "-c effective_io_concurrency=1000");
});

test("环境变量写错：按默认值并留一行告警，绝不把原文拼进启动参数（库会拒绝非法取值 → 所有连接都建不起来）", () => {
  for (const bad of ["0", "1001", "-3", "+16", "1.5", "1e2", "0x10", "abc", "64; -c statement_timeout=0", "64 -c jit=off", "on", "true"]) {
    const { value, warnings } = quietly(() => client.jobsSessionOptions({ JOBS_DB_IO_CONCURRENCY: bad }));
    assert.equal(value, "-c effective_io_concurrency=64", `写成 ${JSON.stringify(bad)} 时应按默认值`);
    assert.equal(warnings.length, 1, `写成 ${JSON.stringify(bad)} 时应告警一次`);
    // 告警不回显环境变量原文（短值如 "0" 会撞上提示里的「1~1000」，只对够长的写法断言）
    if (bad.length > 6) assert.equal(warnings[0].includes(bad), false, "告警里不回显环境变量原文");
  }
});

// 连接池真的把它带上了，且驱动会把它放进连接启动报文（不是只有我们自己的函数返回对了）。
function withFreshPool(env, fn) {
  const saved = {};
  for (const k of ["JOBS_DATABASE_URL", "JOBS_DATABASE_SSL_CA", "JOBS_DATABASE_TLS_SERVERNAME", "JOBS_DB_IO_CONCURRENCY"]) {
    saved[k] = process.env[k];
    delete process.env[k];
  }
  Object.assign(process.env, {
    // 不会真连：Pool 构造时不建连接，这里只读它的配置
    JOBS_DATABASE_URL: "postgres://app_user:not-a-real-secret@db.invalid:5432/jobs_test",
    JOBS_DATABASE_SSL_CA: "-----BEGIN CERTIFICATE-----\\nMIIB\\n-----END CERTIFICATE-----",
    ...env,
  });
  const prevPool = globalThis.__jobsPool;
  delete globalThis.__jobsPool;
  try {
    const pool = client.jobsPool();
    try {
      return fn(pool);
    } finally {
      pool.end().catch(() => {});
    }
  } finally {
    if (prevPool === undefined) delete globalThis.__jobsPool;
    else globalThis.__jobsPool = prevPool;
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

test("连接池：每条连接的启动参数都带预读并发，其它连接配置没被顺手改掉", () => {
  withFreshPool({}, (pool) => {
    assert.equal(pool.options.options, "-c effective_io_concurrency=64");
    assert.equal(pool.options.max, 5);
    assert.equal(pool.options.statement_timeout, 25_000);
    assert.equal(pool.options.ssl.rejectUnauthorized, true, "证书校验必须保持开启");
    // 驱动侧：用池子的配置建一个（不连接的）Client，它要发给库的启动报文里确实有这一项
    const { Client } = require("pg");
    const c = new Client(pool.options);
    assert.equal(c.getStartupConf().options, "-c effective_io_concurrency=64");
  });
});

test("连接池：开关 off 时不带这个参数；改成 16 时带 16", () => {
  withFreshPool({ JOBS_DB_IO_CONCURRENCY: "off" }, (pool) => {
    assert.equal(pool.options.options, undefined);
    const { Client } = require("pg");
    const saved = process.env.PGOPTIONS;
    delete process.env.PGOPTIONS; // 驱动在我们不传时会读它；本机 / CI 若设了，这条断言量的就不是我们的代码
    try {
      assert.equal("options" in new Client(pool.options).getStartupConf(), false, "关掉时启动报文里不该有 options");
    } finally {
      if (saved !== undefined) process.env.PGOPTIONS = saved;
    }
  });
  withFreshPool({ JOBS_DB_IO_CONCURRENCY: "16" }, (pool) => {
    assert.equal(pool.options.options, "-c effective_io_concurrency=16");
  });
});
