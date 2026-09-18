"""多益网络招聘官网（xz.duoyi.com 校招 / sz.duoyi.com 社招）适配器 —— 纯 httpx，零登录、零浏览器。

## 站点形态（2026-09-18 live 探明）
两个 host 是**同一套后端**：`recruit` 参数选渠道，host 只是前端皮肤——
xz host 传 `recruit=20` 照样返回社招全集（total 57），反之亦然。所以渠道**只认 source_url 的
host 前缀**（xz → 校招 10，sz → 社招 20），不认页面。两渠道 id 空间不重叠（live 33 ∩ 57 = 0）。

- 列表：`GET /v40/api/index/positions/jds/page?recruit={10|20}&pageIndex={n}&pageSize={m}`
  → `{"message":"success","data":{"pageIndex","pageSize","total","list":[…]}}`
  ⚠️ 前缀是 `/v40/api`，裸 `/api/...` 是另一个 ASP.NET 站点，一律 500「页面出错」——
     接口路径要从前端 `$api` 的 baseURL 读（`/v40/api/deliveries/...` 同前缀），别照 JS 里的相对路径猜。
  ✅ pageIndex / pageSize 都真实生效（page1 ∩ page2 = 0，page2 = 13 = 33 − 20；pageSize=200 如实回显）。
- 正文：**列表行自带全文**（`jobResponsibility` + `jobRequirements`），不需要逐岗详情 → 零薄卡。
- 逐岗 jd_url：`https://{host}/v40/#/position-detail/{id}` —— 站点路由表里就是
  `path:"/position-detail/:id"`（hash 路由；`/v40/position-detail/{id}` 走 history 形态是 404）。
  `#` 后面 canonical 原样不碰。
- 判死（enrich._detail_duoyi）：`GET /v40/api/index/positions/{id}/jds`，
  真 id → `data` 为对象且 `name` 非空；不存在的 id → `{"message":"success","data":null,"code":0}`；
  格式非法 id → `code=10100`「服务端错误」（**不判死**）。

## 与顺丰/美的校招同一口径的两条纪律
- 「HTTP 200 + 结构不对」抛错记 failed，不许安静返 0 条（CLAUDE.md「接口返 0 ≠ 对方没开」）；
  `list: []` + `total: 0` 是合法空态照常放行。
- 抓全 = 翻页没截断 **且** 去重后条数 ≥ 自报 total（翻页期间上下架会让分页窗口滑动）。

## 诚实边界
- `outerNature` 只有「实习 / 正式」两种（live 校招 33 行里实习 1 / 正式 32）；校招渠道里标「实习」
  的岗 job_type 记「实习」，其余按渠道记「校园招聘」/「社会招聘」。
- 判死信号里「已下线但记录仍在」的反向证据**一条都没有**（多益没有公开历史岗位），
  现在只判得出「id 彻底不存在」；真实撤岗若走别的形态会漏判（安全方向）。
"""
import json
import logging
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_page_cap

logger = logging.getLogger(__name__)

_LIST_PATH = "/v40/api/index/positions/jds/page"
_DETAIL_PATH = "/v40/api/index/positions/{job_id}/jds"
_DETAIL_URL = "https://{host}/v40/#/position-detail/{job_id}"
# recruit 渠道码：站点自己的枚举（前端 `recruit:"xz"===this.type?10:20`）。
_CHANNEL_BY_HOST_PREFIX = {"xz": 10, "sz": 20}
_JOB_TYPE_BY_CHANNEL = {10: "校园招聘", 20: "社会招聘"}


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def channel_of(source_url: str) -> int:
    """source_url host 前缀 → recruit 渠道码。认不出直接抛错：拿错渠道抓回来的是另一个板块的岗。"""
    host = (urlparse(str(source_url or "")).hostname or "").lower()
    prefix = host.split(".")[0] if host.endswith(".duoyi.com") else ""
    channel = _CHANNEL_BY_HOST_PREFIX.get(prefix)
    if channel is None:
        raise RuntimeError(f"duoyi: source_url host 必须是 xz.duoyi.com 或 sz.duoyi.com，得到 {source_url!r}")
    return channel


class DuoyiAdapter(BaseAdapter):
    name = "duoyi"
    company_name = "多益网络"
    official_hosts = ("xz.duoyi.com", "sz.duoyi.com")
    PAGE_SIZE = 100

    def should_skip(self, source_url: str) -> Optional[str]:
        # SPA 壳 + hash 路由，HEAD 预检永远回同一份 index.html，没有信息量；
        # 2026-09-18 实测两个 host 的 HEAD 均 200，默认实现也不会跳过。
        # robots.txt 只 Disallow /welcome/ 与 /baidu/，/v40/ 与 /v40/api 不在其中。
        return None

    def _headers(self, host: str) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://{host}/v40/",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        channel = channel_of(source_url)
        host = urlparse(source_url).hostname.lower()
        self._host = host
        self._channel = channel

        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers=self._headers(host)) as client:

            def fetch_page(page_no: int) -> PageResult:
                resp = client.get(f"https://{host}{_LIST_PATH}", params={
                    "recruit": channel, "pageIndex": page_no, "pageSize": self.PAGE_SIZE,
                })
                resp.raise_for_status()
                try:
                    payload = resp.json() or {}
                except ValueError as exc:
                    raise RuntimeError(f"duoyi: 列表接口返回非 JSON（HTTP {resp.status_code}）") from exc
                data = payload.get("data") if isinstance(payload, dict) else None
                rows = (data or {}).get("list") if isinstance(data, dict) else None
                total = _int_or_none((data or {}).get("total")) if isinstance(data, dict) else None
                if not isinstance(rows, list) or total is None:
                    raise RuntimeError(
                        "duoyi: jds/page 结构异常"
                        f"（message={payload.get('message') if isinstance(payload, dict) else '?'!r} "
                        f"list={type(rows).__name__} total={total!r}）")
                return PageResult(items=rows, total=total)

            rows, total, complete = paginate_all(
                fetch_page,
                page_size=self.PAGE_SIZE,
                max_pages=resolve_page_cap(self.PAGE_SIZE),
                delay_seconds=0.2,
                label=f"{self.name}:{host}",
            )

        by_id = {}
        for row in rows:
            job_id = str((row or {}).get("id") or "").strip()
            if job_id:
                by_id[job_id] = row
        self.reported_total = total
        self.fetch_complete = bool(complete) and (total is None or len(by_id) >= total)
        return json.dumps({"host": host, "channel": channel, "rows": list(by_id.values())},
                          ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            doc = json.loads(payload) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        host = str(doc.get("host") or "xz.duoyi.com")
        channel = _int_or_none(doc.get("channel")) or 10
        jobs: List[RawJob] = []
        for row in doc.get("rows") or []:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("name") or "").strip()
            if not job_id or not title:
                continue
            places = [str(p).strip() for p in (row.get("workPlaces") or []) if str(p).strip()]
            location = places[0] if places else ""
            if location and not _in_source_regions(location, getattr(self, "regions", None)):
                continue
            jd_url = _DETAIL_URL.format(host=host, job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location or None,
                job_type=_job_type_of(row, channel),
                summary=_summary_of(row, places),
                jd_url=jd_url,
                apply_url=jd_url,
                salary_text=str(row.get("salaryRange") or "").strip() or None,
                posted_at=str(row.get("publishDate") or "").strip() or None,
            ))
        return jobs


def _in_source_regions(location: str, regions) -> bool:
    """只丢能确证在范围外的岗（同 sf_express_campus / midea_campus）：多益的地点是裸城市名
    （广州/武汉/苏州/杭州），`derive_country_code` 返回 None 是「证据不足」不是「证据相反」。"""
    if normalizer.location_in_source_regions(location, regions):
        return True
    return normalizer.derive_country_code(location) is None


def _job_type_of(row: dict, channel: int) -> str:
    natures = [str(n).strip() for n in (row.get("outerNature") or [])]
    if natures and all(n == "实习" for n in natures):
        return "实习"
    return _JOB_TYPE_BY_CHANNEL.get(channel, "社会招聘")


def _summary_of(row: dict, places) -> Optional[str]:
    """【任职要求】排在【岗位职责】前面：届别/学历硬信号在要求段，而 grad_class 只看截断后前 400 字
    （同 sf_express_campus 量出来的结论）。"""
    parts = []
    head = []
    kind = str(row.get("outerType") or "").strip()
    if kind:
        head.append(f"职位类型：{kind}")
    natures = [str(n).strip() for n in (row.get("outerNature") or []) if str(n).strip()]
    if natures:
        head.append("性质：" + " / ".join(natures))
    if len(places) > 1:
        head.append("工作城市：" + "、".join(places))
    if head:
        parts.append(" · ".join(head))
    requirement = str(row.get("jobRequirements") or "").strip()
    duty = str(row.get("jobResponsibility") or "").strip()
    if requirement:
        parts.append("【任职要求】\n" + requirement)
    if duty:
        parts.append("【岗位职责】\n" + duty)
    return "\n\n".join(parts) or None
