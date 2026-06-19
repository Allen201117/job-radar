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
    max_pages = 4

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
