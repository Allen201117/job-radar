"""比亚迪招聘浏览器适配器。

列表和详情 JSON 接口公开，但逐岗页面 URL 含前端生成的加密参数。适配器让官方页面
自己生成 URL：加载社会招聘首屏，点击真实岗位标题捕获 popup，再用公开 queryDetail
接口补齐正文。只放行成功捕获到详情 URL 的岗位。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


class BydAdapter(BaseAdapter):
    name = "byd"
    company_name = "比亚迪"
    LIST_MATCH = "/portal-api/position/queryList"
    DETAIL_API = "https://job.byd.com/portal/api/portal-api/position/queryDetail"
    MAX_JOBS = 20

    def should_skip(self, source_url: str) -> Optional[str]:
        return None

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        list_rows = []
        captured = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                locale="zh-CN",
                viewport={"width": 1366, "height": 900},
            )
            page = context.new_page()

            def on_response(response):
                if self.LIST_MATCH not in response.url:
                    return
                try:
                    body = response.json() or {}
                    rows = ((body.get("data") or {}).get("data") or [])
                    if rows:
                        list_rows[:] = rows
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(7000)

            cancel = page.get_by_text("取消", exact=True)
            if cancel.count():
                try:
                    cancel.last.click(timeout=3000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            links = page.locator("span.position-link")
            limit = min(links.count(), len(list_rows), self.MAX_JOBS)
            for index in range(limit):
                popup = None
                try:
                    with page.expect_popup(timeout=10000) as popup_info:
                        links.nth(index).click(timeout=8000)
                    popup = popup_info.value
                    popup.wait_for_timeout(1200)
                    detail_url = popup.url
                    if "socialPositionDetails?" in detail_url:
                        captured.append({
                            "row": list_rows[index],
                            "jd_url": detail_url,
                        })
                except Exception:
                    continue
                finally:
                    if popup:
                        try:
                            popup.close()
                        except Exception:
                            pass
            browser.close()

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://job.byd.com/portal/pc/",
            "Origin": "https://job.byd.com",
        }
        jobs = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for item in captured:
                job_id = str((item.get("row") or {}).get("id") or "").strip()
                if not job_id:
                    continue
                try:
                    response = client.post(
                        self.DETAIL_API,
                        json={"id": job_id, "pageSize": 4},
                    )
                    response.raise_for_status()
                    detail = (response.json() or {}).get("data") or {}
                except (httpx.HTTPError, ValueError):
                    continue
                if detail:
                    jobs.append({
                        "row": item.get("row") or {},
                        "detail": detail,
                        "jd_url": item["jd_url"],
                    })
        if not jobs:
            raise RuntimeError(
                "byd: no browser-verified detail URLs captured from first page"
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
                    str(detail.get("orgName") or detail.get("fatherOrgName") or "").strip()
                    or None
                ),
                summary="\n\n".join(sections) or None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(
                    str(detail.get("publishTime") or row.get("createTime") or "")[:10]
                    or None
                ),
            ))
        return jobs
