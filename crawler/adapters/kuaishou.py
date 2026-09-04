"""快手招聘浏览器签名拦截适配器（社招 + 日常实习）。

## 合规边界（红线，别绕）
- `campus.kuaishou.cn/robots.txt` = `User-agent: * / Disallow: /` → **校招板块一律不抓**。
  官网「校园招聘」这个 tab 点下去就是跳到那个域名，所以快手校招对我们来说不存在。
- `zhaopin.kuaishou.cn` 没有 robots.txt（404）→ 社招与**日常实习**都在这个域名下，可抓。

## 为什么要抓「日常实习」
它和社招同域、同接口、同签名，只差一个 `positionNatureCode`（C001 社招 / C002 实习），
但此前只配了社招 URL —— 1,087 个实习岗白白漏掉，而实习正是校招专区的核心供给之一。
岗位行**自带 positionNatureCode**，所以 _map 能逐条判类型，不需要按来源 URL 打标。
"""
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
        # 日常实习（C002）：同域同接口，只是另一个 tab。校招 tab 指向 campus.kuaishou.cn，
        # 那个域名 robots 全站禁止，**不要加进来**。
        "https://zhaopin.kuaishou.cn/#/official/trainee/?workLocationCode=domestic",
    ]
    wait_ms = 6000
    max_pages = 160  # 每个 list_url 各自的翻页上限。live: 社招 1,285 岗≈129 页 / 实习 1,087≈109 页

    # positionNatureCode → (三桶分类要的类型标签, 详情页路由段)。
    # 详情页两个路由段其实通用（实测拿实习 id 走 /social/ 也能渲染出同一个岗），
    # 但仍按类型走各自的段：语义正确，且实习岗是新增的、不存在改 canonical_jd_url 把存量打成重复的问题。
    _NATURE = {"C001": ("社会招聘", "social"), "C002": ("实习", "trainee")}

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
        # 岗位行自带 positionNatureCode，逐条判类型——不要按「来自哪个 list_url」推断：
        # PlaywrightAdapter 把多个 URL 的拦截结果汇成一个 blob，_map 拿不到来源。
        job_type, route = self._NATURE.get(
            str(post.get("positionNatureCode") or "").strip().upper(), ("社会招聘", "social"))
        jd_url = (
            f"https://zhaopin.kuaishou.cn/#/official/{route}/job-info/"
            f"{job_id}"
        )
        return RawJob(
            company=self.company_name,
            title=title,
            location="、".join(dict.fromkeys(locations)),
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
