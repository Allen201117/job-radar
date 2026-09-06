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
import { extractGradClass } from "@/lib/grad-class";

const { canonicalizeJdUrl } = canonicalUrl as {
  canonicalizeJdUrl: (u: string | null | undefined) => string | null;
};
const { deriveCountryCode, deriveJobScope, normalizeRegions } = geo as {
  deriveCountryCode: (location: string | null | undefined) => string | null;
  deriveJobScope: (
    location: string | null | undefined,
    regions?: string[] | string | null,
  ) => "domestic" | "overseas";
  normalizeRegions: (regions: string[] | string | null | undefined) => string[];
};
const { sponsorshipSignal } = sponsorship as {
  sponsorshipSignal: (text: string | null | undefined) => "available" | "none" | "unknown";
};

// insert 数据列（值取自 job，缺省 null）；canonical_jd_url/search_doc 由触发器维护、id/时间/状态/计数走字面量。
const INSERT_DATA_COLS = [
  "source_id", "company", "title", "location", "country_code", "job_scope", "job_type", "grad_class", "summary",
  "jd_url", "apply_url", "salary_text", "posted_at", "content_hash", "experience", "education", "deadline",
  "sponsorship_signal",
] as const;
// update 数据列：刷新 live 重抓提供的基础字段 + location 派生 geo 字段；不碰 source_id / jd_url /
// experience / education / deadline / first_seen_at，避免把爬虫/富化已填字段清空。
const UPDATE_DATA_COLS = [
  "company", "title", "location", "country_code", "job_scope", "job_type", "grad_class", "summary",
  "apply_url", "salary_text", "posted_at", "content_hash", "sponsorship_signal",
] as const;
// 这些富化字段在 UPDATE 时新值为空则保留旧值（COALESCE(NULLIF(...))），与 crawler/jobs_db._PRESERVE_IF_EMPTY 同口径：
// app 的 discovery/search 刷新多只带列表骨架（无 JD 正文）→ 不得把浏览器/httpx 富化补好的 summary 抹成 NULL。
const PRESERVE_IF_EMPTY = new Set<string>(["summary", "job_type", "salary_text"]);
// 同样要防「刷新抹掉」，但列是非文本类型 → 不能套 NULLIF(x,'')（'' 往 smallint 强转会报错）。
// 非文本列的「空」就是 NULL，直接 COALESCE(x, 列)。与 crawler/jobs_db._PRESERVE_IF_NULL 同口径。
const PRESERVE_IF_NULL = new Set<string>(["grad_class"]);
// job_scope 还有第三种保护：**拿不出依据时不许写**。
// deriveJobScope 走到函数末尾返回的 'domestic' 是**兜底默认值不是结论**，而库里那一行
// 很可能是有依据的 overseas。让默认值盖掉结论 = 刷一次就把海外岗打回国内看板。
// 2026-09-05 香港库实测，在招且「地点抽不出国家」却已判 overseas 的有 6,313 个：
// 4,312 个来自 regions 不含 CN 的源（AbbVie 1,576 / ServiceNow 608 / Ubisoft 272…），
// 另外 2,001 个来自含 CN 的源、地点是 "Toronto, Canada" / "Warsaw, …, PL" /
// "Søborg, …, DK" 这类**国别码还没进词表**的写法 —— 它们确确实实在海外。
// 判据只认「不是兜底那一行」：deriveJobScope 只有两条路返回 domestic ——
// 地点抽出了大中华国家码（有依据），或走到末尾兜底（没依据）；返回 overseas 则必然
// 来自三个正向分支之一（国家码 / 自报海外 / 源 regions 不含 CN）。所以
// 「显式传了 job_scope」「抽得出国家码」「结论是 overseas」三者有其一才算有依据。
// ⚠️ 别把「拿到了 regions」当依据：regions 含 CN 时函数是**穿过** regions 分支落到兜底的，
// 那一步没产生任何结论 —— 上面那 2,001 行正是这么被覆盖掉的。
// 实现：无依据时把该列的值传 null，靠 COALESCE 回退旧值 —— job_scope 是 not null 列，
// 所以只有「app 拿不出依据」这一种情况会走到回退分支，正常写入行为一字不变。
const SCOPE_COL = "job_scope";
const SCOPE_EVIDENCED = "__job_scope_evidenced";

export type UpsertResult = { row: any; action: "created" | "updated" };

function withDerivedFields(job: Record<string, any>): Record<string, any> {
  // source_regions 是调用方挂上来的**非列**字段（app/api/search 从 sources 行带下来）：
  // 让 app 侧的求职范围判定与 crawler/normalizer 逐字同口径（都把源 regions 喂给 deriveJobScope）。
  // INSERT/UPDATE 的列都是显式枚举的，所以它不会漏进 SQL。
  //
  // ⚠️ /api/discovery 那条链**刻意没接**：它写 source_id=null（官方源发现的岗还没有 sources 行），
  // 拿不到 regions，新插入的裸远程岗因此仍按兜底落 domestic。为什么不修——先量了再决定：
  //   · 香港库里 source_id is null 的行 **全表 0 条**（2026-09-05 实测，不分状态）
  //     ⇒ 这条链**从来没有真的插进过一个岗**；
  //   · discovery_runs 里 mode='web_search'（官方源发现）最后一次是 **2026-06-05**，
  //     company_refresh 最后一次 2026-06-22 —— 三个月没跑过。
  // 所以这是个**理论上的洞**，为它把源信息一路穿到 discovery 那条链上不划算。
  // 什么时候该做：上面两个数字任意一个涨起来（有 source_id is null 的行进来，或 web_search
  // 恢复日常运行）。「覆盖已有结论」那一半已经由下面的 SCOPE_EVIDENCED 堵死，与本条无关。
  const regions = normalizeRegions(job.source_regions);
  const countryCode = job.country_code ?? deriveCountryCode(job.location);
  const jobScope = job.job_scope ?? deriveJobScope(job.location, regions);
  return {
    ...job,
    country_code: countryCode,
    job_scope: jobScope,
    [SCOPE_EVIDENCED]:
      job.job_scope != null || jobScope === "overseas" || deriveCountryCode(job.location) !== null,
    sponsorship_signal:
      job.sponsorship_signal ?? sponsorshipSignal([job.title, job.summary].filter(Boolean).join(" ")),
    // 届别只认硬信号，抽不出留 null（与 crawler/grad_class.py 同口径，改规则两边同改）
    grad_class: job.grad_class ?? extractGradClass(job),
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
  const setParts = UPDATE_DATA_COLS.map((c, i) => {
    if (PRESERVE_IF_EMPTY.has(c)) return `${c} = COALESCE(NULLIF($${i + 1}, ''), ${c})`;
    if (PRESERVE_IF_NULL.has(c) || c === SCOPE_COL) return `${c} = COALESCE($${i + 1}, ${c})`;
    return `${c} = $${i + 1}`;
  });
  // expired = detail 探活确认撤岗的强信号；列表/发现重抓不得复活它（否则点开 404/已下线）。
  // 与 crawler/jobs_db._update_set_clause 的 status CASE 同口径：expired 黏住，removed/active 仍刷 active。
  setParts.push("status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE 'active' END", "last_seen_at = now()");
  const sql =
    `update jobs set ${setParts.join(", ")} where id = $${UPDATE_DATA_COLS.length + 1}::uuid returning ${JOB_COLUMNS}`;
  const vals = [
    ...UPDATE_DATA_COLS.map((c) => (c === SCOPE_COL && !job[SCOPE_EVIDENCED] ? null : job[c] ?? null)),
    id,
  ];
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

/**
 * 按 id 补 summary（enrich 按需富化写回）。返回是否命中一行。
 *
 * 不用管物化的招聘类型：正文是它的分类依据之一，库里的触发器
 * （jobs-db/schema.sql 的 jobs_guard_recruitment_class）看到依据变了会自动把结论作废，
 * 再由补算任务按最终那一行重算。**别在这里手写分类**——手上只有 summary，
 * 缺 company / apply_url / experience，算出来的会和最终那一行对不上（那正是 2026-09-03 的 bug）。
 *
 * 届别（grad_class）是例外，可以在这里补，理由与上面那条警告不冲突：
 * 它只依赖 title / job_type / summary 这类文本，不需要 company / apply_url / experience，
 * 而这里手上就有新正文。**这批遗留正是这么来的**：岗位入库时是薄卡（没正文→抽不出届别→
 * NULL），后来 enrich 把正文补上，而这条 SQL 过去不碰 grad_class，于是永远停在 NULL；
 * 线上实测约 2,100 个在招校招岗正文里明明写着「20XX届」却没标注。
 *
 * ⚠️ 这里**只喂 summary**（title/job_type 不在本函数的入参里，取它们要多打一次库）。
 * 够用：标题里的届别在主 upsert 路径就已经抽过了，这条路补的是「正文后到」的那部分。
 * COALESCE 保证已有届别绝不被覆盖；抽不出返回 null，行为与改动前完全一致。
 */
export async function updateJobSummaryById(id: string, summary: string): Promise<boolean> {
  const gradClass = extractGradClass({ summary });
  const rows = await jobsQuery(
    "update jobs set summary = $1, enrich_checked_at = now(), grad_class = coalesce(grad_class, $3) where id = $2::uuid returning id",
    [summary, id, gradClass],
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
