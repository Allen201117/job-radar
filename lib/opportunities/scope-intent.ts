// 求职范围（国内 / 海外 / 全都要）与用户自己说过的地点之间的关系（2026-09-28 立）。
//
// ❌ 现象（ux-walkthrough 09-24~27 每天 8/46 个画像）：求职范围「全都要」、目标城市全在国内、没有英文简历的用户，
//    /today 把美国岗排在同方向的本地岗前面（成都销售画像 TOP 10 里 7 个美国岗，卡片理由写「目标城市 US」）；
//    「海外」画像只召回 1 个岗也不回落国内（回落只认 0）。
// ✅ 根因：用户从没选过海外地区 —— 顶栏切换只提交 job_scope，`target_regions` 由服务端补成默认的 US/SG/Remote
//    （preferences-input.parsePreferenceScopeInput；全站也没有选地区的界面，线上 18 个非国内画像的值逐个都是这三项）。
//    而 stage-2 把「落在默认地区」算成地点命中（+15），召回 SQL 还把它排在用户自己填的城市前面 ⇒
//    一个系统替用户填的默认值，压过了用户亲手写的城市。
// ✅ 防：「全都要」且目标城市全在国内时，海外岗的地点只算 unknown（放行、轻罚）不算 match，召回层内改成城市在前；
//    「海外」画像对口岗太少（< THIN_OVERSEAS_FEED）时补上国内岗，并在页面上说清为什么。
//
// ⚠️ 本模块引 lib/geo（52KB 词表），只许服务端用：eligibility / 召回 SQL / today 页。别从会进客户端包的模块引它。
import { deriveCountryCode } from "../geo";
import type { CandidateProfile } from "../types";
import type { FeedSections, Opportunity, OpportunityFeed, RadarProfile } from "./types";

// deriveCountryCode 单次约 20µs，而 stage-2 每个海外岗都要问一次（全都要画像一次召回 1,000+ 个海外岗）→ 按城市数组身份缓存。
const allDomesticCache = new WeakMap<readonly string[], boolean>();

/** 用户填了目标城市，且每一个都判得出在中国（与 lib/geo.deriveCountryCode 同口径；香港 / 新加坡 / 判不出的都不算）。 */
export function targetCitiesAllDomestic(profile: Pick<RadarProfile, "targetLocations">): boolean {
  const cities = profile.targetLocations;
  const hit = allDomesticCache.get(cities);
  if (hit !== undefined) return hit;
  const v = cities.length > 0 && cities.every((c) => deriveCountryCode(c) === "CN");
  allDomesticCache.set(cities, v);
  return v;
}

/**
 * 「全都要」画像的海外岗该不该拿地点加分：目标城市全在国内时，默认海外地区不是用户说过的地点 → 不加。
 *
 * 只管「全都要」：它把国内岗与海外岗放在同一张清单里比分，地点分的偏差直接决定谁排前面。
 * 「海外」画像的清单里全是海外岗，统一降一档不改变任何相对顺序，只会把分数压到展示门槛下（被动强度门槛 70），
 * 白白让清单变短 —— 所以它保持原口径，清单太短由 {@link shouldTryDomesticFallback} 兜。
 * 没填城市的画像不动：它没有「用户说过的地点」可以对照（当前没有已就绪的这类非国内画像）。
 */
export function overseasLocationUnstated(profile: Pick<RadarProfile, "jobScope" | "targetLocations">): boolean {
  return profile.jobScope === "all" && targetCitiesAllDomestic(profile);
}

/** 「海外」画像对口岗少于这个数就补国内岗。与 ux-walkthrough 的 THIN_SHOWN_BAD 同值：少于它首屏都填不满。 */
export const THIN_OVERSEAS_FEED = 10;

/** 求职范围不是国内、目标城市全在国内、又没有英文简历 —— 海外池里本来就难有对口岗，允许按国内补。 */
export function canFallbackToDomestic(profile: RadarProfile, candidate: Pick<CandidateProfile, "has_en_resume"> | null): boolean {
  if (profile.jobScope === "domestic") return false;
  if (candidate?.has_en_resume) return false;
  return targetCitiesAllDomestic(profile);
}

/**
 * 要不要多跑一次国内召回。「海外」：展示岗 < {@link THIN_OVERSEAS_FEED}；「全都要」：只在 0 岗时（原口径）。
 * 「全都要」不放宽是量过的：它的召回本来就含国内岗，2026-09-28 真实画像逐个重放，按国内重算的展示数
 * 没有一个多于原清单 —— 放宽只会给每次打开白加一次冷召回（2~5s）。
 */
export function shouldTryDomesticFallback(
  profile: RadarProfile,
  candidate: Pick<CandidateProfile, "has_en_resume"> | null,
  scopedTotal: number,
): boolean {
  if (!canFallbackToDomestic(profile, candidate)) return false;
  return profile.jobScope === "overseas" ? scopedTotal < THIN_OVERSEAS_FEED : scopedTotal === 0;
}

export interface ScopeFallback {
  /** 用户选的范围（文案用）。 */
  scope: "overseas" | "all";
  /** 原范围里找到的展示岗数（它们排在最前）。 */
  scopedCount: number;
  /** 补进来的国内岗数。 */
  addedCount: number;
}

const SECTION_KEYS: Array<keyof FeedSections> = ["critical", "main", "explore", "momentum", "waiting"];

/**
 * 原范围的岗在前、国内补充的岗在后，按区合并（同一个岗只出现一次）。国内一个新岗都补不出来 → null（不回落）。
 *
 * 不整个换成国内清单：用户选了海外，原范围里找到的那几个岗是他要的，换掉就丢了。
 * 关键提醒来自用户自己的收藏 / 投递，两次构建算的是同一批，合并时按 id 去重。
 */
export function mergeDomesticFallback(
  scoped: OpportunityFeed,
  domestic: OpportunityFeed,
  scope: "overseas" | "all",
): { feed: OpportunityFeed; fallback: ScopeFallback } | null {
  const seen = new Set<string>();
  const sections = {} as FeedSections;
  // 计数只算机会卡、不算关键提醒：提醒是用户自己收藏 / 投递的岗，不是「这个范围里找到的对口机会」，
  // 算进去文案会说「海外找到 3 个」而其实一个海外岗都没有。
  let scopedCount = 0;
  for (const key of SECTION_KEYS) {
    const merged: Opportunity[] = [];
    for (const o of scoped.sections[key] || []) {
      if (seen.has(o.job.id)) continue;
      seen.add(o.job.id);
      merged.push(o);
      if (key !== "critical") scopedCount += 1;
    }
    sections[key] = merged;
  }
  let addedCount = 0;
  for (const key of SECTION_KEYS) {
    for (const o of domestic.sections[key] || []) {
      if (seen.has(o.job.id)) continue;
      seen.add(o.job.id);
      sections[key].push(o);
      if (key !== "critical") addedCount += 1;
    }
  }
  if (addedCount === 0) return null;

  const shown = SECTION_KEYS.flatMap((key) => sections[key]);
  const by_signal: OpportunityFeed["counts"]["by_signal"] = {};
  for (const o of shown) {
    const type = o.signals[0]?.type;
    if (type) by_signal[type] = (by_signal[type] ?? 0) + 1;
  }
  const sumFiltered = (a = scoped.counts.filtered, b = domestic.counts.filtered) =>
    a && b
      ? {
          inactive: a.inactive + b.inactive,
          mismatch: a.mismatch + b.mismatch,
          low_score: a.low_score + b.low_score,
          thin: a.thin + b.thin,
        }
      : (a ?? b);
  return {
    feed: {
      ...scoped,
      candidate_capped: scoped.candidate_capped || domestic.candidate_capped,
      counts: {
        total: shown.length,
        critical: sections.critical.length,
        main: sections.main.length,
        by_signal,
        screened: (scoped.counts.screened ?? 0) + (domestic.counts.screened ?? 0),
        filtered: sumFiltered(),
      },
      sections,
    },
    fallback: { scope, scopedCount, addedCount },
  };
}

/** /today 顶部那一句说明。先说用户选了什么、再说为什么补、最后给能做的动作。 */
export function scopeFallbackNotice(fb: ScopeFallback): string {
  const scopeLabel = fb.scope === "overseas" ? "海外" : "全都要";
  const why = "你的目标城市都在国内、也还没有英文简历";
  const next = "要看更多海外机会，先在个人中心补一份英文简历。";
  if (fb.scopedCount === 0) {
    return `你把求职范围设成了${scopeLabel}，但${why}，这个范围里没有对口的机会。下面按国内范围展示；${next}`;
  }
  return (
    `你把求职范围设成了${scopeLabel}，但${why}，${fb.scope === "overseas" ? "海外岗位" : "这个范围"}里只找到 ${fb.scopedCount} 个对口机会（排在最前）。` +
    `后面补上了 ${fb.addedCount} 个国内的对口岗位；${next}`
  );
}
