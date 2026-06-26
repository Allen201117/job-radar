// 服务端专用：自建香港 jobs 库的 PostgreSQL 连接池（Phase 1，jobs-store 边界）。
// 仅 server（API route / RSC / server action）用 —— 绝不能进客户端 bundle（含 JOBS_DATABASE_URL）。
import "server-only";
import { Pool, types, type QueryResultRow } from "pg";

// ⚠️ 根因修复（2026-06-26 生产事故）：node-pg 默认把 timestamptz(OID 1184)/timestamp(1114) 解析成 JS **Date 对象**，
// 而全库代码（含 Supabase/PostgREST 路径）一律假设这些时间列是 **ISO 字符串**（`new Date(str)` / `String(str)` /
// `(firstSeenAt||"").localeCompare(...)` 直接字符串比较）。Date 没有 .localeCompare → 机会 Feed 的
// `grouping.ts` 排序在生产抛 `TypeError: (t.firstSeenAt||"").localeCompare is not a function` → buildOpportunityFeed
// 抛 → today 页「机会队列暂时无法更新」。（本地 psycopg2/单测用字符串日期，掩盖了此 bug，只有真 node-pg→香港库才暴露。）
// 让 node-pg 返回**原始字符串**，与 Supabase 同口径，全链路按字符串处理 → 一处修，全表时间列免疫。
types.setTypeParser(1184, (v) => v); // timestamptz
types.setTypeParser(1114, (v) => v); // timestamp (无时区)

// 全局复用连接池：Vercel serverless 跨调用复用同一池，避免每次新建连接（连接风暴）。
const globalForPool = globalThis as unknown as { __jobsPool?: Pool };

function makePool(): Pool {
  const url = process.env.JOBS_DATABASE_URL;
  if (!url) {
    throw new Error("JOBS_DATABASE_URL 未配置（自建香港 jobs 库连接串）");
  }
  // ⚠️ 不能直接传 connectionString：node-pg 的 pg-connection-string 把 URL 里的 sslmode=require 当成
  //   verify-full（校验 CA）→ 拒掉自建库的自签证书（"self-signed certificate"），覆盖掉 ssl 选项。
  //   故解析成显式字段 + 显式 ssl:{rejectUnauthorized:false}（加密但不校验，自签库正确做法）。
  const u = new URL(url);
  const pool = new Pool({
    host: u.hostname,
    port: u.port ? Number(u.port) : 5432,
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    database: u.pathname.replace(/^\//, "") || "jobradar_jobs",
    ssl: { rejectUnauthorized: false },
    max: 5,
    idleTimeoutMillis: 10_000,
    connectionTimeoutMillis: 8_000,
    // 跨区（Vercel→香港）大结果集传输会占 statement_timeout（服务器发送被慢客户端阻塞也计时）。给 25s 防御余量
    // （正常召回 1500 行实测 3s，远不到顶）。注：这**不是** 2026-06-26 503 的根因（真因见上面 type parser），仅防御。
    // 消费方页/路由 maxDuration 须 ≥ 此值，否则函数先被平台杀、错误不被 catch（白屏而非降级提示）。
    statement_timeout: 25_000,
  });
  // 失效连接（ETIMEDOUT / Connection terminated unexpectedly）会触发 idle client error。
  // 挂 handler：pg 会驱逐这条坏连接、进程不崩，避免坏连接长期留在池里导致后续请求持续失败（P0-1 §7）。
  pool.on("error", (err) => {
    console.warn("[jobs-pool] idle client error (connection evicted):", err.message);
  });
  return pool;
}

export function jobsPool(): Pool {
  if (!globalForPool.__jobsPool) {
    globalForPool.__jobsPool = makePool();
  }
  return globalForPool.__jobsPool;
}

/** 跑一条参数化 SQL，返回行数组。 */
export async function jobsQuery<T extends QueryResultRow = QueryResultRow>(
  sql: string,
  params: unknown[] = [],
): Promise<T[]> {
  const res = await jobsPool().query<T>(sql, params as any[]);
  return res.rows;
}

/** 标量查询（count 等），取第一行第一列。 */
export async function jobsScalar<T = unknown>(sql: string, params: unknown[] = []): Promise<T | null> {
  const rows = await jobsQuery(sql, params);
  if (!rows.length) return null;
  const first = rows[0] as Record<string, unknown>;
  const keys = Object.keys(first);
  return keys.length ? (first[keys[0]] as T) : null;
}
