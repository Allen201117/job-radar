// 点击时校验门的撤岗探测：用户点岗位的瞬间，服务端按 jd_url 反推官方 detail 端点探一下死活，
// 返回 "alive" | "dead" | "unknown"。与 Python crawler/enrich.py 的撤岗信号**同口径**
// （wt req_state=9501 / hotjob state=1017 / detail 404·410），由 tests/liveness-client.test.js golden 钉死。
//
// 安全不变量（与 sweep 一致）：**只在明确撤岗信号才判 dead**；任何拿不准（未知响应/非 404 错误/网络错/
// 超时/不支持的源）一律 "unknown" → 放行跳转，绝不误判活岗为死、绝不把用户卡死。
// 覆盖有快速 JSON/HTTP 撤岗信号的 httpx 源：wt/hotjob/workday + C 类大厂自建门户
// （amazon/apple/meituan/microsoft/sf_express/tencent/vivo，2026-06-25 加）；浏览器 SPA 源（含 bilibili/phenom）靠后台审计。
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

// --- C 类大厂自建门户（2026-06-25，与 crawler/enrich.py 的 _detail_xxx 同口径、同 live 实测关闭信号）。
// 安全不变量同上：只在明确撤岗信号判 dead；拿不准/网络错/限流 → unknown（放行）。 ---

// amazon：HTML 逐岗页（.json 被 Akamai 拦）；撤岗→404，在招→200。
async function livenessAmazon({ jd_url }) {
  const r = await fetchRaw(jd_url, { headers: { "User-Agent": UA, Accept: "text/html,application/xhtml+xml" } });
  if (GONE.has(r.status)) return "dead";
  if (r.ok) return "alive";
  return "unknown";
}

// apple：jobNumber=jd_url 路径 /details/{jobNumber}/；jobDetails JSON；撤岗→404，在招→200 {res}。
async function livenessApple({ jd_url }) {
  const m = new URL(jd_url).pathname.match(/\/details\/([^/?]+)/);
  if (!m) return "unknown";
  const r = await fetchRaw(`https://jobs.apple.com/api/v1/jobDetails/${m[1]}`, {
    headers: { "User-Agent": UA, Accept: "application/json", Referer: "https://jobs.apple.com/" },
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const j = (await r.json()) || {};
  if (j.res) return "alive";
  return "unknown";
}

// meituan：POST getJobDetail {jobUnionId}；撤岗→status=0 无 data；在招→status=1+data。
async function livenessMeituan({ jd_url }) {
  const jid = new URL(jd_url).searchParams.get("jobUnionId") || "";
  if (!jid) return "unknown";
  const r = await fetchRaw("https://zhaopin.meituan.com/api/official/job/getJobDetail", {
    method: "POST",
    headers: {
      "User-Agent": UA,
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/json",
      Referer: "https://zhaopin.meituan.com/web/position",
      Origin: "https://zhaopin.meituan.com",
    },
    body: JSON.stringify({ jobUnionId: jid }),
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const j = (await r.json()) || {};
  if (!j.data && String(j.status) === "0") return "dead";
  if (j.data && String(j.status) === "1") return "alive";
  return "unknown";
}

// microsoft：pcsx search?query={displayJobId}；精确命中→alive，0 命中→dead。displayJobId=jd_url /job/{id}。
async function livenessMicrosoft({ jd_url }) {
  const m = new URL(jd_url).pathname.match(/\/job\/([^/?#]+)/);
  if (!m) return "unknown";
  const jid = m[1];
  const qs = new URLSearchParams({ domain: "microsoft.com", query: jid, start: "0", num: "20" }).toString();
  const r = await fetchRaw(`https://apply.careers.microsoft.com/api/pcsx/search?${qs}`, {
    headers: { "User-Agent": UA, Accept: "application/json", Referer: "https://jobs.careers.microsoft.com/" },
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const positions = (((await r.json()) || {}).data || {}).positions || [];
  if (positions.some((p) => String(p.displayJobId || p.id) === jid)) return "alive";
  if (positions.length === 0) return "dead";
  return "unknown";
}

// sf_express：JobSearchById 逐岗 HTML；撤岗→<title>顺丰人才招聘系统-404，在招→社会招聘标题。
async function livenessSfExpress({ jd_url }) {
  const r = await fetchRaw(jd_url, { headers: { "User-Agent": UA, Accept: "text/html" } });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const html = await r.text();
  const m = html.match(/<title>([\s\S]*?)<\/title>/);
  const title = m ? m[1].trim() : "";
  if (title === "顺丰人才招聘系统-404") return "dead";
  if (title.startsWith("顺丰人才招聘系统-")) return "alive";
  return "unknown";
}

// tencent：ByPostId?postId=；撤岗→Code=500 & Data="E1005"，在招→Code=200 & Data 对象。E1003=bogus 不判死。
async function livenessTencent({ jd_url }) {
  const pid = new URL(jd_url).searchParams.get("postId") || "";
  if (!pid) return "unknown";
  const qs = new URLSearchParams({ postId: pid }).toString();
  const r = await fetchRaw(`https://careers.tencent.com/tencentcareer/api/post/ByPostId?${qs}`, {
    headers: { "User-Agent": UA, Accept: "application/json", Referer: "https://careers.tencent.com/" },
  });
  if (GONE.has(r.status)) return "dead";
  const j = (await r.json().catch(() => null)) || {};
  if (String(j.Code) === "500" && String(j.Data) === "E1005") return "dead";
  if (String(j.Code) === "200" && j.Data && typeof j.Data === "object") return "alive";
  return "unknown";
}

// vivo：POST job/detail {job_id=_irjid}；撤岗→code=105002，在招→code=0+data。code=100000=服务器错不判死。
async function livenessVivo({ jd_url }) {
  const jid = new URL(jd_url).searchParams.get("_irjid") || "";
  if (!jid) return "unknown";
  const r = await fetchRaw("https://hr.vivo.com/api/social/webSite/portal/job/detail", {
    method: "POST",
    headers: {
      "User-Agent": UA,
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/json",
      Referer: "https://hr.vivo.com/jobs",
      Origin: "https://hr.vivo.com",
    },
    body: JSON.stringify({ job_id: jid }),
  });
  if (GONE.has(r.status)) return "dead";
  if (!r.ok) return "unknown";
  const j = (await r.json()) || {};
  if (String(j.code) === "105002") return "dead";
  if (String(j.code) === "0" && j.data) return "alive";
  return "unknown";
}

// adapter_name → 探活器（只覆盖有快速撤岗信号的 httpx 源；与 Python ENRICH_REGISTRY 的撤岗子集对齐）。
const LIVENESS = {
  wt: livenessWt,
  hotjob: livenessHotjob,
  workday: livenessWorkday,
  // C 类大厂自建门户（2026-06-25，live 验证关闭信号）：
  amazon: livenessAmazon,
  apple: livenessApple,
  meituan: livenessMeituan,
  microsoft: livenessMicrosoft,
  sf_express: livenessSfExpress,
  tencent: livenessTencent,
  vivo: livenessVivo,
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
  livenessAmazon,
  livenessApple,
  livenessMeituan,
  livenessMicrosoft,
  livenessSfExpress,
  livenessTencent,
  livenessVivo,
  TIMEOUT_MS,
};
