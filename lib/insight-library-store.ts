// ============================================================
// 洞察库的取数层：索引（跨实例缓存）+ 单主体条目（实时）。
// 页面与 /api/insights/library 共用同一份，避免两处各建一份索引导致数字不一致。
// ============================================================
import { unstable_cache } from "next/cache";
import { callOutsideRequestScope } from "./cache-outside-request";
import { createServiceClient } from "./supabaseService";
import { fetchAllPagesConcurrent } from "./supabase-paginate";
import { ITEM_COLUMNS, flattenSources } from "./insight-bundle";
import {
  buildLibraryIndex,
  isLibraryContent,
  LIBRARY_EXCLUDED_DIMENSIONS,
  LIBRARY_EXCLUDED_ORIGINS,
  type LibraryCardMetric,
  type LibrarySubject,
  type RawItemRow,
  type RawSubjectRow,
} from "./insight-library";
import { evaluateInsight } from "./insight-verification";
import type { InsightItemView } from "./types";

/**
 * 索引多旧算「陈旧」：超过它，下一个请求照常拿到旧索引，同时在后台重建（stale-while-revalidate）。
 * 洞察由每日派生/富化链产出，10 分钟滞后用户感知不到。
 */
const INDEX_TTL_SECONDS = 600;
/**
 * 兜底：拿到的索引比这还旧，说明后台重建一直没落地（或整站闲了这么久）→ 本次请求同步重建一份。
 * 这是 2026-09-04「索引三个多小时一动不动」那次事故的上限：陈旧不许超过它。
 */
const INDEX_MAX_STALE_SECONDS = 2 * 60 * 60;

const SOURCE_SELECT =
  "insight_item_sources(insight_sources(id, url, publisher, source_kind, excerpt, collected_at, deidentified, created_at))";

/**
 * 洞察库的取数过滤：**四个取数点共用这一个**（索引 / 卡面按 subject / 卡面按公司 / 展开全部）。
 * 别在任何一处手写 `.neq("origin", "derived")` —— 上一版就是漏了「展开全部」那一处，
 * 卡面写「1 条」点开却出 7 条数据层（见 lib/insight-library 的排除名单注释）。
 */
function libraryScope<T extends { not: Function }>(query: T): T {
  const origins = LIBRARY_EXCLUDED_ORIGINS.join(",");
  const dims = LIBRARY_EXCLUDED_DIMENSIONS.join(",");
  return (query as any).not("origin", "in", `(${origins})`).not("dimension", "in", `(${dims})`) as T;
}

/** 建索引各段耗时（诊断用）。随索引一起缓存，只有几个数字，不影响缓存体积。 */
export interface IndexBuildTiming {
  subjects_ms: number;
  subject_rows: number;
  items_ms: number;
  item_rows: number;
  /** 条目 + 来源的 JSON 体积（KB）——跨洋（香港函数 → 悉尼 Supabase）传输的主要载荷。 */
  items_kb: number;
  profiles_ms: number;
  profile_rows: number;
  build_ms: number;
  total_ms: number;
  index_kb: number;
}

export interface LibraryIndex {
  subjects: LibrarySubject[];
  builtAt: string;
  buildTiming?: IndexBuildTiming;
}

type ProfileRow = { id: string; company: string; industry: string | null };

async function loadIndex(): Promise<LibraryIndex> {
  const supabase = createServiceClient();
  const t0 = performance.now();
  const timed = async <T>(run: () => Promise<T>): Promise<[T, number]> => {
    const started = performance.now();
    const value = await run();
    return [value, performance.now() - started];
  };
  // 计数与取数必须共用同一份过滤条件（fetchAllPagesConcurrent 按计数切页）。
  const subjectsQuery = (columns: string, options?: { count: "exact"; head: true }) =>
    // 主体：rejected / retired 是治理结论，索引里直接不要。
    supabase.from("insight_subjects").select(columns, options).eq("status", "active");
  // 条目 + 来源。来源是 claim 展示门的必需输入（时间窗 + ≥2 独立域名）；
  // 不带来源就没法判断「这条能不能展示」，卡面计数会比点进去看到的多。
  // 不按 subject_id 过滤：NULL 是「公司级」，由 buildLibraryIndex 挂到公司主体上。
  const itemsQuery = (columns: string, options?: { count: "exact"; head: true }) =>
    libraryScope(supabase.from("insight_items").select(columns, options).eq("status", "active"));
  const profilesQuery = (columns: string, options?: { count: "exact"; head: true }) =>
    supabase.from("company_profiles").select(columns, options);
  const HEAD = { count: "exact", head: true } as const;

  // 三张表互不依赖，并发取；每张表内部的各页也并发（见 fetchAllPagesConcurrent）。
  // 改前是 3 张表 × 各自分页全部串行：主体 1.0s + 条目 4.6s + 画像 0.5s ≈ 6.2s（2026-09-23 线上分段）。
  const [[subjectRows, subjectsMs], [itemRows, itemsMs], [profileRows, profilesMs]] = await Promise.all([
    timed(() =>
      fetchAllPagesConcurrent<RawSubjectRow>(
        () => subjectsQuery("id", HEAD),
        (from, to) =>
          subjectsQuery("id,company_id,kind,name,job_count,status")
            .order("id", { ascending: true })
            .range(from, to)
            .overrideTypes<RawSubjectRow[], { merge: false }>(),
      ),
    ),
    timed(() =>
      fetchAllPagesConcurrent<any>(
        () => itemsQuery("id", HEAD),
        (from, to) =>
          itemsQuery(`${ITEM_COLUMNS}, ${SOURCE_SELECT}`).order("id", { ascending: true }).range(from, to),
      ),
    ),
    timed(() =>
      fetchAllPagesConcurrent<ProfileRow>(
        () => profilesQuery("id", HEAD),
        (from, to) =>
          profilesQuery("id,company,industry")
            .order("id", { ascending: true })
            .range(from, to)
            .overrideTypes<ProfileRow[], { merge: false }>(),
      ),
    ),
  ]);
  const items: RawItemRow[] = itemRows.map((raw) => ({
    ...(raw as RawItemRow),
    sources: flattenSources(raw),
  }));

  const tBuild = performance.now();
  const companies = new Map(
    profileRows.map((row) => [row.id, { company: row.company, industry: row.industry ?? null }]),
  );

  const subjects = buildLibraryIndex(subjectRows, items, companies);
  const tBuilt = performance.now();
  // ⚠️ 缓存条目一旦超过 Vercel 数据缓存的 2MB 上限就会**静默不缓存**，症状是每个请求
  // 都在重建索引（线上实测 ~10s/次），且没有任何报错。这行日志是它唯一的哨兵。
  const bytes = JSON.stringify(subjects).length;
  if (bytes > 1_500_000) {
    console.warn(
      `[insight-library] 索引已 ${Math.round(bytes / 1024)}KB，逼近 2MB 缓存上限；` +
        "再涨会静默失去缓存，需要进一步瘦身或分片。",
    );
  }
  const buildTiming: IndexBuildTiming = {
    subjects_ms: Math.round(subjectsMs),
    subject_rows: subjectRows.length,
    items_ms: Math.round(itemsMs),
    item_rows: itemRows.length,
    items_kb: Math.round(JSON.stringify(itemRows).length / 1024),
    profiles_ms: Math.round(profilesMs),
    profile_rows: profileRows.length,
    build_ms: Math.round(tBuilt - tBuild),
    total_ms: Math.round(performance.now() - t0),
    index_kb: Math.round(bytes / 1024),
  };
  console.log(
    `[insight-library] 索引重建：${subjects.length} 个主体，${buildTiming.index_kb}KB ` +
      JSON.stringify(buildTiming),
  );
  return { subjects, builtAt: new Date().toISOString(), buildTiming };
}

/**
 * ⚠️ 跨实例缓存（unstable_cache），不要退回进程内 Map：serverless 多实例下命中率≈0。
 * 索引只依赖库里的洞察、与用户无关，所以可以全站共享。
 *
 * 形态：**stale-while-revalidate + 陈旧上限兜底**（2026-09-23 起；此前是 10 分钟时间桶）。
 * · 平时：条目过了 INDEX_TTL_SECONDS 就算陈旧，请求照常拿旧的、Next 在 waitUntil 里后台重建。
 *   没有任何请求需要等建索引（除了条目根本不存在：首次部署新键 / 管理后台 revalidateTag 之后）。
 * · 兜底：拿到的索引比 INDEX_MAX_STALE_SECONDS 还旧 → 同步重建一份（按 10 分钟时间桶存，
 *   同一窗口里只建一次）。
 *
 * ⚠️ 为什么不能只靠 revalidate（时间桶当初就是为此加的，兜底分支保住了它的作用）：
 * 2026-09-04 线上光配 revalidate:600 时，`index_built_at` 三个多小时一动不动 ——
 * 那时建索引要 ~10s，后台重建大概率没跑完就被回收，于是永远在发陈旧数据、而且**不报错**。
 * 症状很难看：治理脚本刚判完档，页面按「加班强度 ≤ 2」筛却是 0 条（索引里 metric_value 还全是空）。
 * 现在建索引改成并发取数（6.2s → 见 buildTiming），页面与接口都配了 maxDuration 给后台重建留余量；
 * 真没落地，兜底分支把陈旧封顶在 2 小时并打 warn。
 *
 * ⚠️ 为什么纯时间桶不够：每个 10 分钟窗口的第一个请求都要同步建一次索引。本站流量稀疏，
 * 大多数访问恰好就是「窗口里第一个」，于是线上 /insights 大多数时候 6~7s（2026-09-23 实测）。
 *
 * ⚠️ 必须经 callOutsideRequestScope 调用：否则 Next 把请求 URL（含 ?q=腾讯 这种中文）拼进缓存条目名，
 * Vercel 数据缓存读写全部静默失败，带中文搜索词的每个请求都重建索引（见 lib/cache-outside-request.ts）。
 */
const getCachedIndex = unstable_cache(async () => loadIndex(), ["insight-library-index-v3"], {
  revalidate: INDEX_TTL_SECONDS,
  tags: ["insight-library"],
});

const getRebuiltIndex = unstable_cache(
  async (_bucket: number) => loadIndex(),
  ["insight-library-index-v3-rebuild"],
  { revalidate: INDEX_TTL_SECONDS * 2, tags: ["insight-library"] },
);

export async function getInsightLibraryIndex(): Promise<LibraryIndex> {
  const index = await callOutsideRequestScope(() => getCachedIndex());
  const ageSeconds = (Date.now() - Date.parse(index.builtAt)) / 1000;
  if (!(ageSeconds > INDEX_MAX_STALE_SECONDS)) return index;

  console.warn(
    `[insight-library] 索引已 ${Math.round(ageSeconds / 60)} 分钟没更新（后台重建没落地，或整站闲置这么久），本次同步重建`,
  );
  const bucket = Math.floor(Date.now() / (INDEX_TTL_SECONDS * 1000));
  const rebuilt = await callOutsideRequestScope(() => getRebuiltIndex(bucket));
  return Date.parse(rebuilt.builtAt) > Date.parse(index.builtAt) ? rebuilt : index;
}

/**
 * 一批主体的「可展示条目」。**卡面正文与「展开全部」共用这一个取数点。**
 *
 * 两路取：命中 subject_id 的（业务线条目）+ 公司级的（subject_id 为 NULL，
 * 迁移 204 的定义，挂到该公司的 company 主体上）。
 *
 * ⚠️ 为什么非合并不可：旧的 getSubjectItems 只走 subject_id 那一路、且没过滤 origin，
 *    而库里**带 subject_id 的行全部是 origin=derived**（2026-09-07 live 复核：company 6,642 +
 *    business_unit 3,933，非派生行一条都没有）。于是卡面写「说法 1 条」，点开是 7 条
 *    清一色的数据层（城市分布 / 职能分布 / 学历要求…）。一个取数点 + 一道门，
 *    才能保证「卡面写几条，点开就是几条」。
 */
async function loadDisplayableItems(
  subjects: Pick<LibrarySubject, "id" | "kind" | "company_id">[],
): Promise<Map<string, InsightItemView[]>> {
  const bySubject = new Map<string, InsightItemView[]>();
  const ids = subjects.map((s) => s.id);
  if (ids.length === 0) return bySubject;

  const supabase = createServiceClient();
  const companyIds = subjects.filter((s) => s.kind === "company").map((s) => s.company_id);
  const select = `${ITEM_COLUMNS}, ${SOURCE_SELECT}`;
  const [bySubjectRes, byCompanyRes] = await Promise.all([
    libraryScope(
      supabase.from("insight_items").select(select).in("subject_id", ids).eq("status", "active"),
    ),
    companyIds.length
      ? libraryScope(
          supabase
            .from("insight_items")
            .select(select)
            .in("company_id", companyIds)
            .is("subject_id", null)
            .eq("status", "active"),
        )
      : Promise.resolve({ data: [], error: null } as any),
  ]);
  const error = bySubjectRes.error || byCompanyRes.error;
  if (error) throw new Error(error.message);

  const subjectIdByCompany = new Map(
    subjects.filter((s) => s.kind === "company").map((s) => [s.company_id, s.id]),
  );
  const now = new Date();
  for (const raw of [...(bySubjectRes.data || []), ...(byCompanyRes.data || [])]) {
    const key = (raw as any).subject_id || subjectIdByCompany.get((raw as any).company_id);
    if (!key) continue;
    // 内存侧再复核一次排除名单：DB 过滤写错（或将来有人绕过 libraryScope）时，
    // 这一道让数据层至多漏进日志、漏不进页面。
    if (!isLibraryContent(raw as any)) continue;
    const sources = flattenSources(raw);
    // ⚠️ 与索引走**同一道展示门**：卡面写几条，点开就必须是几条。
    const ev = evaluateInsight(raw as any, sources, now);
    if (!ev.displayable) continue;
    const view = { ...(raw as any), sources, outdated: ev.outdated } as InsightItemView;
    const list = bySubject.get(key);
    if (list) list.push(view);
    else bySubject.set(key, [view]);
  }
  return bySubject;
}

/**
 * 展开某个主体时才取它的全部条目。
 * 刻意不进索引缓存：条目全文 + 来源体积远大于卡面所需，放进去等于把首屏又做回逐条下发。
 *
 * 入参是**整个主体**而不是 id：公司级条目要靠 company_id 才取得到（见 loadDisplayableItems）。
 */
export async function getSubjectItems(
  subject: Pick<LibrarySubject, "id" | "kind" | "company_id">,
): Promise<InsightItemView[]> {
  const bySubject = await loadDisplayableItems([subject]);
  const out = bySubject.get(subject.id) || [];
  // fact 在前（有官方出处最硬），再按样本量 —— 与卡面挑选同序，避免「卡面第一条」
  // 和「展开第一条」是两条不同的内容。
  const rank: Record<string, number> = { fact: 0, claim: 1, signal: 2 };
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
  /** 当前筛选选中的主题：卡面把它排最前。用户筛「加班少的公司」却先看到年终奖，很别扭。 */
  focusMetric?: string | null,
): Promise<LibrarySubject[]> {
  if (subjects.length === 0) return subjects;

  let bySubject: Map<string, InsightItemView[]>;
  try {
    bySubject = await loadDisplayableItems(subjects);
  } catch (error: any) {
    // 取不到就退回索引里的数字：卡面会略旧，但不会整页空掉。
    console.error("[insight-library] 取卡面内容失败", error?.message || error);
    return subjects;
  }

  const rank: Record<string, number> = { fact: 0, claim: 1, signal: 2 };
  const out: LibrarySubject[] = [];
  for (const subject of subjects) {
    const live = bySubject.get(subject.id) || [];
    // 索引可能比库旧（治理脚本刚退役过一批），此时该主体已经没有可展示内容 → 本页不显示它。
    if (live.length === 0) continue;
    // 筛中主题的「代表值」= 该主题所有档位的中位数，与 lib/insight-library 的筛选口径一致。
    // ⚠️ 卡面要挑**最能解释这次匹配**的那几条：线上实测滴滴 5 条加班档位是 [1,2,2,4,4]，
    // 中位数 2 所以被「≤2」筛出来是对的，但卡面按老排序挑到了 1、4、4 —— 两条 2 一条没露，
    // 用户看到「加班多」会以为筛错了。所以按「离中位数的距离」排，离得近的先上。
    const focusValues = focusMetric
      ? live
          .filter((i) => i.metric_key === focusMetric && i.metric_value != null)
          .map((i) => i.metric_value as number)
          .sort((a, b) => a - b)
      : [];
    const focusMedian = focusValues.length
      ? focusValues.length % 2
        ? focusValues[(focusValues.length - 1) / 2]
        : (focusValues[focusValues.length / 2 - 1] + focusValues[focusValues.length / 2]) / 2
      : null;
    const distance = (item: InsightItemView) =>
      focusMedian == null || item.metric_key !== focusMetric || item.metric_value == null
        ? Number.POSITIVE_INFINITY
        : Math.abs(item.metric_value - focusMedian);
    live.sort(
      (a, b) =>
        // 筛中的主题优先：用户是带着「看这一项」的意图筛过来的。
        (focusMetric ? (b.metric_key === focusMetric ? 1 : 0) - (a.metric_key === focusMetric ? 1 : 0) : 0) ||
        distance(a) - distance(b) ||
        (rank[a.assertion || "claim"] ?? 9) - (rank[b.assertion || "claim"] ?? 9) ||
        (b.sample_size || 0) - (a.sample_size || 0),
    );
    const counts: Record<string, number> = { fact: 0, signal: 0, claim: 0 };
    const dims = new Set<string>();
    let latest: string | null = null;
    for (const item of live) {
      counts[item.assertion || "claim"] = (counts[item.assertion || "claim"] || 0) + 1;
      dims.add(item.dimension);
      if (!latest || item.last_verified_at > latest) latest = item.last_verified_at;
    }
    out.push({
      ...subject,
      // 卡面上一切给用户看的数字都取自这次实时查询，不取缓存索引——
      // 索引只负责筛选/分面/排序（轻微滞后无所谓），展示必须准。
      item_count: live.length,
      assertion_counts: counts as LibrarySubject["assertion_counts"],
      dimensions: [...dims] as LibrarySubject["dimensions"],
      last_verified_at: latest,
      cards: live.slice(0, perSubject).map((item) => ({
        metric_key: item.metric_key || "",
        metric_value: item.metric_value ?? null,
        metric_unit: item.metric_unit ?? null,
        sample_size: item.sample_size ?? null,
        assertion: (item.assertion || "claim") as LibraryCardMetric["assertion"],
        content: item.content,
        scope: (item.scope || {}) as Record<string, unknown>,
      })),
    });
  }
  return out;
}
