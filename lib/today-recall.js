"use strict";
/**
 * Today 看板「偏好预筛 + 最新兜底」两段召回的合并逻辑（纯函数，可单测）。
 *
 * 背景：jobs 表数百源每日抓取，盲取最新 200 条会被最后爬完的大厂批量岗位刷屏，
 * 且用户偏好只参与排序、未参与召回。改为先按偏好 SQL 预筛，预筛结果不足时再用
 * 「最新 active」兜底凑数，保证看板不空。本函数只负责「合并 + 去重 + 兜底门槛 +
 * 截断」，不碰 IO。preferred 始终排在 fallback 前，内部按 id 去重。
 *
 * @param {Array} preferred 偏好预筛结果（已按 first_seen_at desc 排好）
 * @param {Array} fallback  最新 active 岗位（仅当预筛不足时用于补齐）
 * @param {{target?: number, minPreferred?: number}} [opts]
 *   target=召回总上限（默认 200）；minPreferred=预筛达到此数则不再兜底（默认 50）
 * @returns {Array} 合并去重后的岗位（preferred 在前，长度 ≤ target）
 */
function mergeRecallJobs(preferred, fallback, opts) {
  const target = opts && opts.target != null ? opts.target : 200;
  const minPreferred = opts && opts.minPreferred != null ? opts.minPreferred : 50;

  const seen = new Set();
  const out = [];

  const take = (list) => {
    if (!Array.isArray(list)) return;
    for (const job of list) {
      if (out.length >= target) return;
      if (!job || job.id == null || seen.has(job.id)) continue;
      seen.add(job.id);
      out.push(job);
    }
  };

  take(preferred);

  // 仅当预筛结果不足门槛时才用最新岗位兜底，避免无关大厂岗位稀释偏好相关性
  if (out.length < minPreferred) {
    take(fallback);
  }

  return out;
}

module.exports = { mergeRecallJobs };
