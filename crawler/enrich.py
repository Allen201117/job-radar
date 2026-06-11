"""按 jd_url 反推官方 detail 端点 → 返回 JD 正文（summary）文本。

drain worker（enrich_backlog.py）+ on-demand（P3）共用。为何按 jd_url 反推而非 re-crawl 列表：
适配器补正文只作用于「当前仍挂 live 列表」的岗位，存量里已不在列表但仍 active 的空 summary 行
re-crawl 永远碰不到（实测 oracle 重爬 77→74 只清 3 行）——必须按 jd_url 直推 detail 端点。

httpx 类（无浏览器、可高并发）：workday/oracle/eightfold/smartrecruiters（搬已 live 验证的
backfill_foreign_summaries 逻辑）+ hotjob。browser 类（beisen/moka/feishu）P2 再加。

fetcher 签名：f(row: dict, src: dict) -> str（空串 = 无正文/已撤岗/404；异常上抛由调用方计死信）。
  row 需含 jd_url（+ title/job_type 供调用方派生）；src 需含 source_url/adapter_name。
"""
import re
from urllib.parse import urlparse, parse_qs

import httpx

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      "Accept": "application/json"}
TIMEOUT = 25


class JobClosedError(Exception):
    """源站明确告知该岗位已撤下/招聘已关闭（如 hotjob detail 返回 state=1017）。

    与「无正文」(fetcher 返回 "") 区分：这类岗永远补不到 summary 且应置 status='expired'，
    不是死信。**只在明确关闭信号时抛**——网络错误/限流仍走普通异常（调用方计 miss 重试），不得 expired。
    """


# --- 外企四家族：搬 scripts/backfill_foreign_summaries.py（已 live 验证，全是公开 JSON API） ---
def _detail_workday(row, src):
    # jd_url = {host}/{site}{ep}；detail = source_url 去尾部 /jobs 再拼 {ep}（ep 从 /job/ 起）
    m = re.search(r"(/job/.+)$", urlparse(row["jd_url"]).path)
    if not m:
        return ""
    cxs_base = re.sub(r"/jobs/?$", "", src["source_url"])
    r = httpx.get(f"{cxs_base}{m.group(1)}", headers=UA, timeout=TIMEOUT)
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
    if r.status_code >= 300:
        return ""
    items = r.json().get("items", []) or []
    if not items:
        return ""
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
    if r.status_code >= 300:
        return ""
    secs = (r.json().get("jobAd") or {}).get("sections") or {}
    parts = [(secs.get(k) or {}).get("text")
             for k in ("jobDescription", "responsibilities", "qualifications")]
    return " ".join(x for x in parts if x)


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
    if r.status_code >= 300:
        return ""
    j = r.json() or {}
    # 已撤岗：HTTP 200 + {"state":"1017","msg":"...招聘已经关闭...","type":"warning"}，无 data。
    # 这是明确的过期信号（≠ 无正文），上抛由调用方置 status='expired'。
    if str(j.get("state")) == "1017":
        raise JobClosedError(f"hotjob postId={post_id} closed: {j.get('msg') or 'state=1017'}")
    d = j.get("data") or {}
    return " ".join(x for x in (d.get("workContent"), d.get("serviceCondition")) if x)


# adapter_name -> fetcher（httpx 类，P1）
ENRICH_REGISTRY = {
    "workday": _detail_workday,
    "oracle": _detail_oracle,
    "eightfold": _detail_eightfold,
    "smartrecruiters": _detail_smartrecruiters,
    "hotjob": _detail_hotjob,
}

# 需渲染、低并发，P2 实现（仅占位以便 detail_class 分流）
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
