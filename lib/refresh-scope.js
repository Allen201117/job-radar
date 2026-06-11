"use strict";
/**
 * 「刷新公司库」范围解析（纯函数，可单测）。
 *
 * 当前筛选优先、未配字段用用户偏好兜底（CLAUDE.md 原则#2）→ 相关性打分 → 每 adapter|host
 * 多样性 cap（防单平台占满 N 槽）→ 总 cap N。返回选中的 source_ids（CI 照此选源刷新）。
 *
 * 注：抓取端 crawler/discovery.py filter_raw_jobs 还会按 关键词/城市/类型/exclude 逐岗过滤，
 * 故本函数只做「选哪些公司源」的粗粒度收窄；exclude 在这里也顺手剔掉公司名命中的源。
 */
const liveSearch = require("./live-search");
const expandSearchTerms =
  (liveSearch && liveSearch.expandSearchTerms) || ((q) => (q ? [String(q)] : []));
const INLINE_LIVE_ADAPTERS =
  (liveSearch && liveSearch.INLINE_LIVE_ADAPTERS) || new Set();

const _lc = (s) => String(s == null ? "" : s).trim().toLowerCase();
const _arr = (a) => (Array.isArray(a) ? a : []);

function _hostOf(url) {
  try {
    return new URL(String(url || "")).host.toLowerCase();
  } catch {
    return "";
  }
}

// manual 值优先（非空即用），否则用偏好兜底列表。统一为去空白小写、去重的 term 数组。
function _pickTerms(manual, fallbackList) {
  const m = _lc(manual);
  const base = m ? [m] : _arr(fallbackList).map(_lc).filter(Boolean);
  return Array.from(new Set(base));
}

// input: filters{company,keyword} + preferences{targetCompanies,targetKeywords,targetRoles,excludeKeywords} + sources[]
// opts: cap(默认25) / perHostCap(默认3)。返回 sourceIds / sources / matchedCount / droppedCount。
function resolveRefreshScope(input = {}, opts = {}) {
  const filters = input.filters || {};
  const prefs = input.preferences || {};
  const sources = _arr(input.sources);
  const cap = Math.max(1, opts.cap || 25);
  const perHostCap = Math.max(1, opts.perHostCap || 3);

  const companyTerms = _pickTerms(filters.company, prefs.targetCompanies);
  const rawKeywordTerms = _pickTerms(filters.keyword, [
    ..._arr(prefs.targetKeywords),
    ..._arr(prefs.targetRoles),
  ]);
  // 关键词扩展（中英同义 / 缩写），让中文偏好词也能命中英文 industry/segment。
  const keywordTerms = Array.from(
    new Set(
      rawKeywordTerms
        .flatMap((t) => {
          try {
            return [t, ...expandSearchTerms(t).map(_lc)];
          } catch {
            return [t];
          }
        })
        .filter(Boolean),
    ),
  );
  const excludeTerms = Array.from(
    new Set(_arr(prefs.excludeKeywords).map(_lc).filter(Boolean)),
  );

  const scored = [];
  for (const s of sources) {
    if (!s || !s.adapter_name || s.enabled === false) continue;
    const sCompany = _lc(s.company);
    const sText = _lc(`${s.company || ""} ${s.industry || ""} ${s.segment || ""}`);
    if (excludeTerms.length && excludeTerms.some((t) => sCompany.includes(t))) continue;
    let score = 0;
    if (companyTerms.length && companyTerms.some((t) => sCompany.includes(t))) score += 100;
    if (keywordTerms.length && keywordTerms.some((t) => t && sText.includes(t))) score += 20;
    if (INLINE_LIVE_ADAPTERS.has(s.adapter_name)) score += 3; // 快源略优先（CI 内先出结果）
    if (score > 0) scored.push({ source: s, score });
  }

  scored.sort((a, b) => b.score - a.score);

  // 多样性 cap：第一轮每 adapter|host 最多 perHostCap（避免 25 槽被单平台 Moka 占满，结果更多样）；
  // 不足 cap 再二轮放宽填满（recipe 串行抓取无 Errno-35，单主机只影响时长，已被总 cap 兜住）。
  const picked = [];
  const seen = new Set();
  const perKey = new Map();
  for (const item of scored) {
    if (picked.length >= cap) break;
    const key = `${item.source.adapter_name}|${_hostOf(item.source.source_url)}`;
    const used = perKey.get(key) || 0;
    if (used >= perHostCap) continue;
    perKey.set(key, used + 1);
    picked.push(item.source);
    seen.add(item.source.id);
  }
  for (const item of scored) {
    if (picked.length >= cap) break;
    if (seen.has(item.source.id)) continue;
    picked.push(item.source);
    seen.add(item.source.id);
  }

  return {
    sourceIds: picked.map((s) => s.id),
    sources: picked,
    matchedCount: scored.length,
    droppedCount: Math.max(0, scored.length - picked.length),
  };
}

module.exports = { resolveRefreshScope };
