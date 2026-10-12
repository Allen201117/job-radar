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

// 本池每条连接的预读并发（effective_io_concurrency，2026-10-12 实测后定，创始人拍板「连接池带上、取 64」）。
// ❌ 库上是默认值 1：「先从索引拿到一批行的位置、再回表逐块读」（位图堆扫描）时一次只等一块盘读。
//    数据不在缓存里，每读一块 0.15ms（真从盘上读 0.2~0.45ms）—— /today 现跑召回、/jobs 登录搜索取候选冷的时候几秒就是这么来的。
// ✅ 调大后位图堆扫描会把后面要读的块提前一起发给磁盘。四轮实测（51 个真实用户的召回 SQL + 56 种真实搜索 + 36 城，
//    每个输入在四种设置下各跑一次，每种设置读块合计 81~83 万；库内 EXPLAIN ANALYZE，冷跑）：
//      每读一块   1 → 0.149ms · 16 → 0.046 · 64 → 0.033 · 200 → 0.028
//      /today 现跑召回（51 人） 中位 0.76s → 0.26s，九成内 4.1s → 1.3s，合计 82.6s → 27.1s
//      /jobs 登录搜索取候选（38~40 种） 中位 0.39s → 0.17s，九成内 3.6s → 0.73s，合计 34.4s → 11.4s
//    取 64：比 16 现跑召回合计再少 31%，200 比 64 没有更多收益。
// ⚠️ 它只管位图堆扫描「取堆块」那一段。吃不到的：索引扫描（/today 线上走的读快照、匿名默认态、北京这类大城市按时间索引顺扫、
//    回补 60 行）、位图**索引**页自己的读（GIN 页 / 主键叶子页）、全表顺扫的计数、纯计算。别指望它治这些。
// ⚠️ 规划器不看它：171 条真实 SQL 按 1 / 200 / 1 / 200 各 EXPLAIN 一次，计划随设置变的 0 条；数据在缓存里时耗时比值 0.99~1.03。
// ⚠️ 对别的会话：有预读查询在跑时，别人读一块超过 1ms 的比例 1.3% → 3~6%（最慢 1% 从 1.1ms 到 2.1~2.7ms），中位 / 九成不变，
//    在等磁盘 / 等写日志的会话数没变多（旁路采样 3.5 万次，含爬虫重度写库 + 三条冷查询同时跑）。
//    没量：大量用户同时冷查询的叠加；爬虫侧也开预读（改角色 / 库级配置）—— 那是另一件事，要改先量。
// 只影响本池的连接（应用查询 + 用本文件的脚本，如 /today 召回快照的后台刷新）；爬虫（psycopg2）和自建连接的脚本不受影响。
// 完整数字与测法：docs/reviews/2026-10-12-effective-io-concurrency.md
export const JOBS_IO_CONCURRENCY = 64;

/**
 * 连接启动参数（libpq 的 options）：建连接时就把预读并发设好，不占一次往返，也不会像 `set` 那样只落在某几条连接上。
 * 环境变量 JOBS_DB_IO_CONCURRENCY：`off` = 我们不带这个参数（退回库的默认值；驱动此时会读进程里的 PGOPTIONS，线上没设）；
 * 1~1000 的十进制整数 = 改用这个值；其它写法一律按默认值——一个手滑的环境变量不该让所有连接都建不起来（库会拒绝非法取值）。
 * 返回值只由校验过的数字重新拼出来，环境变量原文不进启动参数。
 */
export function jobsSessionOptions(env: Record<string, string | undefined> = process.env): string | undefined {
  const raw = (env.JOBS_DB_IO_CONCURRENCY ?? "").trim().toLowerCase();
  if (raw === "off") return undefined;
  let value = JOBS_IO_CONCURRENCY;
  if (raw) {
    // 只认纯数字：Number("1e2") / Number("0x10") 也是整数，但那不是人会有意写的值
    const parsed = /^\d{1,4}$/.test(raw) ? Number(raw) : NaN;
    if (parsed >= 1 && parsed <= 1000) value = parsed;
    else console.warn(`[jobs-pool] JOBS_DB_IO_CONCURRENCY 不是 off 或 1~1000 的整数，按默认值 ${JOBS_IO_CONCURRENCY}`);
  }
  return `-c effective_io_concurrency=${value}`;
}

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
    options: jobsSessionOptions(),
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
