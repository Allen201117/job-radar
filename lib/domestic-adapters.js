"use strict";
// adapter → 资本来源 的判定依据，两个用途：
//  ① 选源排序（lib/refresh-scope.js）：DOMESTIC_ADAPTERS = 国内意图下优先抓取的本土核心源。
//  ② 资本来源筛选国籍判定（lib/company-origin.ts）：FOREIGN_ATS_ADAPTERS = 外企 ATS / 外企自建源白名单，
//     名单外的公司一律按「中国」兜底 —— 库里岗位绝大多数为本土，未知归中国，"外企"筛选才能挡住
//     大量「公司名没收录 + 不是外企源」的本土公司（治本：选外企不再混入中国企业）。
//
// 为什么判定用「外企白名单」而非「本土白名单」：外企在华一律走这十几个国际 ATS / 自建站，名单稳定、
// 不随国内大厂新增而变；而本土 adapter 持续新增（meituan/bilibili/vivo/byd/sf_express…），维护本土
// 全名单极易漏判。识别少数稳定的外企源、其余默认本土，更不易漏。
//
// ⚠️ DOMESTIC_ADAPTERS 仍与 crawler/run.py 的同名集合两处同步（仅用于选源排序，不参与国籍判定）。

const DOMESTIC_ADAPTERS = new Set([
  "baidu", "jd", "bytedance", "bytedance_campus", "tencent",
  "nio_feishu", "xpeng_feishu", "horizon_feishu", "xiaomi_feishu", "haier",
  "moka", "beisen", "company_spa", "feishu", "hotjob", "wt", "netease", "oppo",
  "xiaohongshu", "alibaba", "huawei", "ctrip",
]);

// 外企 ATS / 外企自建招聘源 adapter（与 crawler/run.py ADAPTERS 中标注的跨国企业源对齐）。
// 通用国际 ATS（外企在华招聘主力）+ 外企自建巨头门户。新增外企源基本仍落在这些 adapter 上。
const FOREIGN_ATS_ADAPTERS = new Set([
  "apple", "apple_cn", "siemens",
  "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "eightfold", "oracle",
  "amazon", "phenom", "microsoft", "google",
]);

function isDomesticAdapter(name) {
  return DOMESTIC_ADAPTERS.has(String(name == null ? "" : name).trim());
}

function isForeignAtsAdapter(name) {
  return FOREIGN_ATS_ADAPTERS.has(String(name == null ? "" : name).trim());
}

module.exports = {
  DOMESTIC_ADAPTERS,
  FOREIGN_ATS_ADAPTERS,
  isDomesticAdapter,
  isForeignAtsAdapter,
};
