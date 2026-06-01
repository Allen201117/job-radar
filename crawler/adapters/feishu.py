"""
飞书/Lark 招聘平台通用层（{company}.jobs.feishu.cn）。

与字节同平台：拦截 /api/v1/search/job/posts，岗位在 data.job_post_list，
详情页 https://{host}/index/position/{id}/detail。一套适配覆盖蔚来/小鹏/地平线/小米。
"""
from typing import Optional

from .base import RawJob
from .playwright_base import PlaywrightAdapter


class FeishuRecruitAdapter(PlaywrightAdapter):
    host = ""  # 子类设置，如 nio.jobs.feishu.cn
    intercept_match = "/api/v1/search/job/posts"
    posts_keys = ("data.job_post_list", "job_post_list")

    def __init__(self):
        self.official_hosts = (self.host,)
        self.detail_template = "https://" + self.host + "/index/position/{id}/detail"
        self.list_urls = [
            "https://" + self.host + "/index/position",
            "https://" + self.host + "/",
        ]

    def _map(self, post: dict) -> Optional[RawJob]:
        pid = str(post.get("id") or post.get("code") or "").strip()
        title = (post.get("title") or "").strip()
        if not pid or not title:
            return None

        city = ""
        ci = post.get("city_info")
        if isinstance(ci, dict):
            city = ci.get("name") or ""
        if not city:
            cl = post.get("city_list")
            if isinstance(cl, list) and cl and isinstance(cl[0], dict):
                city = cl[0].get("name") or ""

        job_type = ""
        jc = post.get("job_category")
        if isinstance(jc, dict):
            job_type = jc.get("name") or ""

        jd_url = self.detail_template.format(id=pid)
        return RawJob(
            company=self.company_name, title=title, location=city or None,
            job_type=job_type or None, jd_url=jd_url, apply_url=jd_url,
            summary=(post.get("description") or None),
        )


class NioAdapter(FeishuRecruitAdapter):
    name = "nio_feishu"; company_name = "蔚来"; host = "nio.jobs.feishu.cn"


class XpengAdapter(FeishuRecruitAdapter):
    name = "xpeng_feishu"; company_name = "小鹏汽车"; host = "xiaopeng.jobs.feishu.cn"


class HorizonAdapter(FeishuRecruitAdapter):
    name = "horizon_feishu"; company_name = "地平线"; host = "horizon.jobs.feishu.cn"


class XiaomiAdapter(FeishuRecruitAdapter):
    name = "xiaomi_feishu"; company_name = "小米"; host = "xiaomi.jobs.feishu.cn"
