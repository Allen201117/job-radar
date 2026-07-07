"""比亚迪招聘适配器。

列表和详情 JSON 接口公开，但逐岗页面 URL 含前端 AES 加密参数。适配器先用公开
queryList 按行偏移量拉全列表，再让官方页面的 Vue Router 批量生成每个职位的加密
详情 URL；无需逐个点击。queryDetail 只用于有限正文富化，不限制列表岗位产出。
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_detail_cap
from .china_location import is_china_company_location


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list_offsets(total: int, page_size: int) -> List[int]:
    """Return queryList row offsets; its pageNum parameter is an offset, not a page index."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    return list(range(0, max(1, total), page_size))


class BydAdapter(BaseAdapter):
    name = "byd"
    company_name = "比亚迪"
    LIST_API = "https://job.byd.com/portal/api/portal-api/position/queryList"
    DETAIL_API = "https://job.byd.com/portal/api/portal-api/position/queryDetail"
    LIST_PAGE_SIZE = 1000
    # queryDetail 是公开 httpx 接口（非浏览器、很快）→ 默认覆盖全量列表逐岗补 JD 正文（~2k 岗，并发约 1-2min）。
    # 旧 DETAIL_CAP=20 只补 20 个 → 其余 ~2000 岗全是无正文薄卡（不进 count_valid_active_jobs）。
    # 快档 daily 仍可用 env CRAWL_DETAIL_CAP=0 跳过逐岗富化（resolve_detail_cap），只抓列表骨架。
    DETAIL_CAP = 6000
    DETAIL_WORKERS = 10  # 单 host(job.byd.com) 并发上限：礼貌 + 防限流
    ROUTE_BATCH_SIZE = 500

    def should_skip(self, source_url: str) -> Optional[str]:
        return None

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://job.byd.com/portal/pc/",
            "Origin": "https://job.byd.com",
        }

    def _list_payload(self, offset: int) -> dict:
        return {
            "positionTypeArr": [],
            "positionProvinceArr": [],
            "positionCityArr": [],
            "positionOrgArr": [],
            "vagueCondition": "",
            "searchType": 1,
            "zpType": "00251",
            "pageNum": offset,
            "pageSize": self.LIST_PAGE_SIZE,
        }

    def _fetch_list_rows(self, client: httpx.Client) -> List[dict]:
        rows_by_id = {}
        total = 0
        offsets = [0]
        for offset in offsets:
            response = client.post(self.LIST_API, json=self._list_payload(offset))
            response.raise_for_status()
            body = response.json() or {}
            data = body.get("data") or {}
            rows = data.get("data") or []
            if offset == 0:
                reported = _int_or_none(data.get("total"))
                if reported is not None:
                    self.reported_total = reported
                total = int(data.get("total") or len(rows))
                offsets.extend(_list_offsets(total, self.LIST_PAGE_SIZE)[1:])
            for row in rows:
                job_id = str((row or {}).get("id") or "").strip()
                if job_id:
                    rows_by_id[job_id] = row
        if total and len(rows_by_id) < total:
            raise RuntimeError(
                f"byd: queryList returned {len(rows_by_id)} unique rows, expected {total}"
            )
        return list(rows_by_id.values())

    def _generate_detail_urls(self, source_url: str, job_ids: List[str]) -> dict:
        from playwright.sync_api import sync_playwright

        urls = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                locale="zh-CN",
                viewport={"width": 1366, "height": 900},
            )
            page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_function(
                """() => {
                    const root = document.querySelector('#app');
                    return root && root.__vue__ && root.__vue__.$router;
                }""",
                timeout=15000,
            )
            for start in range(0, len(job_ids), self.ROUTE_BATCH_SIZE):
                batch = job_ids[start:start + self.ROUTE_BATCH_SIZE]
                resolved = page.evaluate(
                    """ids => {
                        const router = document.querySelector('#app').__vue__.$router;
                        return ids.map(id => {
                            const route = router.resolve({
                                path: '/social/socialPositionDetails',
                                query: {id},
                            });
                            return [id, new URL(route.href, location.origin).href];
                        });
                    }""",
                    batch,
                )
                urls.update(dict(resolved))
            browser.close()
        return urls

    def _fetch_one_detail(self, client: httpx.Client, job_id: str) -> dict:
        """单岗 queryDetail（公开 httpx POST）→ data dict；任何网络/解析错误返回空（不阻断整批）。"""
        try:
            response = client.post(self.DETAIL_API, json={"id": job_id, "pageSize": 4})
            response.raise_for_status()
            return (response.json() or {}).get("data") or {}
        except (httpx.HTTPError, ValueError):
            return {}

    def _fetch_details(self, client: httpx.Client, job_ids: List[str]) -> dict:
        """并发用公开 queryDetail 给全量列表逐岗补 JD 正文（tagDetailList → summary）。返回 {job_id: detail}。
        cap=0（快档 CRAWL_DETAIL_CAP=0）→ 跳过逐岗富化；否则取前 cap 个（默认 DETAIL_CAP 覆盖全量）。"""
        cap = resolve_detail_cap(self.DETAIL_CAP)
        targets = job_ids[:cap] if cap else []
        if not targets:
            return {}
        details = {}
        with ThreadPoolExecutor(max_workers=self.DETAIL_WORKERS) as ex:
            futures = {ex.submit(self._fetch_one_detail, client, jid): jid for jid in targets}
            for fut in as_completed(futures):
                detail = fut.result()
                if detail:
                    details[futures[fut]] = detail
        return details

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = self._headers()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            list_rows = self._fetch_list_rows(client)
            job_ids = [str(row.get("id")) for row in list_rows]
            detail_urls = self._generate_detail_urls(source_url, job_ids)

            details = self._fetch_details(client, job_ids)

        jobs = []
        for row in list_rows:
            job_id = str(row.get("id") or "").strip()
            detail_url = detail_urls.get(job_id)
            if detail_url and "socialPositionDetails?" in detail_url:
                jobs.append({
                    "row": row,
                    "detail": details.get(job_id) or {},
                    "jd_url": detail_url,
                })
        if not jobs:
            raise RuntimeError(
                "byd: official router generated no encrypted detail URLs"
            )
        self.fetch_complete = (
            self.reported_total is not None and len(list_rows) >= self.reported_total
        )
        return json.dumps({"jobs": jobs}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for item in rows:
            detail = item.get("detail") or {}
            row = item.get("row") or {}
            jd_url = str(item.get("jd_url") or "").strip()
            title = str(detail.get("positionName") or row.get("positionName") or "").strip()
            province = str(detail.get("province") or row.get("province") or "").strip()
            city = str(detail.get("city") or row.get("city") or "").strip()
            location = "-".join(part for part in (province, city) if part)
            if not (
                title
                and jd_url.startswith("https://job.byd.com/portal/pc/#/social/")
                and "socialPositionDetails?" in jd_url
                and is_china_company_location(location)
            ):
                continue
            sections = []
            for section in detail.get("tagDetailList") or []:
                if not isinstance(section, dict):
                    continue
                name = str(section.get("name") or "").strip()
                text = str(section.get("detail") or "").strip()
                if text:
                    sections.append(f"【{name}】\n{text}" if name else text)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type=(
                    str(
                        detail.get("orgName")
                        or detail.get("fatherOrgName")
                        or row.get("orgAliasName")
                        or row.get("fatherOrgAliasName")
                        or ""
                    ).strip()
                    or None
                ),
                summary="\n\n".join(sections) or None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(
                    str(
                        detail.get("publishTime")
                        or row.get("publishTime")
                        or row.get("createTime")
                        or ""
                    )[:10]
                    or None
                ),
            ))
        return jobs
