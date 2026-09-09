// ============================================================
// 洞察展示门 — 共享的「过校验门 + 按维度分组」逻辑
// /api/insights 与 /api/insights/availability 共用，避免重复（来源：原 insights 路由内联逻辑）。
// ============================================================

import {
  evaluateInsight,
  type InsightEvaluation,
} from "./insight-verification";
import type {
  InsightDimension,
  InsightItem,
  InsightItemView,
  InsightSource,
} from "./types";

export const INSIGHT_DIMENSIONS: InsightDimension[] = [
  "timing",
  "hiring",
  "listing",
  "compensation_intensity",
  "path",
  "culture",
];

/**
 * 「数据层」的 origin —— 展示给用户的两个面（洞察库 /insights 与岗位卡的公司洞察抽屉）
 * **都不收**这两类。判据只有一条：用户自己查一下就有的，不算信息差。
 *
 *   · derived         —— 我们从自有岗位库算出的结构分布（城市 / 职能 / 学历 / 经验年限 /
 *                        在架时长 / 近 30 天新挂出…）。用户在岗位库筛一下就有。
 *   · official_filing —— 年报派生的在职员工数、技术人员占比、人均薪酬。年报里写着。
 *
 * 2026-09-07 创始人先后定的两次：先撤洞察库的，再撤抽屉里的年报数字。
 * 两个面共用这一份，就是为了别再出现「一个面撤了、另一个面还在显示」。
 *
 * ⚠️ 后台治理页（/api/insights/admin）**不用**这份名单：治理要看得见全部条目，
 *    它排除 derived 是为了体积（约 9,000 条会把页面压垮），不是为了「不该看」。
 * ⚠️ 派生链与年报链**照常在后台跑**（趋势要攒够 30 天快照才有意义），
 *    等「同比在缩招」这类真信息差出来了再按主题单独放回，而不是把整层倒回来。
 */
export const DATA_LAYER_ORIGINS = ["derived", "official_filing"] as const;

/** PostgREST 的 `not("origin","in",…)` 值。别在调用点手拼字符串。 */
export const DATA_LAYER_ORIGINS_FILTER = `(${DATA_LAYER_ORIGINS.join(",")})`;

/** 这条是不是数据层（内存侧复核用；DB 侧过滤用上面那个常量）。 */
export function isDataLayerItem(item: { origin?: string | null }): boolean {
  return Boolean(item.origin && (DATA_LAYER_ORIGINS as readonly string[]).includes(item.origin));
}

// ⚠️ 踩过的坑（2026-09-03）：在 verification 判断里加了新逻辑却忘了加进 ITEM_COLUMNS，
// 导致新字段在查询结果里永远是 undefined，逻辑永远走不到。加新展示门前先确认列在这里。
export const ITEM_COLUMNS =
  "id, company_id, dimension, grade, title, content, sample_size, payload, time_window, valid_from, valid_until, last_verified_at, deidentified, status, created_at, updated_at, verification, origin, assertion, subject_id, metric_key, metric_value, metric_unit, scope";

export function emptyDimensions(): Record<InsightDimension, InsightItemView[]> {
  return { timing: [], hiring: [], listing: [], compensation_intensity: [], path: [], culture: [] };
}

// Supabase 嵌套 select 返回 { insight_sources: {...} }[]，拍平为 InsightSource[]
export function flattenSources(item: any): InsightSource[] {
  const rows = (item?.insight_item_sources || []) as Array<{
    insight_sources: InsightSource | null;
  }>;
  return rows.map((r) => r.insight_sources).filter(Boolean) as InsightSource[];
}

// 输入：某公司的 active 洞察原始行（含嵌套来源）；输出：过门后的分组展示态 + 评估结果
export function groupGatedInsights(
  rawItems: any[],
  now: Date = new Date(),
): {
  dimensions: Record<InsightDimension, InsightItemView[]>;
  evaluations: InsightEvaluation[];
} {
  const dimensions = emptyDimensions();
  const evaluations: InsightEvaluation[] = [];

  for (const raw of rawItems || []) {
    const item = raw as InsightItem;
    const sources = flattenSources(raw);
    const ev = evaluateInsight(item, sources, now);
    evaluations.push(ev);
    if (!ev.displayable) continue;
    dimensions[item.dimension]?.push({ ...item, sources, outdated: ev.outdated });
  }

  // 每个维度内：新鲜在前、过时在后，再按 last_verified_at 倒序
  for (const dim of INSIGHT_DIMENSIONS) {
    dimensions[dim].sort((a, b) => {
      if (a.outdated !== b.outdated) return a.outdated ? 1 : -1;
      return (
        new Date(b.last_verified_at).getTime() - new Date(a.last_verified_at).getTime()
      );
    });
  }

  return { dimensions, evaluations };
}
