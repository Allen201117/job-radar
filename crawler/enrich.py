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
from datetime import date
from urllib.parse import urlparse, parse_qs

import httpx
from selectolax.parser import HTMLParser

from adapters.bankcomm import BankcommAdapter
from adapters.ccb import CcbAdapter, _repair_json as _ccb_repair_json
from adapters.cmcc import CmccAdapter, _sign_header as _cmcc_sign_header
from adapters.cn_portal_tls import make_transport
from adapters.icbc import IcbcAdapter
from adapters.spdb import SpdbAdapter

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      "Accept": "application/json"}
TIMEOUT = 25


class JobClosedError(Exception):
    """源站明确告知该岗位已撤下/招聘已关闭（如 hotjob detail 返回 state=1017）。

    与「无正文」(fetcher 返回 "") 区分：这类岗永远补不到 summary 且应置 status='expired'，
    不是死信。**只在明确关闭信号时抛**——网络错误/限流仍走普通异常（调用方计 miss 重试），不得 expired。
    """


class DetailUnknownError(RuntimeError):
    """detail 探测没拿到可判读的响应（403 / 429 / 5xx / 非 JSON / 半截页）。

    ⚠️ 它既不是「在招」也不是「撤岗」（2026-09-08 加，修 F3）。
    在此之前，liveness-only 的探活器对非 404/410 的任何状态码都 `return ""`，
    而空串在调用方那里同时表示「已确认在招、只是没有正文」和「这次没探到」——
    于是 enrich_backlog 对一个 403/限流的响应也照样盖上 enrich_checked_at，
    产品侧的「最近确认仍在招」和治理看板的「已核验率」双双被灌水：
    我们把「没探到」写成了「刚确认过」。
    抛出它 → 调用方的 `except Exception: fetch_err = True` 分支 → 记 miss 重试，不盖戳、不改状态。"""


def _raise_if_unknown(r):
    """非 2xx（且已排除 404/410 撤岗）一律判 unknown。**先调 _raise_if_gone 再调它。**"""
    if r.status_code >= 300:
        raise DetailUnknownError(f"detail unknown (HTTP {r.status_code})")


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
    _raise_if_gone(r)      # 404/410 = 岗位已撤
    _raise_if_unknown(r)   # 403/429/5xx = 没探到，不是「确认在招」（Akamai 拦截在这条链上很常见）
    return ""


def _detail_apple(row, src):
    # jobNumber = jd_url 路径 /details/{jobNumber}/；detail = 公开 jobDetails JSON。
    # 撤岗→404 {"error":"jobsite.general.serviceError"}（live 验证 4/30 真实撤岗岗 = 404）；在招→200 {res}。
    m = re.search(r"/details/([^/?]+)", urlparse(row["jd_url"]).path)
    if not m:
        return ""
    r = httpx.get(f"https://jobs.apple.com/api/v1/jobDetails/{m.group(1)}",
                  headers={**UA, "Referer": "https://jobs.apple.com/"}, timeout=TIMEOUT)
    _raise_if_gone(r)      # 404 = 岗位已撤
    _raise_if_unknown(r)   # 其余非 2xx = 没探到，不是「确认在招」
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


def _detail_successfactors(row, src):
    # SF CSB 详情页是 SSR；多数租户正文在 class 含 jobdescription 的 span（live 验证 Ferrari/Bayer/Adidas；
    # ZF 类租户详情不内嵌正文 → 返空走 miss）。⚠️ 该 HTML 会让 selectolax 解析成空 DOM → 必须正则抽取。
    # 撤岗/不存在 → 302 跳 /errorpage/?errortype=…（live 验证 bogus id），不是 404 → 按最终 URL 判死。
    r = httpx.get(row["jd_url"], headers={**UA, "Accept": "text/html"}, timeout=TIMEOUT, follow_redirects=True)
    _raise_if_gone(r)
    if "/errorpage" in str(r.url).lower():
        raise JobClosedError(f"successfactors closed (errorpage): {row['jd_url']}")
    if r.status_code >= 300:
        return ""
    m = re.search(
        r'<span[^>]*class="[^"]*jobdescription[^"]*"[^>]*>(.*?)</span>\s*(?:</div|<div|<footer|<span[^>]*class="[^"]*job)',
        r.text, re.S | re.I)
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


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
        # 非 JSON（真 5xx/限流）→ unknown：既不判死，也不许当成「确认在招」盖戳。
        raise DetailUnknownError("tencent detail non-JSON response")
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


def _detail_avature(row, src):
    # Avature SearchJobs SSR 详情页（各租户 JobDetail 路径不同）：正文在 <main> 里。
    # Siemens 使用 /externaljobs/JobDetail/{id}；其他租户仍直接 GET 各自卡片给出的 jd_url。
    # JD 正文在 <main> 里（live 验证：7.6k 字符含完整 JD；<article> 只有 324 字元信息，别用）。
    # httpx 直抓、零浏览器。
    # 补这个函数前 Siemens 338 个在招岗 100% 是无正文薄卡（adapter 压根不在 ENRICH_REGISTRY 里）。
    # ⚠️ 撤岗**不是 404**，是 **403 + 错误页**（2026-07-28 live 实测 JobDetail/510194 → HTTP 403，
    # <main> 只剩 "An error has occurred Page not found Go to open jobs"）。
    # _raise_if_gone 只认 404/410 → 旧实现把 403 当普通失败吞掉返回 ""，岗位永远留在 active：
    # 实测库里 484 个 Siemens active 岗**全部**在 7 天内被探活过、却一个都没下架过。
    # 故按「403 且正文命中错误页文案」判死（照 _detail_google 的软 404 范式）。
    # 必须同时看状态码和文案——单凭 403 可能是 WAF 临时拦截，误判会误杀活岗。
    r = httpx.get(row["jd_url"], headers=UA, timeout=TIMEOUT, follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code == 403:
        flat = re.sub(r"\s+", " ", _main_text(r.text) or "").strip().lower()
        if "page not found" in flat or "an error has occurred" in flat:
            raise JobClosedError(f"avature job closed (HTTP 403 error page): {row['jd_url']}")
    if r.status_code >= 300:
        return ""
    return _main_text(r.text)


# 保留旧私有符号，既有 Siemens 测试/第三方脚本仍可调用；新接线统一使用通用函数。
_detail_siemens = _detail_avature


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


_HUAWEI_DETAIL_API = ("https://career.huawei.com/reccampportal/services/portal/portalpub"
                      "/getJobDetail/newHr")
# 不存在的 jobId 也返 HTTP 200 + 109 字段骨架，只是几乎全空（实测 99999999 → 5 个字段有值）；
# 在招岗实测 ~32 个字段有值。取 8 作阈值：留足余量，宁可漏判也不错杀。
_HUAWEI_EMPTY_FIELD_CAP = 8


def _huawei_query(jd_url, key, default=""):
    m = re.search(rf"[?&]{key}=([^&]+)", jd_url or "")
    return m.group(1) if m else default


def _detail_huawei(row, src):
    """华为 career.huawei.com：逐岗公开 JSON 详情接口，零浏览器、零鉴权。
    GET …/portalpub/getJobDetail/newHr?jobId={id}&dataSource={ds}
    （2026-07-29 用无头浏览器抓详情页 XHR 抓到的真实端点，httpx 直连可用。）

    ⚠️ 为什么必须逐岗判、不能靠列表缺席：列表接口 getJob/newHr 返回的是**筛选过的子集**
    （实测只返 13 条），而库里 460 个 active 逐个查下来**全部在招** → 列表缺席 ≠ 撤岗。
    详见 adapters/huawei.py 里 supports_absence_liveness 的立碑注释。

    撤岗信号：接口对任何 jobId 都返 200 + 109 字段骨架，区别在**有没有填内容**——在招岗
    ~32 个字段有值且 jobname 非空；不存在的 jobId 只有 5 个字段有值、jobname 为空。
    故判死要求「jobname 为空」**且**「有值字段数 ≤ 阈值」同时成立：只看 jobname 空的话，
    接口某次返半截数据就会误杀在招岗——本源刚因误判差点被清库，这里宁可漏判不可错杀。
    """
    r = httpx.get(_HUAWEI_DETAIL_API,
                  params={"jobId": _huawei_query(row["jd_url"], "jobId"),
                          "dataSource": _huawei_query(row["jd_url"], "dataSource", "1")},
                  headers=UA, timeout=TIMEOUT, follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    try:
        payload = r.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    name = (payload.get("jobname") or payload.get("nameCn") or "").strip()
    filled = sum(1 for v in payload.values() if v not in (None, "", [], {}))
    if not name and filled <= _HUAWEI_EMPTY_FIELD_CAP:
        raise JobClosedError(f"huawei job closed (detail payload empty): {row['jd_url']}")
    return (payload.get("mainBusiness") or "").strip()


# --- 探活盲区六家（2026-08-28，审阅 P1-3：11 adapter 12,775 岗三层探活零覆盖）---
# 每家的判死信号都做过真伪 id live 对拍（真 id ≥2 个返回正常数据、伪 id ≥2 个返回可区分的
# 「不存在」信号），证据见各函数注释。红线不变：只认正面撤岗证据，含糊信号一律不判死。


def _detail_jd(row, src):
    # jd_url = zhaopin.jd.com/web/job-info-detail?requementId={id}：JSP SSR 页面，零鉴权。
    # 在招 → HTTP 200，正文内嵌 <h1 class="post-name"> + div.main-content 下「岗位描述/任职要求」
    # 成对 div.part（live 验证 3 真 id）。不存在/已撤 → HTTP 302 跳首页、body 空（live 验证 4 伪 id）。
    # httpx.get 默认不跟随重定向 → 302 本身就是判死信号。
    r = httpx.get(row["jd_url"], headers={**UA, "Accept": "text/html"}, timeout=TIMEOUT)
    if r.status_code in (301, 302, 303, 307, 308):
        raise JobClosedError(f"jd closed (redirect {r.status_code}): {row['jd_url']}")
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    tree = HTMLParser(r.text)
    if not tree.css_first("h1.post-name"):
        return ""  # 页面结构变化/未命中标题，保守不判死
    parts = [n.text(separator=" ", strip=True) for n in tree.css("div.main-content div.part")]
    return "\n".join(x for x in parts if x)


_ANT_BOARD_BY_PATH = {"off-campus-position": "social", "campus-position": "campus"}


def _detail_antgroup(row, src):
    # talent.antgroup.com 是 UMI SPA；公开 JSON 接口 = POST hrcareersweb.antgroup.com/api/
    # {social|campus}/position/detail，body={"id":positionId}，零鉴权（live 验证 3 真 id 200+38 字段）。
    # 不存在/撤岗 → 200 + {"success":true,"content":null}（live 验证 4 伪 id 皆此形状）。
    # ⚠️ {"success":false,...} 是含糊系统异常（live 验证 id="1" 返 system_error），不判死。
    p = urlparse(row["jd_url"])
    board = _ANT_BOARD_BY_PATH.get((p.path or "").strip("/"))
    pid = (parse_qs(p.query).get("positionId") or [""])[0]
    if not (board and pid):
        return ""
    headers = {**UA, "Content-Type": "application/json",
               "Referer": "https://talent.antgroup.com/", "Origin": "https://talent.antgroup.com"}
    r = httpx.post(f"https://hrcareersweb.antgroup.com/api/{board}/position/detail",
                   json={"id": pid}, headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    try:
        j = r.json() or {}
    except ValueError:
        return ""
    if not j.get("success"):
        return ""
    content = j.get("content")
    if content is None:
        raise JobClosedError(f"antgroup positionId={pid} closed (content=null): {row['jd_url']}")
    if not isinstance(content, dict):
        return ""
    return "\n".join(x for x in (content.get("description"), content.get("requirement")) if x)


def _detail_haier(row, src):
    # maker.haier.net/client/job/detail.html?id={id}：SSR，零鉴权。在招 → 200 + 26-27KB、
    # 正文在 4 个 div.cb-wordwrap（live 验证 3 真 id）。不存在/撤岗 → 200 但 ~6.5KB、出现
    # 专用错误容器 <div class="cb-page404">（「参数错误」+3 秒跳转，live 验证 3 伪 id）。
    # 按 cb-page404 判死而非「cb-wordwrap 为空」——防页面改版误杀。
    r = httpx.get(row["jd_url"], headers={**UA, "Accept": "text/html"}, timeout=TIMEOUT,
                  follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    tree = HTMLParser(r.text)
    if tree.css_first("div.cb-page404"):
        raise JobClosedError(f"haier job closed (cb-page404): {row['jd_url']}")
    parts = [n.text(separator=" ", strip=True) for n in tree.css("div.cb-wordwrap")]
    return "\n".join(x for x in parts if x)


def _detail_ashby(row, src):
    # jobs.ashbyhq.com/{org}/{uuid}：SSR，真实在招岗注入 <title>{岗位} @ {公司}</title> +
    # application/ld+json JobPosting（含 description 正文），live 验证 3 真 id。
    # 撤岗/不存在（含整个 org 不存在）→ 统一通用壳：<title>Jobs</title>、无 ld+json、HTTP 恒 200
    # （live 验证 4 种伪造完全一致）→ 只能按内容判死，且要求「title==Jobs 且无 ld+json」双条件。
    if not re.match(r"^/[^/]+/[0-9a-fA-F-]{36}/?$", urlparse(row["jd_url"]).path):
        return ""
    r = httpx.get(row["jd_url"], headers={**UA, "Accept": "text/html"}, timeout=TIMEOUT,
                  follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    title_m = re.search(r"<title>(.*?)</title>", r.text, re.S)
    title = html_lib.unescape(title_m.group(1).strip()) if title_m else ""
    ld_m = re.search(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", r.text, re.S)
    if title == "Jobs" and not ld_m:
        raise JobClosedError(f"ashby posting gone (generic shell): {row['jd_url']}")
    if not ld_m:
        return ""
    try:
        data = json.loads(ld_m.group(1))
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict) or data.get("@type") != "JobPosting":
        return ""
    desc = html_lib.unescape(str(data.get("description") or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", desc)).strip()


_MIHOYO_INFO_API = "https://ats.openout.mihoyo.com/ats-portal/v1/job/info"


def _detail_mihoyo(row, src):
    # jd_url 是 hash 路由 SPA（#/position/{id} 或 #/campus/position/{id}，id 在 fragment）；
    # detail = adapter 在用的公开 v1/job/info（POST {id, channelDetailIds:[1]}），社招/校招同接口。
    # live 验证：真 id（社招 9407/9406/9404、校招 9100）code=0+完整 data；伪数字 id → 200 +
    # code=1080001052「当前职位不存在」。⚠️ 只认 1080001052：code=2080001003 是入参格式错
    # （非数字 id 才触发），拿它判死会把我方解析 bug 错杀成撤岗。
    m = re.search(r"/position/(\d+)", urlparse(row["jd_url"]).fragment)
    if not m:
        return ""
    headers = {**UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
               "Referer": "https://jobs.mihoyo.com/", "Origin": "https://jobs.mihoyo.com"}
    r = httpx.post(_MIHOYO_INFO_API, json={"id": m.group(1), "channelDetailIds": [1]},
                   headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    if str(j.get("code")) == "1080001052":
        raise JobClosedError(f"mihoyo job id={m.group(1)} closed: {j.get('message')}")
    d = j.get("data")
    if not isinstance(d, dict):
        return ""
    return "\n".join(x for x in (d.get("description"), d.get("jobRequire")) if x)


def _detail_tencent_music(row, src):
    # join.tencentmusic.com：社招 POST /api/job/info、校招 POST /api/uc-job/info，body={"id":id}，
    # board 取 jd_url 路径首段。live 验证：真 id（社招 15055/15057、校招 15056）code="200"(字符串)
    # +完整 data；伪 id（数字/非数字、两接口）→ 200 + code=404(数字) + msg="该岗位不存在！"。
    # 真伪 code 连类型都不同，用 str() 统一比较防类型漂移。
    p = urlparse(row["jd_url"])
    parts = [x for x in p.path.split("/") if x]
    if not parts:
        return ""
    board = parts[0]
    jid = (parse_qs(p.query).get("id") or [""])[0]
    if not jid:
        return ""
    api = ("https://join.tencentmusic.com/api/uc-job/info" if board == "campus"
           else "https://join.tencentmusic.com/api/job/info")
    headers = {**UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
               "Referer": f"https://join.tencentmusic.com/{board}", "Origin": "https://join.tencentmusic.com"}
    r = httpx.post(api, json={"id": jid}, headers=headers, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    if str(j.get("code")) == "404":
        raise JobClosedError(f"tencent_music job id={jid} closed: {j.get('msg')}")
    d = j.get("data")
    if not isinstance(d, dict):
        return ""
    return "\n".join(x for x in (d.get("duty"), d.get("requirement")) if x)


def _detail_iguopin(row, src):
    # jd_url = www.iguopin.com/job/detail?id={job_id}；detail = 抓取阶段已在用的公开 info API。
    # 撤岗/过期 → 200 + {"code":200,"data":{"status":2,...}}（live 验证 40/40 个 deadline 已过的
    # 真实岗全部复现，数据仍完整、仅 status 1→2）；不存在 → {"code":2001,"msg":"数据不存在。"}
    # （live 验证伪 id + 缺参数均命中）。未知 code 一律不判死。
    job_id = (parse_qs(urlparse(row["jd_url"]).query).get("id") or [""])[0]
    if not job_id:
        return ""
    r = httpx.get("https://gp-api.iguopin.com/api/jobs/v1/info", params={"id": job_id},
                  headers={**UA, "Referer": "https://www.iguopin.com/"}, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    code = j.get("code")
    if code == 2001:
        raise JobClosedError(f"iguopin id={job_id} not found: {j.get('msg')}")
    if code != 200:
        return ""
    data = j.get("data") or {}
    if str(data.get("status")) == "2":
        raise JobClosedError(f"iguopin id={job_id} closed: status=2")
    return data.get("contents") or ""


def _detail_pinduoduo(row, src):
    # jd_url = careers.pddglobalhr.com/campus/grad/detail?positionId={uuid}；detail = 独立公开
    # POST 接口。撤岗/不存在 → 200 + {"success":true,"result":{"id":null,"normal":false,...}}
    # （live 验证 4/4 真实过期旧岗 + 2 种伪造 id 同一签名）；在招 → result.id 与请求一致。
    # success=false 是入参类错误（如「职位id不为空」），不判死。
    job_id = (parse_qs(urlparse(row["jd_url"]).query).get("positionId") or [""])[0]
    if not job_id:
        return ""
    r = httpx.post("https://careers.pddglobalhr.com/api/careers/api/recruit/position/detail",
                   json={"id": job_id},
                   headers={**UA, "Content-Type": "application/json",
                            "Referer": "https://careers.pddglobalhr.com/campus/grad",
                            "Origin": "https://careers.pddglobalhr.com"}, timeout=TIMEOUT)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    if not j.get("success"):
        return ""
    result = j.get("result") or {}
    if str(result.get("id") or "") != job_id:
        raise JobClosedError(f"pinduoduo positionId={job_id} closed (id mismatch/null)")
    duty = result.get("jobDuty") or ""
    req = result.get("serveRequirement") or result.get("serviceRequirement") or ""
    return (duty + ("\n\n【任职要求】\n" + req if req else "")).strip()


def _detail_chnenergy(row, src):
    # jd_url = zhaopin.chnenergy.com.cn/annc/showgw?id={uuid}（showgw=岗位，showgg=公告，别混）。
    # 2026-09-05 live 标定：在招 → 200 + ~60KB 页面且含「招聘岗位：」；不存在/撤岗 → 200 + 恰好
    # 738 字节错误壳「查看岗位信息发生错误，请重试或者联系管理员。」（伪造同前缀 uuid / 随机 uuid /
    # 非 uuid 三种输入签名完全一致）。判死要求**错误壳出现且「招聘岗位」缺席**两个条件同时成立，
    # 半截页面一律不判死（宁可漏判不可错杀）。
    job_id = (parse_qs(urlparse(row["jd_url"]).query).get("id") or [""])[0]
    if not job_id:
        return ""
    r = httpx.get("https://zhaopin.chnenergy.com.cn/annc/showgw",
                  params={"id": job_id},
                  headers={**UA, "Accept": "text/html,application/xhtml+xml,*/*"},
                  timeout=TIMEOUT, follow_redirects=True)
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    html = r.text
    if "查看岗位信息发生错误" in html and "招聘岗位" not in html:
        raise JobClosedError(f"chnenergy id={job_id} closed (error shell)")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", HTMLParser(text).text()).strip()
    m = re.search(r"岗位职责(.*)", text, re.S)
    # 页面尾部固定挂着「国家能源投资集团有限责任公司」版权行，截掉，别当正文存进去。
    return (m.group(1) if m else "").split("国家能源投资集团有限责任公司")[0].strip()


# --- 国有大行 + 中国移动自建门户（2026-09-06 真伪 id live 对拍）---
# 接入前这五家 9,292 个 active 岗零撤岗路径（连同农行 2,418 共 11,710，2026-09-06 实测）。
# 五家共用 adapters/cn_portal_tls.make_transport()：强制 IPv4 + 允许 TLS 传统重协商。
# ⚠️ **不走它的话本机全绿、上 GitHub runner 全炸**（建行/交行/移动 UNSAFE_LEGACY_RENEGOTIATION_DISABLED、
# 工行 Errno 101）——这两条毛病本机永远测不出来，见 adapters/cn_portal_tls.py 的立碑。
# 判死一律双条件、宁可漏判不可错杀：半截数据 / 超时 / 空 body / 通用系统异常一律返 ""，不判死。


def _cn_portal_client(headers, timeout=TIMEOUT):
    """五家自建门户共用的 httpx.Client（IPv4 + 传统重协商，证书校验保持开启）。
    单独抽出来是为了让单测能整体 patch 掉网络层（这五家都不是 httpx.get 一发了事的形状：
    建行要热身会话、交行要两跳确认、移动每次要重新签名）。"""
    return httpx.Client(timeout=timeout, follow_redirects=True, headers=headers,
                        transport=make_transport())


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_DATE10 = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_past_date(value, today=None):
    """value 的前 10 位是不是一个「已经过去的日期」。非日期一律 False（不构成判死依据）。
    ⚠️ 用 UTC 的今天与北京时间的站点字段比：UTC 落后北京 8 小时 → 只会把刚过期的岗多留几小时，
    偏向漏判，与各 adapter 入库时的 `date.today()` 口径一致。"""
    head = str(value or "").strip()[:10]
    if not _DATE10.match(head):
        return False
    return head < (today or date.today().isoformat())


def _loads_object(response):
    """把响应解析成 dict；解不出对象一律返回 None（调用方当「没查成」，绝不判死）。

    容忍**双层编码**：有的门户把 JSON 再 json.dumps 一次当字符串发（中国移动 viewJob.do
    在带 Accept: application/json 时就这样），`r.json()` 会拿到 str 而不是 dict。"""
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    return payload if isinstance(payload, dict) else None


_SPDB_DETAIL_URL = "https://job.spdb.com.cn/jobDetail"
# 不存在的 jobId 返回的固定错误壳（936 字节，`class="my404"` + 「500 您访问的页面出错了！」）。
_SPDB_GONE_MARKERS = ('class="my404"', "您访问的页面出错了")


def _detail_spdb(row, src):
    """浦发 job.spdb.com.cn：详情页是 SSR HTML，零鉴权（2026-09-06 实测连 Referer 都不用带，
    与列表接口不同——列表少了 Referer 会 500）。

    撤岗信号：不存在的 jobId → HTTP 200 + 936 字节固定错误壳（三种伪 id：越界数字 / 乱码 /
    空值，返回的页面逐字节相同）；在招岗 → 70~80KB 完整页面。判死要求**错误壳出现**
    且**抽不出正文**两个条件同时成立，半截页面一律不判死。

    ⚠️ **诚实边界：浦发的详情页不随撤岗消失，所以这里抓不到「岗位已关闭」。**
    2026-09-06 实测：一个当天刚掉出列表、截止日已过的岗（jobId=10023082）仍渲染出完整 JD；
    2020 年发布的老岗（10005198）也照样在。本探活只能抓到「id 彻底不存在」这一种。
    浦发真正的下架信号只有列表缺席看得见，而 list-absence 撤岗按 CLAUDE.md
    「列表里没有 ≠ 已撤岗」那条碑需要单独论证全集性，本次刻意没开。
    """
    job_id = (parse_qs(urlparse(row["jd_url"]).query).get("jobId") or [""])[0]
    if not job_id:
        return ""
    with _cn_portal_client({**UA, "Accept": "text/html,application/xhtml+xml,*/*"}) as client:
        r = client.get(_SPDB_DETAIL_URL, params={"jobId": job_id, "type": _spdb_type_code(row)})
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    # 正文夹在「返回列表」导航与页脚版权之间——直接复用 adapter 的锚点，别抄第二份。
    body = SpdbAdapter._detail_body(r.text)
    if not body and all(m in r.text for m in _SPDB_GONE_MARKERS):
        raise JobClosedError(f"spdb jobId={job_id} not found (my404 shell)")
    return body


def _spdb_type_code(row):
    """详情 URL 的 type：1=社招 / 2=校招，用错打不开。jd_url 里就带着，直接沿用。"""
    q = parse_qs(urlparse(row["jd_url"]).query)
    return (q.get("type") or ["1"])[0]


_ICBC_DETAIL_API = "https://job.icbc.com.cn/icbc/trmo/post/qryPostById"
_ICBC_GONE_MSG = "岗位已失效"
_ICBC_APPLY_CLOSED = 2


def _icbc_post_id(jd_url):
    # jd_url = .../pc/index.html#/main/{school|social}/postDetail/{postId}（hash 路由，不在 query 里）
    m = re.search(r"/postDetail/([A-Za-z0-9]+)", jd_url or "")
    return m.group(1) if m else ""


def _icbc_apply_closed(data, today=None):
    """报名已截止：站点自己的 applyState=2 **且** enterEndTime 确实已过。

    双条件是刻意的——只认 applyState 的话，接口某次返半截数据（字段缺省成 2）就会误杀在招岗。
    这条与 adapters/icbc.py 入库时的 `_is_open`（按 enterEndTime 剔已截止岗）是同一口径：
    列表本来就会照列已截止的岗，入库时丢掉、存量也该跟着下架，否则只进不出。"""
    if _int_or_none(data.get("applyState")) != _ICBC_APPLY_CLOSED:
        return False
    return _is_past_date(data.get("enterEndTime"), today)


def _detail_icbc(row, src):
    """工行 job.icbc.com.cn：POST qryPostById，公开零鉴权（2026-09-06 真伪 id live 对拍）。

    两种撤岗信号，各自双条件：
      1. 岗位不存在 → `retCode="9"` + `retMsg="岗位已失效"`（越界 id / 全零 id / 短 id 三种
         伪值签名一致）。⚠️ **不能只看 retCode=9**：空 postId 同样返 retCode=9，但 retMsg 是
         「请求参数错误」——那是我们自己传错了，不是对方撤岗，所以必须连 retMsg 一起认。
      2. 报名已截止 → `retCode="0"` + `applyState=2` + enterEndTime 已过（见 _icbc_apply_closed；
         live 实测在招岗 applyState=1，30 个截止日已过的岗全部 applyState=2）。
    在招岗返 25 个字段全有值，正文在 postDepict（base64→urlencode→HTML 三层包）。"""
    post_id = _icbc_post_id(row["jd_url"])
    if not post_id:
        return ""
    headers = {**UA, "Content-Type": "application/json;charset=UTF-8",
               "Referer": IcbcAdapter.REFERER}
    with _cn_portal_client(headers) as client:
        r = client.post(_ICBC_DETAIL_API,
                        json={"public": {"call_app": "F-TRM"}, "private": {"postId": post_id}})
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    payload = _loads_object(r)
    if payload is None:
        return ""
    ret_code = str(payload.get("retCode") or "")
    ret_msg = str(payload.get("retMsg") or "")
    if ret_code == "9":
        if _ICBC_GONE_MSG in ret_msg:
            raise JobClosedError(f"icbc postId={post_id} closed: {ret_msg}")
        return ""      # 「请求参数错误」也是 retCode=9 —— 我们传错了，不是对方撤岗
    if ret_code != "0":
        return ""
    data = payload.get("data")
    if not isinstance(data, dict) or not data:
        return ""
    if _icbc_apply_closed(data):
        raise JobClosedError(
            f"icbc postId={post_id} closed: applyState=2 enterEndTime={data.get('enterEndTime')}")
    return IcbcAdapter._decode_depict(data.get("postDepict"))


_CCB_BASE = "https://job3.ccb.com/tran/WCCMainPlatV5"
_CCB_COMMON = {"CCB_IBSVersion": "V5", "isAjaxRequest": "true", "SERVLET_NAME": "WCCMainPlatV5"}
_CCB_CLOSED_STATUS = "2"
# 「这条详情真的有内容」的判据：这四个业务字段全空 = 空骨架（伪 id 的签名）。
_CCB_CONTENT_FIELDS = ("planPostName", "planStatus", "planName", "postDate")


def _ccb_params(jd_url):
    q = parse_qs(urlparse(jd_url or "").query)
    return {k: (q.get(k) or [""])[0]
            for k in ("planId", "planPost", "planType", "orgId", "secondOrgId")}


def _ccb_empty_skeleton(detail):
    """四个业务字段全空 = 这条岗位不存在（伪 planId / 伪 planPost / 伪 orgId / 全伪，
    2026-09-06 live 四种伪值返回的都是同一个 533 字节空骨架）。
    只要有任意一个字段有值就不判死——半截数据宁可漏判。"""
    return all(not str(detail.get(k) or "").strip() for k in _CCB_CONTENT_FIELDS)


def _detail_ccb(row, src):
    """建行 job3.ccb.com：GET NHR107，公开零鉴权，但**必须先热身会话**。

    ⚠️ 热身（TXCODE=100119）不是可选项：2026-09-06 实测全新 client 直接打 NHR107 会拿到
    `SUCCESS=false` +「暂时未能处理您的请求，请重新登录。」——**这既不是登录墙也不是撤岗**，
    所以 SUCCESS!=true 一律返 ""、绝不判死（否则冷会话会把整个源清空）。
    详情接口的 orgId 传的是**二级机构 id**（与 adapters/ccb.py 同口径，前端就是这么传的）。

    两种撤岗信号：
      1. 报名结束 → `planStatus="2"`（站点自己的状态位，与 adapters/ccb.py 入库时丢弃
         planStatus=2 是同一口径；live 用列表里 19 条已结束的岗验过，详情逐条复现）。
      2. 岗位不存在 → SUCCESS=true 但四个业务字段全空的 533 字节空骨架（见 _ccb_empty_skeleton）。

    ⚠️ UA 必须用 adapters/ccb.py 那个浏览器 UA：本项目默认 Bot UA 会换来 HTTP 200 + 零字节
    body（不是 403），_repair_json 会抛 RuntimeError → 这里当作「没查成」返 ""，不判死。"""
    p = _ccb_params(row["jd_url"])
    if not (p["planId"] and p["planPost"] and p["secondOrgId"]):
        return ""
    headers = {"User-Agent": CcbAdapter.user_agent, "Accept": "application/json,text/plain,*/*",
               "Referer": "https://job3.ccb.com/cn/job/job_list.html"}
    with _cn_portal_client(headers) as client:
        client.get(_CCB_BASE, params={**_CCB_COMMON, "TXCODE": "100119"})   # 热身，见 docstring
        r = client.get(_CCB_BASE, params={
            **_CCB_COMMON, "TXCODE": "NHR107", "planId": p["planId"], "planPost": p["planPost"],
            "planType": p["planType"], "orgId": p["secondOrgId"]})
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    try:
        detail = _ccb_repair_json(r.text)
    except (ValueError, RuntimeError):
        return ""   # 空 body / 修不好的 JSON = 没查成，不是撤岗
    if str(detail.get("SUCCESS")) != "true":
        return ""   # 冷会话「请重新登录」/「要素不完整」都长这样
    if str(detail.get("planStatus") or "").strip() == _CCB_CLOSED_STATUS:
        raise JobClosedError(f"ccb planPost={p['planPost']} closed (planStatus=2)")
    if _ccb_empty_skeleton(detail):
        raise JobClosedError(f"ccb planPost={p['planPost']} not found (empty skeleton)")
    return CcbAdapter._summary_of({"_detail": detail}) or ""


_BANKCOMM_API = "https://job.bankcomm.com/api/GTMS.GTMS-PORTAL.V-1.0/"
# jd_url 的 hash 前缀 → 列表接口的 engageType（3=社会招聘 / 1=校园招聘）。
_BANKCOMM_ENGAGE = {"social": 3, "school": 1}


def _bankcomm_target(jd_url):
    """从 `https://job.bankcomm.com/#/{section}/recruitmentInfo/?positionId=N` 取 (id, section)。
    ⚠️ id 与 section 都在 **hash 片段**里，urlparse().query 是空的，必须解 fragment。"""
    fragment = urlparse(jd_url or "").fragment
    position_id = (parse_qs(urlparse(fragment).query).get("positionId") or [""])[0]
    section = next((x for x in (fragment or "").split("/") if x), "")
    return position_id.strip(), section


def _bankcomm_call(client, op, params):
    """照抄前端 jumpRequest：form-urlencoded 单字段 REQ_MESSAGE，业务参数再包一层 params。"""
    message = {"REQ_HEAD": {"TRAN_PROCESS": "", "TRAN_ID": "", "ACCESS_TOKEN": "",
                            "REFRESH_TOKEN": ""},
               "REQ_BODY": {"unnessaryLogin": True, "params": params}}
    r = client.post(f"{_BANKCOMM_API}{op}.do",
                    data={"REQ_MESSAGE": json.dumps(message, ensure_ascii=False)})
    _raise_if_gone(r)
    r.raise_for_status()
    # 解不出对象 → 返 {}：TRAN_SUCCESS 缺席 = 「没答成」，走不判死的分支。
    return _loads_object(r) or {}


def _bankcomm_listed(client, position_id, engage_type):
    """按 positionId 精确查列表：True=还挂着 / False=接口答成了但没有这个岗 / None=没答成。
    None 与 False 必须分开——「没答成」不构成撤岗证据。"""
    payload = _bankcomm_call(client, "querySocietyRecruitInfo", {
        "businessPara": {"workPlace": "", "pubName": "", "positionId": position_id,
                         "engageType": engage_type},
        "pagePara": {"pageNum": 1, "pageSize": 10}})
    if str((payload.get("RSP_HEAD") or {}).get("TRAN_SUCCESS")) != "1":
        return None
    results = ((payload.get("RSP_BODY") or {}).get("results") or {})
    rows = results.get("policyList") or []
    return any(str(x.get("positionId")) == str(position_id) for x in rows)


def _detail_bankcomm(row, src):
    """交行 job.bankcomm.com：POST queryPositionDetail 拿正文，撤岗要**两跳确认**。

    ⚠️ **不能拿详情接口的错误码判死**：不存在的 positionId 返回的是
    `TRAN_SUCCESS=0` + `ERROR_CODE=JUMPTESTBP9001` +「系统异常」——而这正是这个站的
    **通用系统异常码**（adapters/bankcomm.py 的 docstring 记着：业务参数少包一层 params
    也返同一个码）。光凭它判死，对方后端抖一下就会把整个源清空。

    所以死亡判定走第二跳：**按 positionId 精确查列表**（列表接口支持 positionId 过滤，
    2026-09-06 live 验证：真 id → total=1 且 id 对得上；伪/相邻/陈旧 id → TRAN_SUCCESS=1 + total=0）。
    只有「列表接口答成了、且社招校招两个板块都查不到这个 id」才判死。
    ⚠️ 两个板块都查是必须的：live 实测同一个真 id 传错 engageType 就返 total=0——
    只查一个板块的话，岗位换了板块就会被误杀。
    ⚠️ positionId 为空时**绝不能发这个查询**：空值会返回整版岗位（total=15），把「没查到」
    伪装成「查到了」。所以最前面就 return。"""
    position_id, section = _bankcomm_target(row["jd_url"])
    if not position_id:
        return ""
    headers = {**UA, "Content-Type": "application/x-www-form-urlencoded",
               "Referer": BankcommAdapter.REFERER}
    with _cn_portal_client(headers) as client:
        payload = _bankcomm_call(client, "queryPositionDetail", {"positionId": position_id})
        if str((payload.get("RSP_HEAD") or {}).get("TRAN_SUCCESS")) == "1":
            detail = (payload.get("RSP_BODY") or {}).get("results")
            if not isinstance(detail, dict):
                return ""
            return BankcommAdapter._summary_of({"_detail": detail}) or ""
        primary = _BANKCOMM_ENGAGE.get(section, 3)
        for engage_type in (primary, *(v for v in (3, 1) if v != primary)):
            listed = _bankcomm_listed(client, position_id, engage_type)
            if listed is None:
                return ""    # 列表接口也没答成 → 站点不在状态，不判死
            if listed:
                return ""    # 岗还挂着（只是详情这一跳没给）→ 绝不判死
    raise JobClosedError(f"bankcomm positionId={position_id} closed (not listed on either board)")


_CMCC_VIEW_API = "https://job.10086.cn/job-app/job/viewJob.do"
_CMCC_NOT_FOUND_CODE = "2000"
_CMCC_NOT_FOUND_MSG = "未查询到职位信息"
_CMCC_OK_CODE = "0000"


def _detail_cmcc(row, src):
    """中国移动 job.10086.cn：POST viewJob.do，签名头与列表接口同一套（_sign_header）。

    撤岗信号：`code="2000"` + `message="未查询到职位信息"`（2026-09-06 live：全零 uuid /
    改一位的 uuid / 非 uuid 三种伪值签名一致，且同一个伪 id 连打三次结果稳定）。
    在招岗 → `code="0000"` + data 全量字段（含 status=1）。

    ⚠️ 这个站**用 HTTP 200 表达失败**，必须按 code 判：签名错返 code=9999、空 id 返
    code=1001「必填项为空」——两者都不是撤岗，一律返 ""。判死要求 code 与 message
    同时对上，只认 code=2000 的话，哪天它把这个码复用成别的语义就会误杀。
    ⚠️ 每次调用都要重新签名（digest 里带毫秒时间戳），不能缓存 header。
    ⚠️ **不要带 `Accept: application/json`**：带上之后 viewJob.do 会返回**双层编码**的 JSON
    （body 是一个 JSON 字符串，里面才是对象），`r.json()` 拿到的是 str 而不是 dict
    （2026-09-06 实测；adapters/cmcc.py 的列表调用不带 Accept，所以从没撞上这个）。
    这里两手都做：请求头对齐 adapter，解析再用 _loads_object 兜住双层编码——否则一个
    AttributeError 会把整源探活都变成 'err'，看起来像网络抖动、实则永远不会自己好。"""
    job_id = (parse_qs(urlparse(row["jd_url"]).query).get("id") or [""])[0]
    if not job_id:
        return ""
    headers = {"User-Agent": UA["User-Agent"], "Content-Type": "application/json",
               "Referer": CmccAdapter.LIST_REFERER}
    with _cn_portal_client(headers) as client:
        r = client.post(_CMCC_VIEW_API, json={"serviceName": "viewJob",
                                              "header": _cmcc_sign_header(),
                                              "data": {"id": job_id}})
    _raise_if_gone(r)
    if r.status_code >= 300:
        return ""
    payload = _loads_object(r)
    if payload is None:
        return ""
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "")
    if code == _CMCC_NOT_FOUND_CODE and _CMCC_NOT_FOUND_MSG in message:
        raise JobClosedError(f"cmcc id={job_id} closed: {message}")
    if code != _CMCC_OK_CODE:
        return ""      # 9999 签名无效 / 1001 必填项为空 —— 都是我们这边的问题，不是撤岗
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    return CmccAdapter._summary_of(data) or ""


ENRICH_REGISTRY = {
    "huawei": _detail_huawei,
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
    "siemens": _detail_avature,
    # 欧莱雅 Avature live 验证不存在 JobDetail 为 404，由共享 _raise_if_gone 判死；
    # Siemens 的特殊 403 + 错误页分支仍保留，且只有命中文案才会判死。
    "avature": _detail_avature,
    "successfactors": _detail_successfactors,  # SF CSB 详情 SSR：正则抽 jobdescription span（多数租户有；ZF 类无正文租户返空）
    "google": _detail_google,
    "sf_express": _detail_sf_express,
    "tencent": _detail_tencent,
    "vivo": _detail_vivo,
    # 盲区六家（2026-08-28，真伪 id live 对拍，见各函数注释）：
    "jd": _detail_jd,
    "antgroup": _detail_antgroup,
    "haier": _detail_haier,
    "ashby": _detail_ashby,
    "mihoyo": _detail_mihoyo,
    "tencent_music": _detail_tencent_music,
    "iguopin": _detail_iguopin,
    "pinduoduo": _detail_pinduoduo,
    "chnenergy": _detail_chnenergy,
    # meituan_campus 的 jd_url 与 meituan 完全同构（同 jobUnionId 参数、同接口；live 验证
    # 伪 id 返 status=0+「职位已下线或不存在！」与 _detail_meituan 判死逻辑逐字节吻合）：
    "meituan_campus": _detail_meituan,
    # 国有大行 + 中国移动自建门户（2026-09-06，真伪 id live 对拍，见各函数注释）：
    # 接入前这五个源的 9,292 个 active 岗**零撤岗路径**——既不在 ENRICH_REGISTRY（sweep 够不着）、
    # supports_absence_liveness 也全是默认 False，岗位只进不出。
    # ⚠️ abchina（农行 2,418 岗）刻意不在这里：它走浏览器，且它的详情页判死另有坑，见 docstring 顶部。
    "spdb": _detail_spdb,
    "icbc": _detail_icbc,
    "ccb": _detail_ccb,
    "bankcomm": _detail_bankcomm,
    "cmcc": _detail_cmcc,
    # alibaba_campus 暂缺：13 个 BU 白标域名各自独立 cookie+CSRF 会话，详情接口已 live 验证
    # （POST /position/detail，content:null=撤岗），需 per-host session 管理，单独排期。
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
