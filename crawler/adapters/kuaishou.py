"""快手招聘浏览器签名拦截适配器。"""
from typing import Optional

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


_LOCATION_NAMES = {
    "Beijing": "北京",
    "Shanghai": "上海",
    "Guangzhou": "广州",
    "Shenzhen": "深圳",
    "Tianjin": "天津",
    "Hangzhou": "杭州",
    "Chengdu": "成都",
    "Wuhan": "武汉",
    "Qingdao": "青岛",
    "Yantai": "烟台",
    "Xian": "西安",
    "Wuxi": "无锡",
    "Huaian": "淮安",
    "Tongren": "铜仁",
    "Jishou": "吉首",
    "Chengmai": "澄迈",
}


def _pagination_click_budget(current_page: int, total_pages: int, max_pages: int) -> int:
    """Return how many next-page clicks are allowed by the real total and hard cap."""
    reachable_last_page = min(max(1, total_pages), max(1, max_pages))
    return max(0, reachable_last_page - max(1, current_page))


class KuaishouAdapter(PlaywrightAdapter):
    name = "kuaishou"
    company_name = "快手"
    official_hosts = ("zhaopin.kuaishou.cn",)
    intercept_match = "/open/positions/simple"
    posts_keys = ("result.list",)
    list_urls = [
        "https://zhaopin.kuaishou.cn/#/official/social/?workLocationCode=domestic",
    ]
    wait_ms = 6000
    max_pages = 160  # live 2026-06-19: 国内社招 149 页；留少量增长余量

    def _paginate(self, page):
        """Fast Ant pagination: wait for the active page number instead of a fixed 2.5s/page."""
        page_items = page.locator(".ant-pagination-item")
        page_numbers = []
        for text in page_items.all_inner_texts():
            try:
                page_numbers.append(int(text.strip()))
            except (TypeError, ValueError):
                continue
        active = page.locator(".ant-pagination-item-active")
        try:
            current_page = int(active.inner_text().strip())
        except (TypeError, ValueError):
            current_page = 1
        total_pages = max(page_numbers, default=current_page)

        for _ in range(_pagination_click_budget(
            current_page=current_page,
            total_pages=total_pages,
            max_pages=self.max_pages,
        )):
            button = page.locator(".ant-pagination-next").first
            if button.count() == 0:
                break
            classes = button.get_attribute("class") or ""
            if "ant-pagination-disabled" in classes:
                break
            previous = active.inner_text().strip()
            try:
                button.click(timeout=5000)
                page.wait_for_function(
                    """previous => {
                        const el = document.querySelector('.ant-pagination-item-active');
                        return el && (el.textContent || '').trim() !== previous;
                    }""",
                    arg=previous,
                    timeout=6000,
                )
            except Exception:
                break

    def _map(self, post: dict) -> Optional[RawJob]:
        job_id = str(post.get("id") or "").strip()
        title = str(post.get("name") or "").strip()
        if not (job_id and title):
            return None
        locations = [
            _LOCATION_NAMES.get(str(code), str(code))
            for code in (post.get("workLocationsCode") or [])
        ]
        locations = [
            location for location in locations
            if normalizer.is_china_location(location)
        ]
        if not locations:
            return None
        description = str(post.get("description") or "").strip()
        demand = str(post.get("positionDemand") or "").strip()
        summary = (
            description + ("\n\n【任职要求】\n" + demand if demand else "")
        ).strip() or None
        jd_url = (
            "https://zhaopin.kuaishou.cn/#/official/social/job-info/"
            f"{job_id}"
        )
        return RawJob(
            company=self.company_name,
            title=title,
            location="、".join(dict.fromkeys(locations)),
            job_type="社会招聘",
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
