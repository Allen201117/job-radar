// 服务端专用：自建香港 jobs 库的 PostgreSQL 连接池（Phase 1，jobs-store 边界）。
// 仅 server（API route / RSC / server action）用 —— 绝不能进客户端 bundle（含 JOBS_DATABASE_URL）。
import "server-only";
import { Pool, types, type QueryResultRow } from "pg";
import { buildJobsDatabaseSsl } from "./tls-options.js";

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
  // 不能直接传 connectionString：URL 内的 sslmode 会覆盖显式 TLS 选项。
  // 因此拆成连接字段，并强制使用受控 CA + 证书服务器名做完整验证。
  const u = new URL(url);
  const pool = new Pool({
    host: u.hostname,
    port: u.port ? Number(u.port) : 5432,
    user: decodeURIComponent(u.username),
    password: decodeURIComponent(u.password),
    database: u.pathname.replace(/^\//, "") || "jobradar_jobs",
    ssl: buildJobsDatabaseSsl(process.env, u.hostname),
    // 保持 5。2026-09-03 一度改成 2（想省连接位），当天又改回来——**但不是因为它有问题，
    // 而是因为改小根本没解决任何现存瓶颈**，详见下面实测。没有新证据前不要再动这个值。
    //
    // 当天的实测结论（用可靠链路复测得到，可直接引用）：
    //   · 20 并发打 /api/jobs/search：**20/20 全部 200**，p50 1.7s、最慢 12.3s，零错误。
    //   · 压测**进行中**查库：连接只到 **32/100、活跃查询 1 个** → 这个并发级别下
    //     **数据库几乎没在干活，连接更远没打满**，瓶颈在函数侧（每请求要把几千行候选拉进
    //     函数、按 (岗位 × 关键词) 打分），且每个实例的候选缓存是各存各的、冷实例必然重拉。
    //   → 所以「缩函数池省连接位」当前是在解一个不存在的问题；真要扛量应做
    //     **候选缓存跨实例共享**，其次才是 CI 爬虫限并发（撞档时爬虫侧占 ~73/100）。
    //
    // ⚠️ 排查纪律：当天曾从本机 curl 测出「20/20 返 500、卡 52s」并据此误判成事故——
    // 真相是**本机 HTTP 代理正在挂**（同一时刻 git push 报 SSL_ERROR、curl 也返 000），
    // 代理故障会伪装成服务端 500。**压测结论必须用可靠链路复核，别拿本机代理的报错当生产故障。**
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

/**
 * 带事务级参数跑一条只读 SQL：`set local` 只在这一个事务里生效，连接还回池子后不留痕迹
 * （直接 `set` 会留在那条连接上，之后轮到它的别的查询跟着变，而且各连接不一致）。
 * settings 的名和值会拼进 SQL，只许传代码里写死的常量。
 */
export async function jobsQueryWithLocalSettings<T extends QueryResultRow = QueryResultRow>(
  sql: string,
  params: unknown[],
  settings: Record<string, number>,
): Promise<T[]> {
  for (const [name, value] of Object.entries(settings)) {
    if (!/^[a-z_]+$/.test(name) || !Number.isInteger(value)) {
      throw new Error(`jobsQueryWithLocalSettings：参数 ${name} 不合法`);
    }
  }
  const client = await jobsPool().connect();
  // 借出期间连接断掉（库重启 / 被 kill / 网络断），驱动会在 client 上发 'error' 事件，而池子在借出时已经摘掉了自己的监听；
  // 没人接的话 Node 把它当未捕获异常，整个函数实例连同别的在途请求一起挂。正在跑的那条查询会另外收到这个错、走下面的 catch。
  const onClientError = (err: Error) => {
    console.warn("[jobs-pool] checked-out client error:", err.message);
  };
  client.on("error", onClientError);
  let failed = false;
  try {
    await client.query("begin read only");
    for (const [name, value] of Object.entries(settings)) {
      await client.query(`set local ${name} = ${value}`);
    }
    const res = await client.query<T>(sql, params as any[]);
    await client.query("commit");
    return res.rows;
  } catch (e) {
    failed = true;
    await client.query("rollback").catch((rollbackError: Error) => {
      // 连接多半已经断了；这条连接反正要销毁，记一笔就行，抛出去的仍是原来那个错
      console.warn("[jobs-pool] rollback 失败（连接将销毁）:", rollbackError.message);
    });
    throw e;
  } finally {
    client.removeListener("error", onClientError);
    // 出过错的连接直接销毁，不还回池子（可能还停在事务里）
    client.release(failed);
  }
}

/** 标量查询（count 等），取第一行第一列。 */
export async function jobsScalar<T = unknown>(sql: string, params: unknown[] = []): Promise<T | null> {
  const rows = await jobsQuery(sql, params);
  if (!rows.length) return null;
  const first = rows[0] as Record<string, unknown>;
  const keys = Object.keys(first);
  return keys.length ? (first[keys[0]] as T) : null;
}
