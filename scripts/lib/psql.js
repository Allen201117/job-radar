"use strict";
/**
 * 脚本直连 jobs 库的 psql 调用助手（Python 侧同口径：crawler/psql_env.py）。
 *
 * 🚫 连接串绝不放进 psql 的命令行参数（2026-09-24 立）：
 * ❌ 旧写法 `execFileSync("psql", [process.env.JOBS_DATABASE_URL, ...])`：
 *    ① 带密码的连接串出现在 `ps` / `pgrep -f` 里，本机任何用户都看得见；
 *    ② psql 一失败（比如连接超时），Node 的报错 message 就是 "Command failed: psql <完整 argv>"，
 *       密码跟着进日志 / CI 输出 / 会话记录（2026-09-23 一个照抄此写法的本地对拍脚本真泄露过）。
 * ✅ 拆成 libpq 环境变量（PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE，查询参数按 libpq 官方
 *    对照表转成 PGSSLMODE / PGSSLROOTCERT / PGHOSTADDR …）经 env 传给 psql，psql 的参数里不带连接串。
 *    失败时只用**脱敏后的 stderr** 另造一个 Error——原始 error 的 message 与 spawnargs 都带 argv，绝不透传。
 *
 * 语义与「把 URL 当第一个参数」一致：URL 里写了的项覆盖环境里的同名 PG* 变量，没写的项仍由环境兜底
 * （CI 里 enable-jobs-db-strict-tls.sh 那类「环境给 sslmode」的用法不受影响）。
 * 认不出的查询参数直接报错（只报参数名）：悄悄丢掉 sslmode 这类参数会静默降低连接的安全级别。
 *
 * 用法：
 *   const { runPsql } = require("../lib/psql.js");
 *   const out = runPsql(["-t", "-A", "-c", sql], { maxBuffer: 512 * 1024 * 1024 });
 */

const { spawnSync } = require("child_process");

// libpq 连接参数 → 环境变量（PostgreSQL 文档「Environment Variables」一节的官方对照表）。
// 没有对应环境变量的参数（keepalives*、tcp_user_timeout、replication…）刻意不收，遇到就报错。
const PARAM_ENV = Object.freeze({
  host: "PGHOST",
  hostaddr: "PGHOSTADDR",
  port: "PGPORT",
  dbname: "PGDATABASE",
  user: "PGUSER",
  password: "PGPASSWORD",
  passfile: "PGPASSFILE",
  require_auth: "PGREQUIREAUTH",
  channel_binding: "PGCHANNELBINDING",
  service: "PGSERVICE",
  options: "PGOPTIONS",
  application_name: "PGAPPNAME",
  sslmode: "PGSSLMODE",
  requiressl: "PGREQUIRESSL",
  sslnegotiation: "PGSSLNEGOTIATION",
  sslcompression: "PGSSLCOMPRESSION",
  sslcert: "PGSSLCERT",
  sslkey: "PGSSLKEY",
  sslcertmode: "PGSSLCERTMODE",
  sslrootcert: "PGSSLROOTCERT",
  sslcrl: "PGSSLCRL",
  sslcrldir: "PGSSLCRLDIR",
  sslsni: "PGSSLSNI",
  requirepeer: "PGREQUIREPEER",
  ssl_min_protocol_version: "PGSSLMINPROTOCOLVERSION",
  ssl_max_protocol_version: "PGSSLMAXPROTOCOLVERSION",
  min_protocol_version: "PGMINPROTOCOLVERSION",
  max_protocol_version: "PGMAXPROTOCOLVERSION",
  gssencmode: "PGGSSENCMODE",
  krbsrvname: "PGKRBSRVNAME",
  gsslib: "PGGSSLIB",
  gssdelegation: "PGGSSDELEGATION",
  connect_timeout: "PGCONNECT_TIMEOUT",
  client_encoding: "PGCLIENTENCODING",
  target_session_attrs: "PGTARGETSESSIONATTRS",
  load_balance_hosts: "PGLOADBALANCEHOSTS",
});

const URL_RE = /^postgres(?:ql)?:\/\//i;

// 报错里只许出现参数名 / 固定文案，不许出现 URL 的任何片段。
function decodeOrThrow(s, what) {
  try {
    return decodeURIComponent(s);
  } catch {
    throw new Error(`数据库连接串的 ${what} 不是合法的百分号编码`);
  }
}

/** 连接串 → { PGHOST, PGPORT, ... }，只含 URL 里真写了的项。 */
function libpqEnvFromUrl(url) {
  if (typeof url !== "string" || !URL_RE.test(url)) {
    throw new Error("数据库连接串必须是 postgres:// 或 postgresql:// 开头");
  }
  let u;
  try {
    u = new URL(url);
  } catch {
    // ⚠️ 不能透传：Node 的 ERR_INVALID_URL 把整条输入挂在 err.input 上，打印 error 对象就带出密码。
    throw new Error("数据库连接串解析失败（格式不对；多主机写法请改用 PGHOST 环境变量）");
  }
  const env = {};
  if (u.username) env.PGUSER = decodeOrThrow(u.username, "用户名");
  if (u.password) env.PGPASSWORD = decodeOrThrow(u.password, "密码");
  let host = u.hostname;
  if (host.includes(",")) throw new Error("数据库连接串是多主机写法，请改用 PGHOST 环境变量");
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  if (host) env.PGHOST = decodeOrThrow(host, "主机");
  if (u.port) env.PGPORT = u.port;
  const db = u.pathname.replace(/^\//, "");
  if (db) env.PGDATABASE = decodeOrThrow(db, "库名");
  // 不用 URLSearchParams：它把 + 解成空格，libpq 只做百分号解码。
  for (const pair of u.search.replace(/^\?/, "").split("&")) {
    if (!pair) continue;
    const eq = pair.indexOf("=");
    const key = decodeOrThrow(eq < 0 ? pair : pair.slice(0, eq), "查询参数名");
    const value = eq < 0 ? "" : decodeOrThrow(pair.slice(eq + 1), `查询参数 ${key}`);
    const name = PARAM_ENV[key];
    if (!name) throw new Error(`数据库连接串里的参数 ${key} 没有对应的 libpq 环境变量，请从连接串里去掉或改用环境变量`);
    env[name] = value;
  }
  return env;
}

/** 输出里可能出现的敏感片段（密码原文 / 解码后、主机、整条 URL），长的在前，避免先替掉子串。 */
function secretsOf(url) {
  const out = new Set([url]);
  try {
    const u = new URL(url);
    if (u.password) out.add(u.password);
    const env = libpqEnvFromUrl(url);
    for (const k of ["PGPASSWORD", "PGHOST", "PGHOSTADDR"]) if (env[k]) out.add(env[k]);
  } catch {
    // 解析不了的连接串在 runPsql 入口已经报过错，这里只尽力而为。
  }
  return [...out].filter(Boolean).sort((a, b) => b.length - a.length);
}

/** 把文本里的连接串 / 密码 / 主机替换成占位符（主机 IP 同样不许进公开仓的 CI 日志）。 */
function redact(text, url) {
  let s = String(text || "");
  if (!url) return s;
  for (const secret of secretsOf(url)) s = s.split(secret).join("<redacted>");
  return s;
}

/**
 * 跑一次 psql，返回 stdout（encoding="buffer" 时返回 Buffer）。
 * opts: { url（默认 JOBS_DATABASE_URL）, encoding, maxBuffer, input, timeout, env（基础环境，默认 process.env）, bin（测试用） }
 */
function runPsql(args, opts = {}) {
  const url = opts.url ?? process.env.JOBS_DATABASE_URL;
  if (!url) throw new Error("JOBS_DATABASE_URL 未配置（先 source .env.local）");
  if (!Array.isArray(args)) throw new Error("runPsql 的参数必须是数组");
  const pgEnv = libpqEnvFromUrl(url);
  // 防回归：调用方照老习惯把连接串塞进参数，当场拒绝，别让它带着密码跑出去。
  // 密码太短时不按子串查（会误伤正常 SQL），连接串本身仍然拦。
  const pw = pgEnv.PGPASSWORD && pgEnv.PGPASSWORD.length >= 8 ? pgEnv.PGPASSWORD : null;
  if (args.some((a) => typeof a === "string" && (URL_RE.test(a) || a.includes(url) || (pw && a.includes(pw))))) {
    throw new Error("psql 参数里不许出现连接串或密码（连接信息已经通过环境变量传入）");
  }
  const encoding = opts.encoding || "utf8";
  const r = spawnSync(opts.bin || "psql", args, {
    env: { ...(opts.env || process.env), ...pgEnv },
    encoding,
    maxBuffer: opts.maxBuffer ?? 64 * 1024 * 1024,
    input: opts.input,
    timeout: opts.timeout,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const stderr = redact(Buffer.isBuffer(r.stderr) ? r.stderr.toString("utf8") : r.stderr, url).trim();
  if (r.error) {
    // r.error.message / r.error.spawnargs 都带完整 argv → 只取错误码。
    const code = r.error.code || "unknown";
    const hint = code === "ENOENT" ? "（本机没装 psql？）" : code === "ENOBUFS" ? "（输出超过 maxBuffer）" : "";
    throw new Error(`psql 没能跑完：${code}${hint}${stderr ? `\n${stderr}` : ""}`);
  }
  if (r.status !== 0) {
    const how = r.status === null ? `被信号 ${r.signal} 终止` : `退出码 ${r.status}`;
    throw new Error(`psql 失败（${how}）${stderr ? `：\n${stderr}` : ""}`);
  }
  // 成功时的 NOTICE / WARNING 照样给人看（execFileSync 旧行为会转发 stderr），但先脱敏。
  if (stderr) process.stderr.write(`${stderr}\n`);
  return r.stdout;
}

module.exports = { PARAM_ENV, libpqEnvFromUrl, redact, runPsql };
