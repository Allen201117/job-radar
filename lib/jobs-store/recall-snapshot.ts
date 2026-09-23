// /today 召回快照的读写（表 today_recall_snapshots，香港 jobs 库；为什么要有它见 jobs-db/schema.sql 该表注释）。
//
// 分工：这里只管「存什么、取什么」；「快照能不能用、怎么在快照上重跑召回」在 lib/jobs-store/opportunities.ts
// （recallSnapshotUsability / RecallRestriction），两边口径不在这里重复。
//
// 读失败一律按「没有快照」处理（调用方退回现跑召回，行为与没有这张表时逐字相同）；写失败只记日志。
// 快照只是加速层，任何一步出错都不能让 /today 变成错误页。
import "server-only";
import { jobsQuery } from "./client";
import type { RecallTier } from "./opportunities";

export interface RecallSnapshot {
  recallKey: string;
  /** 现跑召回的时刻（ISO）。 */
  computedAt: string;
  /** 召回输出按层拆开的 id（与 SQL 输出逐行同序）。 */
  idsByTier: Partial<Record<RecallTier, string[]>>;
  tiers: RecallTier[];
  rows: number;
  capped: boolean;
  /** 快照里的岗此刻仍在招的条数（读快照时顺手回表数出来——这一步本身就是在预热下一跳要读的堆块）。 */
  activeRows: number;
}

export interface RecallSnapshotWrite {
  recallKey: string;
  computedAt: string;
  /** 现跑召回的原始输出：每行的 id 与层下标（未去重、保持 SQL 输出顺序）。 */
  rows: Array<{ id: string; tier: number }>;
  tiers: RecallTier[];
  capped: boolean;
  source: "cron" | "request";
}

function asArray<T>(v: unknown, map: (x: string) => T): T[] {
  if (Array.isArray(v)) return v.map((x) => map(String(x)));
  // node-pg 未注册解析器的数组类型会原样回 '{a,b}' 文本
  const s = String(v ?? "");
  if (!s.startsWith("{") || s === "{}") return [];
  return s.slice(1, -1).split(",").map((x) => map(x.replace(/^"|"$/g, "")));
}

/**
 * 读快照，并**在同一条 SQL 里**把快照里那些岗的堆块读一遍（数在招条数）。
 *
 * 为什么把「预热」塞进读快照：页面在等悉尼那 4 条 Supabase 查询（0.2~0.56s）时，这条香港库查询与它并行；
 * 快照里 ~1,800 个岗的堆块在这段空档里被读进缓存，紧接着的限定重算就是热读。冷态下这是整条链最贵的 I/O，
 * 放在悉尼往返的影子里等于白拿。
 */
export async function readRecallSnapshot(userId: string): Promise<RecallSnapshot | null> {
  const rows = await jobsQuery<Record<string, unknown>>(
    `select s.recall_key, s.computed_at, s.job_ids, s.tier_idx, s.tier_names, s.capped,
            (select count(*) from jobs j where j.id = any(s.job_ids) and j.status = 'active')::int as active_rows
       from today_recall_snapshots s
      where s.user_id = $1`,
    [userId],
  );
  const r = rows[0];
  if (!r) return null;
  const ids = asArray(r.job_ids, (x) => x);
  const tierIdx = asArray(r.tier_idx, (x) => Number(x));
  const tiers = asArray(r.tier_names, (x) => x) as RecallTier[];
  if (ids.length !== tierIdx.length) return null; // 表约束已钉住；防御性
  const idsByTier: Partial<Record<RecallTier, string[]>> = {};
  for (let i = 0; i < ids.length; i++) {
    const tier = tiers[tierIdx[i]];
    if (!tier) return null; // 层下标越界 = 数据坏了，别拿来用
    (idsByTier[tier] ||= []).push(ids[i]);
  }
  return {
    recallKey: String(r.recall_key),
    computedAt: new Date(String(r.computed_at)).toISOString(),
    idsByTier,
    tiers,
    rows: ids.length,
    capped: Boolean(r.capped),
    activeRows: Number(r.active_rows) || 0,
  };
}

/** 读失败按「没有快照」处理并留痕；永不 reject（页面把它和悉尼查询并行发出，不能多一条报错路径）。 */
export function readRecallSnapshotSafe(userId: string): Promise<RecallSnapshot | null> {
  return readRecallSnapshot(userId).catch((e) => {
    console.warn("[recall-snapshot] 读取失败，按无快照处理：", (e as Error).message);
    return null;
  });
}

export async function writeRecallSnapshot(userId: string, w: RecallSnapshotWrite): Promise<void> {
  await jobsQuery(
    `insert into today_recall_snapshots
       (user_id, recall_key, computed_at, job_ids, tier_idx, tier_names, capped, source, updated_at)
     values ($1, $2, $3, $4::uuid[], $5::smallint[], $6::text[], $7, $8, now())
     on conflict (user_id) do update set
       recall_key = excluded.recall_key, computed_at = excluded.computed_at, job_ids = excluded.job_ids,
       tier_idx = excluded.tier_idx, tier_names = excluded.tier_names, capped = excluded.capped,
       source = excluded.source, updated_at = now()
     -- 并发写（cron 与用户打开页面同时刷新）时只留更新的那份，旧结果不许覆盖新结果
     where today_recall_snapshots.computed_at <= excluded.computed_at`,
    [
      userId,
      w.recallKey,
      w.computedAt,
      w.rows.map((r) => r.id),
      w.rows.map((r) => r.tier),
      w.tiers,
      w.capped,
      w.source,
    ],
  );
}
