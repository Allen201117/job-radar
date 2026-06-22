"use strict";
/**
 * 「刷新公司库」范围解析（纯函数，可单测）。
 *
 * 当前筛选优先、未配字段用用户偏好兜底（CLAUDE.md 原则#2）→ 相关性打分 → 每 adapter|host
 * 多样性 cap（防单平台占满 N 槽）→ 总 cap N。返回选中的 source_ids（CI 照此选源刷新）。
 *
 * 选源排序遵守 CLAUDE.md「核心产品原则」：
 *   #1/#3 中国本土覆盖优先级 > 外企 —— 中文 / 国内城市查询时，本土 adapter（北森/moka/飞书系/
 *         wt/hotjob/字节/百度/京东…）排在外企 ATS（greenhouse/lever/workday…）前；外企量化/crypto
 *         公司（在港/海外为主）不再凭英文 metadata 挤占 N 槽、再被逐岗过滤清空导致结果坍缩到 1-2 家。
 *   #2    抓取默认依据用户偏好收窄；显式公司筛选时只放行命中公司，空筛选空偏好仍返回空范围。
 *
 * 注：抓取端 crawler/discovery.py filter_raw_jobs 仍按 关键词∩城市∩类型∩exclude 逐岗过滤（正确性底线，
 * 本函数不放宽它）；本函数只做「选哪些公司源」的粗粒度收窄，让 N 槽落在「可能命中该筛选」的公司上。
 */
const liveSearch = require("./live-search");
const expandSearchTerms =
  (liveSearch && liveSearch.expandSearchTerms) || ((q) => (q ? [String(q)] : []));

// 本土 adapter 名单收口到 lib/domestic-adapters（与 lib/company-origin 资本来源判定共用一份，避免 drift；
// 仍与 crawler/run.py 的 DOMESTIC_ADAPTERS 两处同步）。本土源=在华招聘为主；外企 ATS 多为在港/海外岗。
const { DOMESTIC_ADAPTERS } = require("./domestic-adapters");

// 明确的海外 / 港澳台意图：用户查这些地点时，外企 ATS 才是正解，不做本土优先压制。
const OVERSEAS_INTENT_MARKERS = [
  "香港", "hong kong", "hongkong", "澳门", "macau", "macao", "台湾", "taiwan",
  "新加坡", "singapore", "海外", "overseas", "global", "美国", "usa", "united states",
  "日本", "japan", "韩国", "korea", "欧洲", "europe",
];

const _lc = (s) => String(s == null ? "" : s).trim().toLowerCase();
const _arr = (a) => (Array.isArray(a) ? a : []);

function _hostOf(url) {
  try {
    return new URL(String(url || "")).host.toLowerCase();
  } catch {
    return "";
  }
}

// 城市核心词（去掉 市/省/特别行政区 等后缀），用于在 notes 里做包含匹配的「城市/HQ 信号」。
function _cityCore(city) {
  return _lc(city)
    .replace(/(特别行政区|自治区|地区|新区|城区|市辖区|省|市|区|县)$/u, "")
    .trim();
}

// manual 值优先（非空即用），否则用偏好兜底列表。统一为去空白小写、去重的 term 数组。
function _pickTerms(manual, fallbackList) {
  const m = _lc(manual);
  const base = m ? [m] : _arr(fallbackList).map(_lc).filter(Boolean);
  return Array.from(new Set(base));
}

// input: filters{company,keyword,city,jobType} + preferences{targetCompanies,targetKeywords,targetRoles,
//        excludeKeywords,city} + sources[]
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

  // 最强相关信号：已收录库里就有命中「城市+关键词(+类型)」岗位的公司（调用方用 jobs 表反查传入）。
  // exact = 还命中类型（完整命中用户筛选）。重爬这些公司必然产出结果——直接根治「选错公司→坍缩到 1 家」。
  const provenExactSet = new Set(_arr(input.provenExactCompanies).map(_lc).filter(Boolean));
  const provenSet = new Set(_arr(input.provenCompanies).map(_lc).filter(Boolean));

  // 有效城市（手动优先、未配用偏好兜底）→ 海外意图判定 + notes 城市信号。
  const effectiveCity = _lc(filters.city) || _lc(prefs.city);
  const cityCore = _cityCore(filters.city || prefs.city || "");
  const overseasIntent =
    !!effectiveCity && OVERSEAS_INTENT_MARKERS.some((m) => effectiveCity.includes(m));
  const domesticPreferred = !overseasIntent;

  // 本土基础入选权（扩覆盖）的触发条件：① 国内意图 ② 无显式公司收窄（有公司筛选时只放行命中公司）
  // ③ 至少有一个非公司筛选信号（城市/关键词/类型）。避免「空筛选空偏好」误把全部本土源拉进来。
  const hasCompanyNarrowing = companyTerms.length > 0;
  const hasNonCompanySignal =
    !!effectiveCity || keywordTerms.length > 0 || !!_lc(filters.jobType);
  const domesticBoostOn = domesticPreferred && !hasCompanyNarrowing && hasNonCompanySignal;

  const scored = [];
  for (const s of sources) {
    if (!s || !s.adapter_name || s.enabled === false) continue;
    const sCompany = _lc(s.company);
    const sText = _lc(`${s.company || ""} ${s.industry || ""} ${s.segment || ""}`);
    const notes = _lc(s.notes);
    if (excludeTerms.length && excludeTerms.some((t) => sCompany.includes(t))) continue;

    const isDomestic = DOMESTIC_ADAPTERS.has(s.adapter_name);
    let score = 0;
    // 已收录里真有该类岗位的公司：最高优先（远超下面所有 metadata 加成），保证重爬即出结果、结果多样。
    if (provenExactSet.has(sCompany)) score += 5000; // 命中 城市+关键词+类型
    else if (provenSet.has(sCompany)) score += 3000; // 命中 城市+关键词
    // 显式公司命中（手动筛选 / 偏好目标公司）—— 高权重，外企本土皆可命中（用户点名要的）。
    if (hasCompanyNarrowing && companyTerms.some((t) => sCompany.includes(t))) score += 1000;
    // 本土基础分：国内意图下让本土源整体排在外企前（100 ≫ 下面关键词/城市加成，外企永远压在本土之后）。
    if (domesticBoostOn && isDomestic) score += 100;
    // 关键词命中公司/行业 metadata（行业词如 游戏/金融 有效；职位词如 产品经理 多不命中行业，仅作弱加成）。
    if (keywordTerms.length && keywordTerms.some((t) => t && sText.includes(t))) score += 30;
    // 城市/HQ 信号：源 notes 明确提到用户所查城市 → 该公司更可能在该城有岗（schema 无 HQ 列，notes 是唯一可用信号）。
    if (cityCore && cityCore.length >= 2 && notes.includes(cityCore)) score += 40;

    if (score > 0) scored.push({ source: s, score });
  }

  // 稳定排序：仅按 score 降序（同分保持输入顺序，多样性 cap 再二次打散平台）。
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
