"""按 jd_url 反推官方 detail 端点 → 返回 JD 正文（summary）文本。

drain worker（enrich_backlog.py）+ on-demand（P3）共用。为何按 jd_url 反推而非 re-crawl 列表：
适配器补正文只作用于「当前仍挂 live 列表」的岗位，存量里已不在列表但仍 active 的空 summary 行
re-crawl 永远碰不到（实测 oracle 重爬 77→74 只清 3 行）——必须按 jd_url 直推 detail 端点。

httpx 类（无浏览器、可高并发）：workday/oracle/eightfold/smartrecruiters（搬已 live 验证的
backfill_foreign_summaries 逻辑）+ hotjob。browser 类（beisen/moka/feishu）P2 再加。

fetcher 签名：f(row: dict, src: dict) -> str（空串 = 无正文/已撤岗/404；异常上抛由调用方计死信）。
  row 需含 jd_url（+ title/job_type 供调用方派生）；src 需含 source_url/adapter_name。
"""
import html as html_lib
import json
import re
from urllib.parse import urlparse, parse_qs

import httpx
from selectolax.parser import HTMLParser

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      "Accept": "application/json"}
TIMEOUT = 25


class JobClosedError(Exception):
    """源站明确告知该岗位已撤下/招聘已关闭（如 hotjob detail 返回 state=1017）。

    与「无正文」(fetcher 返回 "") 区分：这类岗永远补不到 summary 且应置 status='expired'，
    不是死信。**只在明确关闭信号时抛**——网络错误/限流仍走普通异常（调用方计 miss 重试），不得 expired。
    """


def _raise_if_gone(r):
    """通用撤岗约定：任何 ATS 的 detail 端点返回 404/410 = 岗位已下架 → JobClosedError。
    每个 fetcher 拿到响应后调一行即继承该约定，杜绝逐源遗漏（统一底座）。
    仅 404/410（明确 Gone）；5xx/429 等瞬时错误放行（调用方走 miss 重试，绝不误判为撤岗）。"""
    if r.status_code in (404, 410):
        raise JobClosedError(f"detail gone (HTTP {r.status_code})")


# --- 外企四家族：搬 scripts/backfill_foreign_summaries.py（已 live 验证，全是公开 JSON API） ---
def _detail_workday(row, src):
    # jd_url = {host}/{site}{ep}；detail = source_url 去尾部 /jobs 再拼 {ep}（ep 从 /job/ 起）
    m = re.search(r"(/job/.+)$", urlparse(row["jd_url"]).path)
    if not m:
        return ""
    cxs_base = re.sub(r"/jobs/?$", "", src["source_url"])
    r = httpx.get(f"{cxs_base}{m.group(1)}", headers=UA, timeout=TIMEOUT)
    _raise_if_gone(r)  # cxs /job/{path} 404 = 岗位下架
    if r.status_code >= 300:
        return ""
    return (r.json().get("jobPostingInfo", {}) or {}).get("jobDescription") or ""


def _detail_oracle(row, src):
    # jd_url = {host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}
    m = re.search(r"/sites/([^/]+)/job/(\w+)", row["jd_url"])
    if not m:
        return ""
    p = urlparse(row["jd_url"])
    url = (f"{p.scheme}://{p.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
           f'?onlyData=true&expand=all&finder=ById;Id="{m.group(2)}",siteNumber={m.group(1)}')
    r = httpx.get(url, headers=UA, timeout=TIMEOUT)
    _raise_if_gone(r)  # REST 端点 404 = requisition 已撤
    if r.status_code >= 300:
        return ""
    items = r.json().get("items", []) or []
    if not items:
        # finder by Id 返回 200 + items:[] = 该 requisition 已从 CE 撤下 = 撤岗信号。
        # （此处必是 2xx：非 2xx 已在上面拦截走 miss 重试，不会误判瞬时错误为撤岗。）
        raise JobClosedError(f"oracle requisition gone (items=0): {m.group(2)}")
    it = items[0]
    parts = [it.get("ExternalDescriptionStr") or it.get("ShortDescriptionStr"),
             it.get("ExternalResponsibilitiesStr"), it.get("ExternalQualificationsStr")]
    return " ".join(x for x in parts if x)


def _detail_eightfold(row, src):
    # jd_url 是公司自有域名 canonicalPositionUrl，position id = 路径里的长数字段；
    # detail 端点在 eightfold 租户域上（source_url 的 origin + ?domain=）
    m = re.search(r"/(\d{9,})(?:[/?#]|$)", row["jd_url"])
    if not m:
        return ""
    sp = urlparse(src["source_url"])
    domain = (parse_qs(sp.query).get("domain") or [""])[0]
    url = f"{sp.scheme}://{sp.netloc}{sp.path}/{m.group(1)}"
    r = httpx.get(url, params={"domain": domain}, headers=UA, timeout=TIMEOUT)
    _raise_if_gone(r)  # position 详情 404 = 岗位下架
    if r.status_code >= 300:
        return ""
    return r.json().get("job_description") or ""


def _detail_smartrecruiters(row, src):
    # jd_url = https://jobs.smartrecruiters.com/{identifier}/{postingId}
    parts = [x for x in urlparse(row["jd_url"]).path.split("/") if x]
    if len(parts) < 2:
        return ""
    identifier, pid = parts[0], parts[1]
    r = httpx.get(f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{pid}",
                  headers=UA, timeout=TIMEOUT)
    _raise_if_gone(r)  # posting 404 = 岗位已撤/下架
    if r.status_code >= 300:
        return ""
    secs = (r.json().get("jobAd") or {}).get("sections") or {}
    parts = [(secs.get(k) or {}).get("text")
             for k in ("jobDescription", "responsibilities", "qualifications")]
    return " ".join(x for x in parts if x)


def _detail_greenhouse(row, src):
    # board token 取自 source_url(.../boards/{token}/jobs)，job id 取自 jd_url(.../jobs/{id})；
    # detail = 公开 boards-api（无鉴权）。撤岗 → 404（_raise_if_gone）。content 为 HTML 实体，clean_summary 解码。
    board = re.search(r"/boards/([^/]+)/jobs", src.get("source_url") or "")
    jid = re.search(r"/jobs/(\d+)", row["jd_url"])
    if not (board and jid):
        return ""
    r = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{board.group(1)}/jobs/{jid.group(1)}",
                  headers=UA, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    return r.json().get("content") or ""


def _detail_lever(row, src):
    # site 取自 source_url(.../postings/{site})，id = jd_url(jobs.lever.co/{site}/{id}) 末段；
    # detail = 公开 postings API（无鉴权）。撤岗 → 404。正文 = description + lists 各段 content + additional。
    site = re.search(r"/postings/([^/?]+)", src.get("source_url") or "")
    segs = [x for x in urlparse(row["jd_url"]).path.split("/") if x]
    if not (site and segs):
        return ""
    r = httpx.get(f"https://api.lever.co/v0/postings/{site.group(1)}/{segs[-1]}",
                  headers=UA, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    d = r.json() or {}
    lists = " ".join((x.get("content") or "") for x in (d.get("lists") or []))
    return " ".join(x for x in (d.get("description"), lists, d.get("additional")) if x)


# --- hotjob：jd_url = {origin}/{suite}/pb/posDetail.html?postId=&postType= ---
# 详情接口 = {origin}/wecruit/positionInfo/listPositionDetail/{suite}，POST postId + recruitType。
# recruitType 由 postType 推回（与 adapters/hotjob.py 的 _CHANNEL_BY_PAGE 同口径）。
_HOTJOB_RECRUIT = {"society": 2, "campus": 1, "intern": 12}


def _detail_hotjob(row, src):
    p = urlparse(row["jd_url"])
    q = parse_qs(p.query)
    post_id = (q.get("postId") or [""])[0]
    post_type = (q.get("postType") or [""])[0]
    suite = next((x for x in (p.path or "").split("/") if x), "")
    if not (post_id and suite):
        return ""
    origin = f"{p.scheme}://{p.netloc}"
    headers = {**UA, "Accept": "application/json, text/plain, */*",
               "Content-Type": "application/x-www-form-urlencoded",
               "Referer": row["jd_url"], "Origin": origin}
    r = httpx.post(f"{origin}/wecruit/positionInfo/listPositionDetail/{suite}",
                   data={"postId": post_id, "recruitType": _HOTJOB_RECRUIT.get(post_type, 2)},
                   headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)  # detail 端点 404/410（state=1017 在下方另判）
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    # 已撤岗：HTTP 200 + {"state":"1017","msg":"...招聘已经关闭...","type":"warning"}，无 data。
    # 这是明确的过期信号（≠ 无正文），上抛由调用方置 status='expired'。
    if str(j.get("state")) == "1017":
        raise JobClosedError(f"hotjob postId={post_id} closed: {j.get('msg') or 'state=1017'}")
    d = j.get("data") or {}
    return " ".join(x for x in (d.get("workContent"), d.get("serviceCondition")) if x)


# --- wt（老版 WinTalent）：jd_url = {origin}/wt/{brand}/mobweb/position/detail?...&recruitType=&postIdsAry= ---
# 撤岗信号：{origin}/wt/{brand}/web/json/position/detail?postId= 返回 {"req_state":9501,
# "req_msg":"该职位招聘已经关闭…"}（无 postInfo）；在招返回 req_state=9200 + postInfo
# （workContent/serviceCondition=正文）。镜像 hotjob 的 state=1017（live 验证 feihe+yili：9200 在招 / 9501 撤岗）。
def _detail_wt(row, src):
    p = urlparse(row["jd_url"])
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2 or parts[0] != "wt":
        return ""
    brand = parts[1]
    q = parse_qs(p.query)
    post_id = (q.get("postIdsAry") or q.get("postId") or [""])[0]
    rt = (q.get("recruitType") or ["2"])[0]
    if not post_id:
        return ""
    origin = f"{p.scheme}://{p.netloc}"
    headers = {**UA, "Accept": "application/json, text/plain, */*",
               "Referer": f"{origin}/wt/{brand}/web/index", "Origin": origin}
    r = httpx.get(f"{origin}/wt/{brand}/web/json/position/detail",
                  params={"brandCode": 1, "recruitType": rt, "postId": post_id},
                  headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)  # detail 端点 404/410（req_state=9501 在下方另判）
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    # 已撤岗：req_state=9501 + "招聘已经关闭"（无 postInfo）= expired 信号（≠ 无正文）。
    # 保守：只认 9501；其它/未知 req_state 一律落回 ""(miss)，绝不误判活岗为撤岗（安全不变量）。
    if str(j.get("req_state")) == "9501":
        raise JobClosedError(f"wt postId={post_id} closed: {j.get('req_msg') or 'req_state=9501'}")
    pi = j.get("postInfo") or {}
    return " ".join(x for x in (pi.get("workContent"), pi.get("serviceCondition")) if x)


# --- C 类大厂自建门户：逐岗撤岗探活器（2026-06-25 逐源 live 摸到关闭信号，禁猜；§1 红线：
# 只在明确关闭信号判死，bogus/网络错/限流一律走 miss 重试，绝不误判活岗为死）。
# 多数 liveness-only（正文已由列表自带，detail 只用来探死活）；tencent/vivo 顺带返回正文。
# 关闭信号 live 实测见记忆 job-radar-cclass-liveness-signals。 ---

def _detail_amazon(row, src):
    # amazon.jobs 逐岗 .json 被 Akamai 拦（404/406）；但 HTML 逐岗页 httpx 可直连：
    # 在招→200，撤岗/不存在→404（live 验证 bogus id 直接 404）。liveness-only（正文由列表自带）。
    r = httpx.get(row["jd_url"], headers={**UA, "Accept": "text/html,application/xhtml+xml"}, timeout=TIMEOUT)
    _raise_if_gone(r)  # 404/410 = 岗位已撤
    return ""


def _detail_apple(row, src):
    # jobNumber = jd_url 路径 /details/{jobNumber}/；detail = 公开 jobDetails JSON。
    # 撤岗→404 {"error":"jobsite.general.serviceError"}（live 验证 4/30 真实撤岗岗 = 404）；在招→200 {res}。
    m = re.search(r"/details/([^/?]+)", urlparse(row["jd_url"]).path)
    if not m:
        return ""
    r = httpx.get(f"https://jobs.apple.com/api/v1/jobDetails/{m.group(1)}",
                  headers={**UA, "Referer": "https://jobs.apple.com/"}, timeout=TIMEOUT)
    _raise_if_gone(r)  # 404 = 岗位已撤
    return ""


def _detail_meituan(row, src):
    # detail POST {jobUnionId}；撤岗/不存在→200 {"data":null,"status":0,"message":"职位已下线或不存在！"}；
    # 在招→status=1 + data。liveness-only（正文由列表 jobDuty/jobRequirement 自带；detail.desc 恒空）。
    # ⚠️ jobStatus 000/001 都是活岗（红鲱鱼，别拿来判死）；唯一关闭信号 = status==0 且无 data。
    jid = (parse_qs(urlparse(row["jd_url"]).query).get("jobUnionId") or [""])[0]
    if not jid:
        return ""
    headers = {**UA, "Referer": "https://zhaopin.meituan.com/web/position",
               "Origin": "https://zhaopin.meituan.com", "Content-Type": "application/json"}
    r = httpx.post("https://zhaopin.meituan.com/api/official/job/getJobDetail",
                   json={"jobUnionId": jid}, headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    if not j.get("data") and str(j.get("status")) == "0":
        raise JobClosedError(f"meituan jobUnionId={jid} closed: {j.get('message') or 'status=0'}")
    return ""


def _detail_microsoft(row, src):
    # MS pcsx 无逐岗 detail 端点；用 search?query={displayJobId} 探活：在招→positions 含精确 displayJobId（n=1）；
    # 撤岗→0 命中（live 验证：在招精确命中、bogus n=0）。displayJobId = jd_url 路径 /job/{id}。
    # 正文：精确命中后再 GET apply.careers.microsoft.com/careers/job/{positionId}（SSR，无 Akamai，
    # 内嵌 schema.org JobPosting ld+json，description ~3k 字，live 验证 200）→ 682 张薄卡由此补正文。
    m = re.search(r"/job/([^/?#]+)", urlparse(row["jd_url"]).path)
    if not m:
        return ""
    jid = m.group(1)
    r = httpx.get("https://apply.careers.microsoft.com/api/pcsx/search",
                  params={"domain": "microsoft.com", "query": jid, "start": 0, "num": 20},
                  headers={**UA, "Referer": "https://jobs.careers.microsoft.com/"}, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    positions = (r.json().get("data", {}) or {}).get("positions", []) or []
    hit = next((p for p in positions if str(p.get("displayJobId") or p.get("id")) == jid), None)
    if hit is not None:
        return _microsoft_description(str(hit.get("id") or ""))  # 在招 → 顺手补正文（失败返空不影响探活）
    if not positions:
        # HTTP 200 + 0 命中 = 撤岗（与 bogus 同信号；限流/错误已在上面 >=300 拦走 miss）。
        raise JobClosedError(f"microsoft displayJobId={jid} closed (search 0 hit)")
    return ""  # n>0 但无精确命中 → 拿不准，不判死


def _microsoft_description(position_id: str) -> str:
    """SSR 详情页 ld+json JobPosting.description；任何失败静默返空（liveness 结论已在上游给出）。"""
    if not position_id:
        return ""
    try:
        r = httpx.get(f"https://apply.careers.microsoft.com/careers/job/{position_id}",
                      params={"domain": "microsoft.com"},
                      headers={**UA, "Referer": "https://jobs.careers.microsoft.com/"}, timeout=TIMEOUT)
        if r.status_code >= 300:
            return ""
        m = re.search(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", r.text, re.S)
        if not m:
            return ""
        data = json.loads(m.group(1))
        if not isinstance(data, dict) or data.get("@type") != "JobPosting":
            return ""
        return html_lib.unescape(str(data.get("description") or "")).strip()
    except Exception:
        return ""


def _detail_sf_express(row, src):
    # JobSearchById 逐岗 HTML 页：在招→<title>顺丰人才招聘系统-社会招聘-{岗位名}；
    # 撤岗/不存在→<title>顺丰人才招聘系统-404（live 验证：30 oldest 全 404 标题 / 8 recent 全社招标题）。liveness-only。
    r = httpx.get(row["jd_url"], headers={**UA, "Accept": "text/html"}, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    m = re.search(r"<title>(.*?)</title>", r.text, re.S)
    title = (m.group(1).strip() if m else "")
    if title == "顺丰人才招聘系统-404":
        raise JobClosedError(f"sf_express closed (404 page): {row['jd_url']}")
    return ""


def _detail_tencent(row, src):
    # postId = jd_url 查询参数；detail = 公开 ByPostId JSON。撤岗→HTTP500 {Code:500,Data:"E1005"}（3 真实撤岗）；
    # 在招→{Code:200,Data:{Responsibility/Requirement=正文}}。⚠️ E1003=bogus 入参错，不判死。
    pid = (parse_qs(urlparse(row["jd_url"]).query).get("postId") or [""])[0]
    if not pid:
        return ""
    r = httpx.get("https://careers.tencent.com/tencentcareer/api/post/ByPostId",
                  params={"postId": pid}, headers={**UA, "Referer": "https://careers.tencent.com/"}, timeout=TIMEOUT)
    _raise_if_gone(r)  # tencent 撤岗实际走 500+E1005（在下方判），此处仅继承 404/410 通用约定
    try:
        j = r.json() or {}
    except Exception:
        return ""  # 非 JSON（真 5xx/限流）→ miss，不判死
    if str(j.get("Code")) == "500" and str(j.get("Data")) == "E1005":
        raise JobClosedError(f"tencent postId={pid} closed (E1005)")
    data = j.get("Data")
    if str(j.get("Code")) == "200" and isinstance(data, dict):
        return " ".join(x for x in (data.get("Responsibility"), data.get("Requirement")) if x)
    return ""


def _detail_vivo(row, src):
    # job_id = jd_url 查询参数 _irjid；detail POST {job_id}；撤岗→{code:105002,"官网职位未发布"}（13/40 真实撤岗）；
    # 在招→{code:0,data:{job_desc=正文}}。⚠️ code=100000=服务器错(bogus 入参)，不判死。
    jid = (parse_qs(urlparse(row["jd_url"]).query).get("_irjid") or [""])[0]
    if not jid:
        return ""
    headers = {**UA, "Referer": "https://hr.vivo.com/jobs",
               "Origin": "https://hr.vivo.com", "Content-Type": "application/json"}
    r = httpx.post("https://hr.vivo.com/api/social/webSite/portal/job/detail",
                   json={"job_id": jid}, headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    if str(j.get("code")) == "105002":
        raise JobClosedError(f"vivo job_id={jid} closed: {j.get('message') or 'code=105002'}")
    if str(j.get("code")) == "0":
        return (j.get("data") or {}).get("job_desc") or ""
    return ""


# adapter_name -> fetcher（httpx 类，P1）
def _main_text(html_text):
    """取详情页 <main> 的文本（SSR 页面的 JD 正文容器）。上层 clean_summary 再去标签/截断。"""
    node = HTMLParser(html_text).css_first("main")
    return node.text() if node else ""


def _detail_siemens(row, src):
    # Siemens 自建 ATS（jobs.siemens.com/en_US/externaljobs/JobDetail/{id}）：详情页是 SSR，
    # JD 正文在 <main> 里（live 验证：7.6k 字符含完整 JD；<article> 只有 324 字元信息，别用）。
    # httpx 直抓、零浏览器。撤岗 → 404/410（_raise_if_gone 统一约定）。
    # 补这个函数前 Siemens 338 个在招岗 100% 是无正文薄卡（adapter 压根不在 ENRICH_REGISTRY 里）。
    r = httpx.get(row["jd_url"], headers=UA, timeout=TIMEOUT, follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    return _main_text(r.text)


def _detail_google(row, src):
    # Google careers（google.com/about/careers/applications/jobs/results/{id}-{slug}）：详情页 SSR，
    # JD 正文在 <main>（live 验证 5-6k 字符）。httpx 直抓、零浏览器。
    # ⚠️ 撤岗是**软 404**：HTTP 仍 200，但 <main> 只剩 "Job not found. This job may have been taken
    # down."（live 抽样 5 个库内 active 岗，2 个已是这个状态）→ 必须按文案判死，否则死岗永不下架。
    r = httpx.get(row["jd_url"], headers=UA, timeout=TIMEOUT, follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    text = _main_text(r.text)
    flat = re.sub(r"\s+", " ", text or "").strip()
    if "Job not found" in flat or "taken down" in flat:
        raise JobClosedError(f"google job closed (soft 404): {row['jd_url']}")
    return text


ENRICH_REGISTRY = {
    "workday": _detail_workday,
    "oracle": _detail_oracle,
    "eightfold": _detail_eightfold,
    "smartrecruiters": _detail_smartrecruiters,
    "greenhouse": _detail_greenhouse,
    "lever": _detail_lever,
    "hotjob": _detail_hotjob,
    "wt": _detail_wt,
    # C 类大厂自建门户（2026-06-25，live 验证关闭信号）：
    "amazon": _detail_amazon,
    "apple": _detail_apple,
    "meituan": _detail_meituan,
    "microsoft": _detail_microsoft,   # liveness + 正文：jobs.careers.microsoft.com 前端是 Akamai+SPA 拿不到，
                                      # 但 apply.careers.microsoft.com/careers/job/{positionId}（pcsx search 命中里的
                                      # 数字长 id，非 displayJobId）是 SSR + ld+json JobPosting（2026-07-16 live 验证 200）。
    "siemens": _detail_siemens,
    "google": _detail_google,
    "sf_express": _detail_sf_express,
    "tencent": _detail_tencent,
    "vivo": _detail_vivo,
}

# 需渲染、低并发：SPA 壳详情页无 httpx 关闭信号，走 audit_dead_links 浏览器审计兜底。
# bilibili（detail 需 ajSessionId cookie）、phenom（jd_url→SPA 壳，careers.amd.com/pepsicojobs.com）同类。
_BROWSER_ADAPTERS = {"beisen", "moka", "feishu"}


def detail_class(adapter):
    """'httpx' | 'browser' | None（不支持富化的 adapter）。"""
    if adapter in ENRICH_REGISTRY:
        return "httpx"
    if adapter in _BROWSER_ADAPTERS:
        return "browser"
    return None


def enrich_one(adapter, row, src):
    """按 adapter 派发富化，返回 summary 文本或空串。异常上抛由调用方计死信。"""
    fetcher = ENRICH_REGISTRY.get(adapter)
    return fetcher(row, src) if fetcher else ""
