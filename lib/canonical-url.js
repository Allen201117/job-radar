/**
 * canonical_jd_url —— 把同一岗位的链接变体归一到同一把冲突键。
 *
 * 规则（保守，只做不会破坏真实详情链接的归一）：
 *   1. null/undefined 原样返回；空白串 trim 后返回。
 *   2. 含 '#'（SPA hash 路由：Moka/北森/飞书/携程等）→ 整串原样返回，绝不动 fragment——
 *      这些源的岗位身份就在 fragment 里，动它会把详情链接打断。
 *   3. 去掉 query 里的常见 tracking 参数（utm_* 前缀 + 一组明确的统计/广告参数），保留业务参数（id 等）。
 *   4. 规范化 base 的尾斜杠（去掉末尾 /）。
 *
 * ⚠️ 三处实现必须逐字一致：本文件 / crawler/normalizer.py canonicalize_jd_url /
 *    supabase/migrations 的 SQL canonicalize_jd_url()。改规则三处同改，
 *    并同步 tests/canonical-url.test.js + crawler/test_normalizer.py 两套测试。
 */

// 明确是 tracking 的精确参数名（小写比较）。只收纯统计/广告参数——绝不收 from/source/ref/channel
// 这类可能是 ATS 深链业务参数的词，避免把两个不同岗位误并成一个。
const TRACKING_PARAM_KEYS = new Set([
  "spm",
  "scm",
  "bd_vid",
  "gclid",
  "fbclid",
  "msclkid",
  "yclid",
  "hmsr",
  "hmpl",
  "hmcu",
  "hmkw",
  "hmci",
  "_ga",
  "gio_link_id",
]);

function isTrackingKey(key) {
  const k = key.toLowerCase();
  return k.startsWith("utm_") || TRACKING_PARAM_KEYS.has(k);
}

function canonicalizeJdUrl(url) {
  if (url == null) return url; // null / undefined 原样
  const s = String(url).trim();
  if (!s) return s;
  if (s.indexOf("#") >= 0) return s; // SPA hash 路由保守不动

  const qpos = s.indexOf("?");
  let base = qpos >= 0 ? s.slice(0, qpos) : s;
  let query = qpos >= 0 ? s.slice(qpos + 1) : "";

  if (query) {
    query = query
      .split("&")
      .filter((part) => part && !isTrackingKey(part.split("=", 1)[0]))
      .join("&");
  }

  base = base.replace(/\/+$/, "");
  return query ? base + "?" + query : base;
}

module.exports = { canonicalizeJdUrl };
