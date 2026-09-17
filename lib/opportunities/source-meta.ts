// 机会雷达用的 source 元信息（sources 永远在 Supabase / 悉尼）：**跨实例缓存的全表快照**。
//
// 为什么是这个形态（2026-09-18 第三次动它，前两次的教训都写在这儿，别再原地打转）：
//   · 第一版「每请求拉全表」——sources 已越过 PostgREST 单次 1000 行上限（现 1,655 行），
//     内部是**串行**翻页，本机实测 1,434ms，是当时 Promise.all 里最慢的一条；
//   · 第二版「按召回涉及的 id 分块取」——行数少了，但它**依赖召回结果**，只能串在召回之后，
//     线上 02:35 实测这一跳 **480ms**，占 `[today-feed] total 1,880ms` 的 25%；
//     它带的进程内缓存在 serverless 低流量下几乎不命中（每请求一个新实例）。
//   · 这一版：全表 6 列只有 **1,655 行 / 170KB**（2026-09-18 实测，`scripts/perf-probe/today-page.js`），
//     远在 `unstable_cache` 单条约 2MB 的上限内 → 做成**跨实例**共享快照。于是
//     ① 命中时零往返；② 它不再依赖召回结果，可以**和召回并行**发出，即使未命中也藏在召回的影子里。
//
// ⚠️ 必须取**全部**源、不能只取 enabled：`checkEligibility` 靠 `enabled=false` 出 `source_disabled` 硬门，
//    少给一行会让被禁用源的岗从「明确拒绝」变成「元信息未知」而放行——这是静默放宽用户条件。
// ⚠️ 用 service_role 客户端而不是请求态客户端：`sources` 的 RLS 是「所有**登录**用户可读」，anon 读不到；
//    而请求态客户端是从 cookie 建的，放进 `unstable_cache` 的函数体里可能触发 token 刷新去写 cookie
//    （缓存体内写 cookie 会抛），错误又会被 catch 吞成「没有元信息」。service_role 无 cookie、行为确定。
//    只读这 6 个非隐私列。
import "server-only";
import { unstable_cache } from "next/cache";
import { createServiceClient } from "../supabaseService";
import type { SourceMeta } from "./types";

export const SOURCE_META_COLUMNS = "id, company, adapter_name, crawl_method, last_checked_at, enabled";

/** freshness 徽章只看「上次检查时间」的粗粒度，5 分钟内完全够新鲜（与旧的进程内 TTL 同档）。 */
const CACHE_TTL_SECONDS = 300;
/** PostgREST 单次返回上限，超过要翻页。 */
const PAGE_SIZE = 1000;

async function fetchAllSourceMeta(): Promise<SourceMeta[]> {
  const supabase = createServiceClient();
  const out: SourceMeta[] = [];
  for (let from = 0; ; from += PAGE_SIZE) {
    const { data, error } = await supabase
      .from("sources")
      .select(SOURCE_META_COLUMNS)
      .range(from, from + PAGE_SIZE - 1);
    // 抛而不是返回半截：半截快照会让「没取到的那些源」的岗静默丢掉 source_disabled 硬门。
    // 抛出去由调用方 catch → 退回按 id 取的老路径（见 service.ts），不静默降级。
    if (error) throw new Error(error.message);
    const rows = (data || []) as SourceMeta[];
    out.push(...rows);
    if (rows.length < PAGE_SIZE) break;
  }
  return out;
}

const cachedSourceMeta = unstable_cache(fetchAllSourceMeta, ["radar-source-meta-v1"], {
  revalidate: CACHE_TTL_SECONDS,
  tags: ["radar-source-meta"],
});

/**
 * 取全量 source 元信息快照。失败/形状不对返回 null —— 调用方**必须**据此退回按 id 取，
 * 不许当成「这批岗没有元信息」继续（那会静默放宽 source_disabled 硬门）。
 */
export async function loadSourceMetaSnapshot(): Promise<Map<string, SourceMeta> | null> {
  try {
    const rows = await cachedSourceMeta();
    // `unstable_cache` 条目**跨部署存活**：上线那一小段里缓存中可能是旧形状。形状不对当没有，走兜底。
    if (!Array.isArray(rows) || !rows.length) return null;
    const map = new Map<string, SourceMeta>();
    for (const s of rows) if (s && typeof s.id === "string") map.set(s.id, s);
    return map.size ? map : null;
  } catch (e) {
    console.error("[opportunities] source meta snapshot failed:", (e as Error).message);
    return null;
  }
}
