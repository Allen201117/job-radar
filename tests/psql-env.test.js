// scripts/lib/psql.js：连接串绝不进 psql 的命令行参数，也绝不进抛出的报错（2026-09-24 立）。
// 用一个假 psql（node 脚本）回显它收到的 argv 与 PG* 环境变量，断言密码只经环境变量传入。
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const util = require("node:util");

const { PARAM_ENV, libpqEnvFromUrl, redact, runPsql } = require("../scripts/lib/psql.js");

const RAW_PW = "Fake%40pw%2Fw0rd%2Bx"; // 解码后 Fake@pw/w0rd+x
const PW = "Fake@pw/w0rd+x";
const HOST = "db.example.invalid";
const HOSTADDR = "203.0.113.5";
const URL_ = `postgresql://jobs_user:${RAW_PW}@${HOST}:6543/jobs?sslmode=verify-full&sslrootcert=/tmp/ca+1.pem&hostaddr=${HOSTADDR}`;
const SECRETS = [URL_, RAW_PW, PW, HOST, HOSTADDR];

function assertNoSecrets(text, label) {
  for (const s of SECRETS) assert.ok(!String(text).includes(s), `${label} 泄露了 ${s === URL_ ? "连接串" : "敏感片段"}`);
}

function fakePsql() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fake-psql-"));
  const bin = path.join(dir, "psql");
  fs.writeFileSync(
    bin,
    `#!${process.execPath}
const pg = Object.fromEntries(Object.entries(process.env).filter(([k]) => k.startsWith("PG")));
if (process.env.FAKE_PSQL_MODE === "fail") {
  process.stderr.write('psql: error: connection to server at "' + pg.PGHOST + '" (' + pg.PGHOSTADDR + '), port ' + pg.PGPORT + ' failed: password "' + pg.PGPASSWORD + '" timeout expired\\n');
  process.exit(2);
}
if (process.env.FAKE_PSQL_MODE === "notice") process.stderr.write("NOTICE: talking to " + pg.PGHOST + "\\n");
process.stdout.write(JSON.stringify({ argv: process.argv.slice(2), pg }));
`,
    { mode: 0o755 },
  );
  return bin;
}

test("libpqEnvFromUrl：各段拆成 PG* 变量，百分号解码、+ 不当空格", () => {
  assert.deepEqual(libpqEnvFromUrl(URL_), {
    PGUSER: "jobs_user",
    PGPASSWORD: PW,
    PGHOST: HOST,
    PGPORT: "6543",
    PGDATABASE: "jobs",
    PGSSLMODE: "verify-full",
    PGSSLROOTCERT: "/tmp/ca+1.pem",
    PGHOSTADDR: HOSTADDR,
  });
});

test("libpqEnvFromUrl：只输出 URL 里写了的项（没写的留给环境兜底）；IPv6 去方括号", () => {
  assert.deepEqual(libpqEnvFromUrl("postgres://reader@[::1]/d"), { PGUSER: "reader", PGHOST: "::1", PGDATABASE: "d" });
  assert.deepEqual(libpqEnvFromUrl("postgresql://db.example.invalid"), { PGHOST: HOST });
  assert.deepEqual(libpqEnvFromUrl("postgresql://%2Fvar%2Frun%2FPg/jobs"), { PGHOST: "/var/run/Pg", PGDATABASE: "jobs" });
});

test("libpqEnvFromUrl：认不出的参数 / 解析失败都报错，但报错里不带连接串的任何片段", () => {
  const bad = [
    `postgresql://jobs_user:${RAW_PW}@${HOST}:6543/jobs?keepalives=1`,
    `postgresql://jobs_user:${RAW_PW}@${HOST}:notaport/jobs`,
    `postgresql://jobs_user:${RAW_PW}@${HOST}:6543,${HOSTADDR}:6543/jobs`,
    `mysql://jobs_user:${RAW_PW}@${HOST}/jobs`,
  ];
  for (const u of bad) {
    let err;
    try {
      libpqEnvFromUrl(u);
    } catch (e) {
      err = e;
    }
    assert.ok(err, `应当报错：第 ${bad.indexOf(u)} 个`);
    assert.equal(err.input, undefined, "不许透传 ERR_INVALID_URL（它把整条输入挂在 err.input 上）");
    assertNoSecrets(util.inspect(err), "报错对象");
  }
});

test("runPsql：argv 里没有连接串，密码经 PGPASSWORD 传入；URL 覆盖环境、没写的项由环境兜底", () => {
  const bin = fakePsql();
  const out = JSON.parse(
    runPsql(["-t", "-A", "-c", "select 1"], {
      url: `postgresql://jobs_user:${RAW_PW}@${HOST}:6543/jobs`,
      bin,
      env: { PATH: process.env.PATH, PGSSLMODE: "require", PGPORT: "1" },
    }),
  );
  assert.deepEqual(out.argv, ["-t", "-A", "-c", "select 1"]);
  assertNoSecrets(JSON.stringify(out.argv), "argv");
  assert.equal(out.pg.PGPASSWORD, PW);
  assert.equal(out.pg.PGPORT, "6543", "URL 里写了端口就覆盖环境");
  assert.equal(out.pg.PGSSLMODE, "require", "URL 没写 sslmode 时仍用环境里的");
});

test("runPsql：psql 失败时报错只含脱敏后的 stderr，报错对象里找不到密码 / 主机 / 连接串", () => {
  const bin = fakePsql();
  let err;
  try {
    runPsql(["-c", "select 1"], { url: URL_, bin, env: { PATH: process.env.PATH, FAKE_PSQL_MODE: "fail" } });
  } catch (e) {
    err = e;
  }
  assert.ok(err, "应当报错");
  assert.match(err.message, /退出码 2/);
  assert.match(err.message, /<redacted>/);
  assert.match(err.message, /timeout expired/, "stderr 里有用的部分要留着");
  assertNoSecrets(err.message, "message");
  assertNoSecrets(util.inspect(err, { showHidden: true, depth: 5 }), "报错对象");
  assertNoSecrets(JSON.stringify(err), "报错对象（JSON）");
});

test("runPsql：成功时转发的 stderr（NOTICE）也先脱敏", () => {
  const bin = fakePsql();
  const writes = [];
  const orig = process.stderr.write;
  process.stderr.write = (chunk) => { writes.push(String(chunk)); return true; };
  try {
    runPsql(["-c", "select 1"], { url: URL_, bin, env: { PATH: process.env.PATH, FAKE_PSQL_MODE: "notice" } });
  } finally {
    process.stderr.write = orig;
  }
  assert.ok(writes.join("").includes("NOTICE: talking to <redacted>"));
  assertNoSecrets(writes.join(""), "转发的 stderr");
});

test("runPsql：调用方把连接串 / 密码塞进参数，spawn 之前就拒绝", () => {
  for (const args of [[URL_, "-c", "select 1"], ["-d", `postgres://u:${RAW_PW}@${HOST}/jobs`], ["-c", `select '${PW}'`]]) {
    let err;
    try {
      runPsql(args, { url: URL_, bin: "/nonexistent/should-not-run" });
    } catch (e) {
      err = e;
    }
    assert.ok(err);
    assert.match(err.message, /不许出现连接串或密码/);
    assertNoSecrets(util.inspect(err), "报错对象");
  }
});

test("runPsql：psql 不存在 / 连接串没配，报错同样干净", () => {
  let err;
  try {
    runPsql(["-c", "select 1"], { url: URL_, bin: path.join(os.tmpdir(), "no-such-psql-binary") });
  } catch (e) {
    err = e;
  }
  assert.match(err.message, /ENOENT/);
  assert.equal(err.spawnargs, undefined);
  assertNoSecrets(util.inspect(err, { showHidden: true }), "报错对象");
  assert.throws(() => runPsql(["-c", "select 1"], { url: "" }), /未配置/);
});

test("redact：长的先替换，密码原文与解码后都抹掉", () => {
  const s = redact(`raw=${RAW_PW} dec=${PW} url=${URL_} host=${HOST}`, URL_);
  assertNoSecrets(s, "redact 输出");
});

test("PARAM_ENV 与 Python 侧 crawler/psql_env.py 逐条一致", () => {
  const py = fs.readFileSync(path.join(__dirname, "..", "crawler", "psql_env.py"), "utf8");
  const block = py.slice(py.indexOf("PARAM_ENV = {"), py.indexOf("}", py.indexOf("PARAM_ENV = {")));
  const pyMap = Object.fromEntries([...block.matchAll(/"(\w+)":\s*"(PG\w+)"/g)].map((m) => [m[1], m[2]]));
  assert.deepEqual(pyMap, { ...PARAM_ENV });
});

// 防回归：仓库里任何地方都不许再把连接串当 psql 的参数（只允许走 scripts/lib/psql.js / crawler/psql_env.py）。
test("契约：scripts/ lib/ app/ crawler/ 里没有直接 spawn psql 的调用", () => {
  const ROOT = path.join(__dirname, "..");
  const hits = [];
  // 两个助手自己的注释里引用了旧写法，本身不 spawn 带连接串的 psql。
  const ALLOWED = new Set(["scripts/lib/psql.js", "crawler/psql_env.py"]);
  const JS_SPAWN_PSQL = /\b(?:execFileSync|execFile|spawnSync|spawn|execSync|exec)\(\s*(?:["'`]psql\b|`[^`]*\bpsql\s)/;
  const PY_SPAWN_PSQL = /subprocess\.\w+\(\s*\[\s*["']psql["']/;
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) walk(p);
      else if (/\.(c?js|mjs|ts|tsx)$/.test(ent.name) && JS_SPAWN_PSQL.test(fs.readFileSync(p, "utf8"))) hits.push(path.relative(ROOT, p));
      else if (/\.py$/.test(ent.name) && !/^test_/.test(ent.name) && PY_SPAWN_PSQL.test(fs.readFileSync(p, "utf8"))) hits.push(path.relative(ROOT, p));
    }
  };
  for (const d of ["scripts", "lib", "app", "crawler"]) walk(path.join(ROOT, d));
  assert.deepEqual(hits.filter((h) => !ALLOWED.has(h)), [], "改用 scripts/lib/psql.js 的 runPsql（Python：crawler/psql_env.run_psql）");
});
