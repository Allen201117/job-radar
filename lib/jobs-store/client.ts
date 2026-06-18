// 服务端专用：自建香港 jobs 库的 PostgreSQL 连接池（Phase 1，jobs-store 边界）。
// 仅 server（API route / RSC / server action）用 —— 绝不能进客户端 bundle（含 JOBS_DATABASE_URL）。
// app 的 jobs 读取从 supabase-js 迁到这里：jobs 已搬到自建香港 PG（无 PostgREST），用直连 SQL。
// sources / auth / 用户小表仍走 Supabase（lib/supabaseClient）。
import "server-only";
import { Pool, type QueryResultRow } from "pg";

// 全局复用连接池：Vercel serverless 跨调用复用同一池，避免每次新建连接（连接风暴）。
const globalForPool = globalThis as unknown as { __jobsPool?: Pool };

function makePool(): Pool {
  const connectionString = process.env.JOBS_DATABASE_URL;
  if (!connectionString) {
    throw new Error("JOBS_DATABASE_URL 未配置（自建香港 jobs 库连接串）");
  }
  return new Pool({
    connectionString,
    // 自建库用自签 SSL（连接串 sslmode=require）：加密但不校验 CA → rejectUnauthorized:false。
    ssl: { rejectUnauthorized: false },
    max: 5, // serverless 小池
    idleTimeoutMillis: 10_000,
    connectionTimeoutMillis: 8_000,
    statement_timeout: 15_000, // 单查询保护（香港库专供 jobs，重活已建索引）
  });
}

export function jobsPool(): Pool {
  if (!globalForPool.__jobsPool) {
    globalForPool.__jobsPool = makePool();
  }
  return globalForPool.__jobsPool;
}

/** 跑一条参数化 SQL，返回行数组。统一入口，方便加日志/超时/重试。 */
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
  return (keys.length ? (first[keys[0]] as T) : null);
}
