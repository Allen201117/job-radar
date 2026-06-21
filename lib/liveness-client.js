// 点击时校验门的撤岗探测：用户点岗位的瞬间，服务端按 jd_url 反推官方 detail 端点探一下死活，
// 返回 "alive" | "dead" | "unknown"。与 Python crawler/enrich.py 的撤岗信号**同口径**
// （wt req_state=9501 / hotjob state=1017 / detail 404·410），由 tests/liveness-client.test.js golden 钉死。
//
// 安全不变量（与 sweep 一致）：**只在明确撤岗信号才判 dead**；任何拿不准（未知响应/非 404 错误/网络错/
// 超时/不支持的源）一律 "unknown" → 放行跳转，绝不误判活岗为死、绝不把用户卡死。
// 只覆盖有快速 JSON/HTTP 撤岗信号的 httpx 源（死岗大头 wt/hotjob + workday）；浏览器 SPA 源不在此，靠后台审计。
// CJS（路由可 import + node --test 可 require），镜像 lib/enrich-client.js 的 fetch 风格。

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
const TIMEOUT_MS = 2500; // 门用短超时：探不动就放行，绝不卡用户（点击路径在等，封顶压到 2.5s）

async function fetchRaw(url, init, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs || TIMEOUT_MS);
  try {
    return await fetch(url, { ...(init || {}), signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

const GONE = new Set([404, 410]); // 通用撤岗约定：detail 端点 404/410 = 已下架（_raise_if_gone 同口径）

// wt（老版 WinTalent）：撤岗 {origin}/wt/{brand}/web/json/position/detail?postId= → req_state=9501（无 postInfo）；
// 在招 req_state=9200 + postInfo。镜像 crawler/enrich.py _detail_wt。
async function livenessWt({ jd_url }) {
  const u = new URL(jd_url);
  const parts = u.pathname.split("/").filter(Boolean);
  if (parts.length < 2 || parts[0] !== "wt") return "unknown";
  const brand = parts[1];
  const postId = u.searchParams.get("postIdsAry") || u.searchParams.get("postId") || "";
  const rt = u.searchParams.get("recruitType") || "2";
  if (!postId) return "unknown";
  const origin = u.origin;
  const qs = new URLSearchParams({ brandCode: "1", recruitType: rt, postId }).toString();
  const r = await fetchRaw(`${origin}/wt/${brand}/web/json/position/detail?${qs}`, {
    headers: {
      "User-Agent": UA,
      Accept: "application/json, text/plain, */*",
      Referer: `${origin}/wt/${brand}/web/index`,
      Origin: origin,
    },
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const j = (await r.json()) || {};
  if (String(j.req_state) === "9501") return "dead";
  if (j.postInfo || String(j.req_state) === "9200") return "alive";
  return "unknown";
}

// hotjob（wecruit）：撤岗 POST listPositionDetail → state=1017；在招有 data。镜像 _detail_hotjob。
const HOTJOB_RECRUIT = { society: 2, campus: 1, intern: 12 };
async function livenessHotjob({ jd_url }) {
  const u = new URL(jd_url);
  const postId = u.searchParams.get("postId") || "";
  const postType = u.searchParams.get("postType") || "";
  const suite = u.pathname.split("/").filter(Boolean)[0] || "";
  if (!postId || !suite) return "unknown";
  const origin = u.origin;
  const r = await fetchRaw(`${origin}/wecruit/positionInfo/listPositionDetail/${suite}`, {
    method: "POST",
    headers: {
      "User-Agent": UA,
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/x-www-form-urlencoded",
      Referer: jd_url,
      Origin: origin,
    },
    body: new URLSearchParams({
      postId,
      recruitType: String(HOTJOB_RECRUIT[postType] != null ? HOTJOB_RECRUIT[postType] : 2),
    }).toString(),
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const j = (await r.json()) || {};
  if (String(j.state) === "1017") return "dead";
  if (j.data) return "alive";
  return "unknown";
}

// workday：detail = source_url 去尾 /jobs 再拼 jd_url 的 /job/{path}；撤岗 → cxs detail 404/410。镜像 _detail_workday。
async function livenessWorkday({ jd_url, source_url }) {
  const m = new URL(jd_url).pathname.match(/(\/job\/.+)$/);
  if (!m || !source_url) return "unknown";
  const cxsBase = source_url.replace(/\/jobs\/?$/, "");
  const r = await fetchRaw(`${cxsBase}${m[1]}`, {
    headers: { "User-Agent": UA, Accept: "application/json" },
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const j = (await r.json()) || {};
  if (j.jobPostingInfo) return "alive";
  return "unknown";
}

// adapter_name → 探活器（只覆盖有快速撤岗信号的 httpx 源；与 Python ENRICH_REGISTRY 的撤岗子集对齐）。
const LIVENESS = {
  wt: livenessWt,
  hotjob: livenessHotjob,
  workday: livenessWorkday,
};

function livenessSupported(adapter) {
  return Object.prototype.hasOwnProperty.call(LIVENESS, adapter);
}

// 探一个岗的死活。永不抛：任何异常（网络/超时/解析）→ "unknown"（放行），守住"绝不误判 + 绝不卡用户"。
async function checkLiveness(adapter, input) {
  const fn = LIVENESS[adapter];
  if (!fn) return "unknown";
  try {
    return await fn(input);
  } catch {
    return "unknown";
  }
}

module.exports = {
  checkLiveness,
  livenessSupported,
  livenessWt,
  livenessHotjob,
  livenessWorkday,
  TIMEOUT_MS,
};
