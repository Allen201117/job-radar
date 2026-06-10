"""华为招聘（career.huawei.com）自建门户适配器（直连公开 JSON 接口，零浏览器、零鉴权）。

华为招聘门户 portal5 公开 GET 接口（无 token / 无签名 / 无 cookie 依赖）：
  https://career.huawei.com/reccampportal/services/portal/portalpub/getJob/newHr/page/{size}/{page}
    ?curPage={page}&pageSize={size}&jobFamilyCode=&deptCode=&keywords=&searchType=1
    &orderBy=P_COUNT_DESC&jobType={1社招|2校招|3实习}
  返回 {"pageVO":{"totalRows":N,"totalPages":M,...},"result":[{jobId, jobname/nameCn,
   mainBusiness(岗位职责正文), jobArea("中国/天津"), jobAddress, jobFamilyName, jobType,
   workYear, degree, deptName, ...}]}
逐岗稳定详情页（id-only，dataSource 字段随响应）：
  social：https://career.huawei.com/reccampportal/portal5/social-recruitment-detail.html?jobId={id}&dataSource={ds}
  campus/intern：…/campus-recruitment-detail.html?jobId={id}&dataSource={ds}
  （live render-verify 过：social 29908 渲染「综合法务专员」正文、campus 24406 渲染岗位职责，过质量门。）
company 恒为「华为」（自建门户，无张冠李戴风险）。adapter 内部遍历 jobType 1/2/3 三渠道，按 jobId 去重。
"""
import json
from typing import Optional

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _first(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


# jobType → (详情页路由前缀, 三桶分类标签)
_CHANNEL = {
    "1": ("social-recruitment-detail", "社会招聘"),
    "2": ("campus-recruitment-detail", "校园招聘"),
    "3": ("campus-recruitment-detail", "实习"),
}
_PORTAL = "https://career.huawei.com/reccampportal/portal5"
_API = ("https://career.huawei.com/reccampportal/services/portal/portalpub"
        "/getJob/newHr/page/{size}/{page}")


class HuaweiAdapter(PlaywrightAdapter):
    """华为自建门户 career.huawei.com。source_url 填
    `https://career.huawei.com/reccampportal/portal5/social-recruitment.html`，
    adapter 内部遍历 jobType 1/2/3 三渠道。"""

    name = "huawei"
    company_name = "华为"
    official_hosts = ("career.huawei.com",)

    _PAGE_SIZE = 50
    _MAX_PAGES = 15   # 50×15=750/渠道 封顶（实习实有 431）
    posts_keys = ("result",) + PlaywrightAdapter.posts_keys

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Referer": f"{_PORTAL}/social-recruitment.html",
        }
        collected = []
        seen_ids = set()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for job_type in ("1", "2", "3"):
                total = None
                got = 0
                for page in range(1, self._MAX_PAGES + 1):
                    url = _API.format(size=self._PAGE_SIZE, page=page) + (
                        f"?curPage={page}&pageSize={self._PAGE_SIZE}"
                        f"&jobFamilyCode=&deptCode=&keywords=&searchType=1"
                        f"&orderBy=P_COUNT_DESC&jobType={job_type}"
                    )
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                        payload = resp.json()
                    except (httpx.HTTPError, ValueError):
                        break
                    rows = payload.get("result") or []
                    if not rows:
                        break
                    fresh = []
                    for row in rows:
                        jid = row.get("jobId")
                        if jid in seen_ids:
                            continue
                        seen_ids.add(jid)
                        row["_jobType"] = job_type
                        fresh.append(row)
                    if fresh:
                        collected.append({"result": fresh})
                    got += len(rows)
                    if total is None:
                        total = (payload.get("pageVO") or {}).get("totalRows") or 0
                    if total and got >= total:
                        break
        if not collected:
            raise RuntimeError("huawei: empty getJob (career.huawei.com)")
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        jid = _first(post, ("jobId",))
        title = _first(post, ("jobname", "nameCn", "jobNameCN"))
        if not (jid and title):
            return None
        job_type = post.get("_jobType") or "1"
        path, label = _CHANNEL.get(job_type, _CHANNEL["1"])
        ds = _first(post, ("dataSource",)) or "1"
        jd_url = f"{_PORTAL}/{path}.html?jobId={jid}&dataSource={ds}"
        # mainBusiness = 岗位职责正文；部分岗附族类/部门作补充
        body = _first(post, ("mainBusiness",))
        fam = _first(post, ("jobFamilyName",))
        summary = (body + (f"\n\n【职位族】{fam}" if fam else "")).strip() or None
        # jobArea 形如「中国/天津」，取末段城市
        area = _first(post, ("jobArea",))
        location = area.split("/")[-1].strip() if area else None
        return RawJob(
            company=self.company_name,
            title=title,
            location=location or None,
            job_type=label,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
