// 服务端专用：自建香港 jobs 库的写入（Phase 1，jobs-store 边界）。仅 app 的次要刷新路由用
//（discovery 官方源发现 / search 已知源刷新 / enrich 按需富化）；爬虫端写入走 crawler/jobs_db.py。
//
// 镜像 crawler/jobs_db.upsert_job 的 canonical-based upsert：按 canonical_jd_url 跨状态查既有行
//（多行优先 active）→ 命中即按同一行 id update（复活 removed 漏看岗、保住 job_actions 外键引用；
//  expired=detail 探活确认撤岗，重抓不复活它 → 见 updateById 的 status CASE）、
// 否则 insert；撞 active-canonical 部分唯一键（jobs-db/schema.sql）退回重查 update（并发幂等兜底）。
// canonical_jd_url / search_doc 由 HK 触发器自动维护，写入端不带——这里只用同口径 canonicalizeJdUrl
// 算 canon 来**查**既有行（与 crawler/normalizer.py + schema.sql 的 SQL 函数字节一致）。
import "server-only";
import { jobsQuery } from "./client";
import { JOB_COLUMNS } from "./types";
import canonicalUrl from "@/lib/canonical-url";
import geo from "@/lib/geo";
import sponsorship from "@/lib/sponsorship";

const { canonicalizeJdUrl } = canonicalUrl as {
  canonicalizeJdUrl: (u: string | null | undefined) => string | null;
};
const { deriveCountryCode, deriveJobScope } = geo as {
  deriveCountryCode: (location: string | null | undefined) => string | null;
  deriveJobScope: (location: string | null | undefined) => "domestic" | "overseas";
};
const { sponsorshipSignal } = sponsorship as {
  sponsorshipSignal: (text: string | null | undefined) => "available" | "none" | "unknown";
};

// insert 数据列（值取自 job，缺省 null）；canonical_jd_url/search_doc 由触发器维护、id/时间/状态/计数走字面量。
const INSERT_DATA_COLS = [
  "source_id", "company", "title", "location", "country_code", "job_scope", "job_type", "summary", "jd_url",
  "apply_url", "salary_text", "posted_at", "content_hash", "experience", "education", "deadline", "sponsorship_signal",
] as const;
// update 数据列：刷新 live 重抓提供的基础字段 + location 派生 geo 字段；不碰 source_id / jd_url /
// experience / education / deadline / first_seen_at，避免把爬虫/富化已填字段清空。
const UPDATE_DATA_COLS = [
  "company", "title", "location", "country_code", "job_scope", "job_type", "summary",
  "apply_url", "salary_text", "posted_at", "content_hash", "sponsorship_signal",
] as const;
// 这些富化字段在 UPDATE 时新值为空则保留旧值（COALESCE(NULLIF(...))），与 crawler/jobs_db._PRESERVE_IF_EMPTY 同口径：
// app 的 discovery/search 刷新多只带列表骨架（无 JD 正文）→ 不得把浏览器/httpx 富化补好的 summary 抹成 NULL。
const PRESERVE_IF_EMPTY = new Set<string>(["summary", "job_type", "salary_text"]);

export type UpsertResult = { row: any; action: "created" | "updated" };

function withDerivedFields(job: Record<string, any>): Record<string, any> {
  return {
    ...job,
    country_code: job.country_code ?? deriveCountryCode(job.location),
    job_scope: job.job_scope ?? deriveJobScope(job.location),
    sponsorship_signal:
      job.sponsorship_signal ?? sponsorshipSignal([job.title, job.summary].filter(Boolean).join(" ")),
  };
}

async function findIdByCanonical(canon: string | null): Promise<string | null> {
  if (!canon) return null;
  const rows = await jobsQuery<{ id: string; status: string }>(
    "select id, status from jobs where canonical_jd_url = $1",
    [canon],
  );
  if (!rows.length) return null;
  const active = rows.find((r) => r.status === "active");
  return active ? active.id : rows[0].id;
}

async function updateById(id: string, job: Record<string, any>): Promise<any | null> {
  const setParts = UPDATE_DATA_COLS.map((c, i) =>
    PRESERVE_IF_EMPTY.has(c) ? `${c} = COALESCE(NULLIF($${i + 1}, ''), ${c})` : `${c} = $${i + 1}`);
  // expired = detail 探活确认撤岗的强信号；列表/发现重抓不得复活它（否则点开 404/已下线）。
  // 与 crawler/jobs_db._update_set_clause 的 status CASE 同口径：expired 黏住，removed/active 仍刷 active。
  setParts.push("status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE 'active' END", "last_seen_at = now()");
  const sql =
    `update jobs set ${setParts.join(", ")} where id = $${UPDATE_DATA_COLS.length + 1}::uuid returning ${JOB_COLUMNS}`;
  const vals = [...UPDATE_DATA_COLS.map((c) => job[c] ?? null), id];
  const rows = await jobsQuery(sql, vals);
  return rows[0] ?? null;
}

async function insertNew(job: Record<string, any>): Promise<any | null> {
  const cols = ["id", ...INSERT_DATA_COLS, "status", "enrich_fail_count", "first_seen_at", "last_seen_at"];
  const ph = [
    "gen_random_uuid()",
    ...INSERT_DATA_COLS.map((_, i) => `$${i + 1}`),
    "'active'", "0", "now()", "now()",
  ];
  const sql = `insert into jobs (${cols.join(", ")}) values (${ph.join(", ")}) returning ${JOB_COLUMNS}`;
  const rows = await jobsQuery(sql, INSERT_DATA_COLS.map((c) => job[c] ?? null));
  return rows[0] ?? null;
}

/** 单条 upsert 到香港库（canonical 冲突键，复活语义同 crawler）。返回写后整行 + created/updated；失败返回 null。 */
export async function upsertJob(job: Record<string, any>): Promise<UpsertResult | null> {
  job = withDerivedFields(job);
  const canon = canonicalizeJdUrl(job.jd_url);
  const existingId = await findIdByCanonical(canon);
  if (existingId) {
    const row = await updateById(existingId, job);
    return row ? { row, action: "updated" } : null;
  }
  try {
    const row = await insertNew(job);
    return row ? { row, action: "created" } : null;
  } catch (e: any) {
    // 并发下撞 active-canonical 唯一键(23505) → 按 canonical 重查命中转 update（幂等兜底，同 jobs_db.upsert_job）
    if (e?.code === "23505") {
      const again = await findIdByCanonical(canon);
      if (again) {
        const row = await updateById(again, job);
        return row ? { row, action: "updated" } : null;
      }
    }
    throw e;
  }
}

/** 按 id 补 summary（enrich 按需富化写回）。返回是否命中一行。 */
export async function updateJobSummaryById(id: string, summary: string): Promise<boolean> {
  const rows = await jobsQuery(
    "update jobs set summary = $1, enrich_checked_at = now() where id = $2::uuid returning id",
    [summary, id],
  );
  return rows.length > 0;
}

// job_events best-effort 写入（与 crawler/jobs_db.record_job_events 同口径；02 spec §5/§9）：
// append-only 里程碑，event_key 幂等去重；写失败只 warning，**绝不影响主写入**。
async function recordJobEvent(
  eventKey: string,
  eventType: string,
  jobId: string,
  sourceId: string | null,
): Promise<void> {
  try {
    await jobsQuery(
      "insert into job_events (event_key, event_type, job_id, source_id, payload) " +
        "values ($1, $2, $3::uuid, $4, '{}'::jsonb) on conflict (event_key) do nothing",
      [eventKey, eventType, jobId, sourceId],
    );
  } catch (e) {
    console.warn("[job_events] insert failed (ignored):", (e as Error).message);
  }
}

function utcDay(): string {
  return new Date().toISOString().slice(0, 10);
}

/** 点击时校验门：探活确认撤岗 → 置 expired + 盖探活戳 + 记确认下架时刻（仅当前还是 active 才动；幂等）。 */
export async function markJobExpiredById(id: string): Promise<boolean> {
  const rows = await jobsQuery<{ id: string; source_id: string | null }>(
    "update jobs set status = 'expired', enrich_checked_at = now(), confirmed_closed_at = now() " +
      "where id = $1::uuid and status = 'active' returning id, source_id",
    [id],
  );
  if (!rows.length) return false;
  // 确认下架 → CLOSED 里程碑（按天去重）。best-effort，不阻塞、不影响 expire 结果。
  await recordJobEvent(`CLOSED:${id}:${utcDay()}`, "CLOSED", id, rows[0].source_id ?? null);
  return true;
}

/** 点击时校验门：探活确认仍在招 → 只盖探活戳（不动 status/summary），让后台轮转少走一遍。 */
export async function touchJobCheckedById(id: string): Promise<boolean> {
  const rows = await jobsQuery(
    "update jobs set enrich_checked_at = now() where id = $1::uuid returning id",
    [id],
  );
  return rows.length > 0;
}
