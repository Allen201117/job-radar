"""
通用 Eightfold 适配器（eightfold.ai 公开 Talent Intelligence 接口，无需鉴权）。

source_url = https://{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}
（如汇丰：https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com）
大量在华跨国企业（金融/制造/消费…外企100强）用 eightfold，greenhouse/lever/workday 都抓不到。
一套适配覆盖任意 eightfold 租户——新增公司只需加一行 sources（source_url 填该端点）。

服务「在华外企」：用接口的 `location` 参数**服务端**收窄到中国/香港，只抓在华岗位；
jd_url 用接口返回的 `canonicalPositionUrl`（公司自有 careers 域名的真实 per-job 链接，已 live 验证），
缺失时回退 {origin}/careers/job/{id}。接口 `num` 上限 10，必须翻页。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse, parse_qs

import httpx

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _reported_total_from_payload(data: dict) -> Optional[int]:
    for key in ("total", "count", "totalCount", "totalResults"):
        total = _int_or_none((data or {}).get(key))
        if total is not None:
            return total
    return None


class EightfoldAdapter(BaseAdapter):
    name = "eightfold"
    max_pages = 100         # num=10/页 → 每个地点安全上限 1000，靠接口 total/短页自然收尾
    china_locations = ("China", "Hong Kong")  # 服务端按地点收窄到大中华区
    overseas_locations = {
        "US": ("United States",),
        "SG": ("Singapore",),
        "Remote": ("Remote",),
    }

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        p = urlparse(source_url)
        origin = f"{p.scheme}://{p.netloc}"
        path = p.path or "/api/apply/v2/jobs"
        domain = (parse_qs(p.query).get("domain") or [""])[0]
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}

        collected: List[dict] = []
        seen_ids = set()
        locations = self._locations_for_regions()
        location_totals: List[int] = []
        location_complete: List[bool] = []
        for loc in locations:
            def fetch_page(page: int) -> PageResult:
                params = {"domain": domain, "location": loc,
                          "start": page * 10, "num": 10, "sort_by": "relevance"}
                r = httpx.get(f"{origin}{path}", params=params, headers=headers, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                positions = (data or {}).get("positions", []) or []
                return PageResult(
                    items=positions,
                    total=_reported_total_from_payload(data if isinstance(data, dict) else {}),
                )

            positions, loc_total, complete = paginate_all(
                fetch_page,
                page_size=10,
                first_page=0,
                max_pages=self.max_pages,
                logger=None,
                label=f"eightfold:{origin}:{loc}",
            )
            if loc_total is not None:
                location_totals.append(loc_total)
            location_complete.append(complete)
            for pos in positions:
                pid = pos.get("id")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                collected.append(pos)
        if len(location_totals) == len(locations):
            self.reported_total = sum(location_totals)

        # 逐岗 detail 抓正文 —— 列表接口的 job_description 恒为空（已 live 验证），外企卡片 JD 因此全空。
        # GET {origin}{path}/{id}?domain={domain} → 顶层 job_description（HTML）；run.py 的 clean_summary 去标签解实体，
        # summary 有正文后 extract_job_type 也能从中推断类型。只补将保留的在华岗，单源封顶防夜间全量被拖垮。
        self._enrich_descriptions(origin, path, domain, collected, headers)
        self.fetch_complete = (
            len(location_complete) == len(locations)
            and all(location_complete)
        )
        return json.dumps({"_origin": origin, "positions": collected}, ensure_ascii=False)

    _DETAIL_CAP = 300  # 单源逐岗 detail 抓取上限，避免拖垮夜间全量

    def _enrich_descriptions(self, origin: str, path: str, domain: str,
                             positions: List[dict], headers: dict):
        """逐岗 GET detail 端点把 job_description 挂到 position['_jd']（供 parse 取作 summary）。"""
        n = 0
        for p in positions:
            if n >= resolve_detail_cap(self._DETAIL_CAP):
                break
            if not isinstance(p, dict):
                continue
            # 与 parse 同口径：只补在华岗（服务端已按 location 收窄，这里再兜一层，省掉少数串入的非华岗 detail 调用）
            if not normalizer.location_in_source_regions(p.get("location"), getattr(self, "regions", None)):
                continue
            pid = p.get("id")
            if not pid:
                continue
            try:
                d = httpx.get(f"{origin}{path}/{pid}", params={"domain": domain},
                              headers=headers, timeout=self.timeout)
                if d.status_code < 300:
                    desc = d.json().get("job_description")
                    if desc:
                        p["_jd"] = desc
                    n += 1
            except Exception:
                continue

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        origin = data.get("_origin", "")
        out: List[RawJob] = []
        seen_urls = set()
        for p in data.get("positions", []):
            if not isinstance(p, dict):
                continue
            title = (p.get("name") or "").strip()
            location = p.get("location") or None
            if not title:
                continue
            # 服务端已按地点收窄，这里再按 regions 兜一层（排除少数串到的非目标地区岗）
            if not normalizer.location_in_source_regions(location, getattr(self, "regions", None)):
                continue
            jd_url = (p.get("canonicalPositionUrl") or "").strip()
            if not jd_url:
                pid = p.get("id")
                if not pid:
                    continue
                jd_url = f"{origin}/careers/job/{pid}"
            if jd_url in seen_urls:
                continue
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,  # run.py 用 extract_job_type(title, summary) 从正文推断
                summary=p.get("_jd"),  # detail 端点抓到的 job_description（HTML）；run.py clean_summary 去标签
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,
            ))
        return out

    def _locations_for_regions(self):
        regions = normalizer.source_regions(getattr(self, "regions", None))
        if regions == {"CN"}:
            return self.china_locations
        out = []
        if "CN" in regions:
            out.extend(self.china_locations)
        for region in sorted(regions):
            out.extend(self.overseas_locations.get(region, ()))
        return tuple(dict.fromkeys(out)) or self.china_locations
