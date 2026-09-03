// ============================================================
// 洞察库的取数层：索引（跨实例缓存）+ 单主体条目（实时）。
// 页面与 /api/insights/library 共用同一份，避免两处各建一份索引导致数字不一致。
// ============================================================
import { unstable_cache } from "next/cache";
import { createServiceClient } from "./supabaseService";
import { fetchAllPages } from "./supabase-paginate";
import { ITEM_COLUMNS, flattenSources } from "./insight-bundle";
import {
  buildLibraryIndex,
  metricKey,
  type LibraryCardMetric,
  type LibrarySubject,
  type RawItemRow,
  type RawSubjectRow,
} from "./insight-library";
import { evaluateInsight } from "./insight-verification";
import type { InsightItemView } from "./types";

/** 索引缓存时长。洞察由每日派生/富化链产出，10 分钟滞后用户感知不到。 */
const INDEX_TTL_SECONDS = 600;

const SOURCE_SELECT =
  "insight_item_sources(insight_sources(id, url, publisher, source_kind, excerpt, collected_at, deidentified, created_at))";

export interface LibraryIndex {
  subjects: LibrarySubject[];
  builtAt: string;
}

async function loadIndex(): Promise<LibraryIndex> {
  const supabase = createServiceClient();

  // 主体：rejected / retired 是治理结论，索引里直接不要。
  const subjectRows = await fetchAllPages<RawSubjectRow>((from, to) =>
    supabase
      .from("insight_subjects")
      .select("id,company_id,kind,name,job_count,status")
      .eq("status", "active")
      .order("id", { ascending: true })
      .range(from, to),
  );

  // 条目 + 来源。来源是 claim 展示门的必需输入（时间窗 + ≥2 独立域名）；
  // 不带来源就没法判断「这条能不能展示」，卡面计数会比点进去看到的多。
  const itemRows = await fetchAllPages<any>((from, to) =>
    supabase
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, ${SOURCE_SELECT}`)
      .eq("status", "active")
      // ⚠️ 洞察库不放「数据层」（2026-09-03 创始人定调）：城市分布、学历要求这类
      // 用户自己在岗位库筛一下就有，不算信息差。洞察库只承载「别人的经验感受」
      // 与官方事实。派生链**照常在后台跑**（快照要攒够 30 天才有趋势），
      // 等趋势这类真信息差出来了再单独放回。
      .neq("origin", "derived")
      // 不按 subject_id 过滤：NULL 是「公司级」，由 buildLibraryIndex 挂到公司主体上。
      .order("id", { ascending: true })
      .range(from, to),
  );
  const items: RawItemRow[] = itemRows.map((raw) => ({
    ...(raw as RawItemRow),
    sources: flattenSources(raw),
  }));

  const profileRows = await fetchAllPages<{ id: string; company: string; industry: string | null }>(
    (from, to) =>
      supabase
        .from("company_profiles")
        .select("id,company,industry")
        .order("id", { ascending: true })
        .range(from, to),
  );
  const companies = new Map(
    profileRows.map((row) => [row.id, { company: row.company, industry: row.industry ?? null }]),
  );

  const subjects = buildLibraryIndex(subjectRows, items, companies);
  // ⚠️ 缓存条目一旦超过 Vercel 数据缓存的 2MB 上限就会**静默不缓存**，症状是每个请求
  // 都在重建索引（线上实测 ~10s/次），且没有任何报错。这行日志是它唯一的哨兵。
  const bytes = JSON.stringify(subjects).length;
  if (bytes > 1_500_000) {
    console.warn(
      `[insight-library] 索引已 ${Math.round(bytes / 1024)}KB，逼近 2MB 缓存上限；` +
        "再涨会静默失去缓存，需要进一步瘦身或分片。",
    );
  }
  console.log(`[insight-library] 索引重建：${subjects.length} 个主体，${Math.round(bytes / 1024)}KB`);
  return { subjects, builtAt: new Date().toISOString() };
}

/**
 * ⚠️ 跨实例缓存（unstable_cache），不要退回进程内 Map：serverless 多实例下命中率≈0。
 * 索引只依赖库里的洞察、与用户无关，所以可以全站共享。
 */
export const getInsightLibraryIndex = unstable_cache(loadIndex, ["insight-library-index-v1"], {
  revalidate: INDEX_TTL_SECONDS,
  tags: ["insight-library"],
});

/**
 * 展开某个主体时才取它的全部条目（走 idx_insight_items_subject 部分索引）。
 * 刻意不进索引缓存：条目全文 + 来源体积远大于卡面所需，放进去等于把首屏又做回逐条下发。
 */
export async function getSubjectItems(subjectId: string): Promise<InsightItemView[]> {
  const supabase = createServiceClient();
  const { data, error } = await supabase
    .from("insight_items")
    .select(`${ITEM_COLUMNS}, ${SOURCE_SELECT}`)
    .eq("subject_id", subjectId)
    .eq("status", "active");
  if (error) throw new Error(error.message);
  const now = new Date();
  const out: InsightItemView[] = [];
  for (const raw of data || []) {
    const sources = flattenSources(raw);
    const ev = evaluateInsight(raw as any, sources, now);
    // 与索引计数同一道门：卡面写几条，展开就必须是几条。
    if (!ev.displayable) continue;
    out.push({ ...(raw as any), sources, outdated: ev.outdated });
  }
  // signal 在前（第一方最可信），再按样本量。
  const rank: Record<string, number> = { signal: 0, fact: 1, claim: 2 };
  return out.sort(
    (a, b) =>
      (rank[a.assertion || "claim"] ?? 9) - (rank[b.assertion || "claim"] ?? 9) ||
      (b.sample_size || 0) - (a.sample_size || 0),
  );
}

/**
 * 给「当前这一页」的主体卡补上指标正文。
 *
 * 正文不进缓存索引（见 LibraryMetric 注释），所以每页现取一次：最多 24 个主体 × 3 条，
 * 按 item id 直接命中主键，比把 1,500 个主体的正文全塞进缓存便宜得多，
 * 也让首屏体积不随洞察库规模增长。
 */
export async function attachCardContents(
  subjects: LibrarySubject[],
  perSubject = 3,
): Promise<LibrarySubject[]> {
  const ids = subjects.map((s) => s.id);
  if (ids.length === 0) return subjects;

  const supabase = createServiceClient();
  // 公司主体的卡面条目可能是公司级写入的（subject_id 为 NULL），所以两路都要取。
  const companyIds = subjects.filter((s) => s.kind === "company").map((s) => s.company_id);
  const columns =
    "subject_id, company_id, metric_key, metric_value, metric_unit, sample_size, assertion, content, scope";
  const [bySubjectRes, byCompanyRes] = await Promise.all([
    supabase.from("insight_items").select(columns)
      .in("subject_id", ids).eq("status", "active")
      .neq("origin", "derived").not("metric_key", "is", null),
    companyIds.length
      ? supabase.from("insight_items").select(columns)
        .in("company_id", companyIds).is("subject_id", null)
        .eq("status", "active").neq("origin", "derived").not("metric_key", "is", null)
      : Promise.resolve({ data: [], error: null } as any),
  ]);
  const error = bySubjectRes.error || byCompanyRes.error;
  const data = [...(bySubjectRes.data || []), ...(byCompanyRes.data || [])];
  if (error) {
    // 取不到正文不该让整页空掉：卡面退回只显示指标名与数值（见 metricText）。
    console.error("[insight-library] 取卡面正文失败", error.message);
    return subjects;
  }
  const subjectIdByCompany = new Map(
    subjects.filter((s) => s.kind === "company").map((s) => [s.company_id, s.id]),
  );
  const bySubject = new Map<string, any[]>();
  for (const row of data || []) {
    const key = row.subject_id || subjectIdByCompany.get(row.company_id);
    if (!key) continue;
    const list = bySubject.get(key);
    if (list) list.push(row);
    else bySubject.set(key, [row]);
  }
  return subjects.map((subject) => {
    // 卡面顺序必须与索引里 trimSubjectForCard 的口径一致：signal 在前，再按样本量。
    const wantedKeys = subject.metrics.slice(0, perSubject).map(metricKey);
    const rows = bySubject.get(subject.id) || [];
    const cards: LibraryCardMetric[] = [];
    for (const key of wantedKeys) {
      const row = rows.find((r) => r.metric_key === key);
      if (!row) continue;
      cards.push({
        metric_key: row.metric_key,
        metric_value: row.metric_value ?? null,
        metric_unit: row.metric_unit ?? null,
        sample_size: row.sample_size ?? null,
        assertion: (row.assertion || "claim") as LibraryCardMetric["assertion"],
        content: row.content,
        scope: row.scope || {},
      });
    }
    return { ...subject, cards };
  });
}
