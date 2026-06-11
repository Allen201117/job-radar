// On-demand 富化（P3）：按 jd_url 反推官方 detail 端点抓 JD 正文，给用户「当下看到」的薄卡即时补 summary。
// 只覆盖**简单映射的 httpx 源**（detail = jd_url 拼接 + 一次 fetch）。复杂/浏览器源（moka 等）不在此，
// 靠后台 drain（crawler/enrich_backlog.py、backfill_moka）。与 Python crawler/enrich.py 同口径反推，
// 由 tests/enrich-client.test.js golden 用例钉死两边一致。CJS（node --test 可 require + 路由可 import）。

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
const TIMEOUT_MS = 15000;

async function fetchJson(url, init) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { ...(init || {}), signal: ctrl.signal });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

// 去 HTML 标签 + 解基础实体 + 收敛空白 + 截断（粗对齐 Python normalizer.clean_summary）。
function cleanSummary(raw) {
  if (!raw) return null;
  const text = String(raw)
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
  if (text.length < 10) return null;
  return text.length > 2000 ? text.slice(0, 2000) : text;
}

// workday：jd_url = {host}/{site}{ep}；detail = source_url 去尾 /jobs 再拼 {ep}（ep 从 /job/ 起）
async function detailWorkday({ jd_url, source_url }) {
  const m = new URL(jd_url).pathname.match(/(\/job\/.+)$/);
  if (!m) return null;
  const cxsBase = source_url.replace(/\/jobs\/?$/, "");
  const j = await fetchJson(`${cxsBase}${m[1]}`, {
    headers: { "User-Agent": UA, Accept: "application/json" },
  });
  return cleanSummary(j && j.jobPostingInfo && j.jobPostingInfo.jobDescription);
}

// hotjob：jd_url = {origin}/{suite}/pb/posDetail.html?postId=&postType=
const HOTJOB_RECRUIT = { society: 2, campus: 1, intern: 12 };
async function detailHotjob({ jd_url }) {
  const u = new URL(jd_url);
  const postId = u.searchParams.get("postId") || "";
  const postType = u.searchParams.get("postType") || "";
  const suite = u.pathname.split("/").filter(Boolean)[0] || "";
  if (!postId || !suite) return null;
  const origin = u.origin;
  const j = await fetchJson(`${origin}/wecruit/positionInfo/listPositionDetail/${suite}`, {
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
  if (!j || String(j.state) === "1017") return null; // 1017 = 已撤岗（后台 drain 会标 expired）
  const d = j.data || {};
  return cleanSummary([d.workContent, d.serviceCondition].filter(Boolean).join(" "));
}

// adapter_name -> TS 反推器（只简单 httpx 源；与 Python ENRICH_REGISTRY 的子集对齐）
const ENRICH_CLIENT = {
  workday: detailWorkday,
  hotjob: detailHotjob,
};

function enrichClientClass(adapter) {
  return Object.prototype.hasOwnProperty.call(ENRICH_CLIENT, adapter) ? "httpx" : null;
}

async function enrichOneClient(adapter, input) {
  const fn = ENRICH_CLIENT[adapter];
  if (!fn) return null;
  try {
    return await fn(input);
  } catch {
    return null;
  }
}

module.exports = {
  cleanSummary,
  ENRICH_CLIENT,
  enrichClientClass,
  enrichOneClient,
  detailWorkday,
  detailHotjob,
};
