"use strict";
// 本土招聘源 adapter 名单 —— 选源排序（lib/refresh-scope.js）专用：国内意图下本土源优先抓取。
// ⚠️ 与 crawler/run.py 的 DOMESTIC_ADAPTERS 两处同步（仅用于选源排序，不参与资本来源国籍判定）。
//
// 资本来源「外企」判定的名单（FOREIGN_ATS_ADAPTERS）已收口到 lib/source-adapters.ts，
// 从每个 adapter 的 origin 字段自动派生（加 adapter 标一次 origin 即自动生效，单一数据源、零 drift）。
const DOMESTIC_ADAPTERS = new Set([
  "baidu", "jd", "bytedance", "bytedance_campus", "tencent",
  "nio_feishu", "xpeng_feishu", "horizon_feishu", "xiaomi_feishu", "haier",
  "moka", "beisen", "company_spa", "feishu", "hotjob", "wt", "netease", "oppo",
  "xiaohongshu", "alibaba", "huawei", "ctrip",
]);

function isDomesticAdapter(name) {
  return DOMESTIC_ADAPTERS.has(String(name == null ? "" : name).trim());
}

module.exports = { DOMESTIC_ADAPTERS, isDomesticAdapter };
