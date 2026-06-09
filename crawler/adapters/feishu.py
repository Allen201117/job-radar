"""
飞书/Lark 招聘平台通用层（{company}.jobs.feishu.cn）。

与字节同平台：拦截 /api/v1/search/job/posts，岗位在 data.job_post_list，
详情页 https://{host}/index/position/{id}/detail。一套适配覆盖蔚来/小鹏/地平线/小米。
"""
from typing import Optional
from urllib.parse import urlparse

import normalizer
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

        desc = (post.get("description") or "").strip()
        req = (post.get("requirement") or "").strip()
        summary = (desc + ("　【职位要求】" + req if req else "")).strip() or None
        jd_url = self.detail_template.format(id=pid)
        return RawJob(
            company=self.company_name, title=title, location=city or None,
            job_type=job_type or None, jd_url=jd_url, apply_url=jd_url,
            summary=summary, posted_at=normalizer.pick_publish_date(post),
        )


class FeishuGenericAdapter(FeishuRecruitAdapter):
    """飞书招聘**数据驱动**通用适配器（国内版 Workday）：host 从 source_url 动态解析，不再每家硬编码子类。
    一套覆盖所有用飞书招聘的公司（造车新势力 / 大量互联网与科技中企）。
    onboard = 加一行 sources，source_url 填该公司飞书招聘页（如 https://{tenant}.jobs.feishu.cn/index/position）。
    company 由 sources.company 兜底；岗位接口/字段/详情页格式复用 FeishuRecruitAdapter。"""
    name = "feishu"
    company_name = ""  # 由 sources.company 兜底

    def __init__(self):
        # 不在 init 固定 host —— 留到 fetch 时按 source_url 解析（见 _bind_host）。
        self.official_hosts = ()
        self.detail_template = ""
        self.list_urls = []

    def _bind_host(self, source_url: str):
        parsed = urlparse(source_url)
        host = parsed.netloc
        path = (parsed.path or "").strip("/")
        if path and path != "index/position":
            portal_base = "/" + path.split("/")[0]
        else:
            portal_base = "/index"
        self.official_hosts = (host,)
        self.detail_template = f"https://{host}{portal_base}/position/{{id}}/detail"
        standard_url = f"https://{host}/index/position"
        # 自定义 portal slug（如 /ponyai、/talent、/social）优先打开传入入口；标准入口保持原行为。
        if path and path != "index/position":
            self.list_urls = [f"https://{host}{portal_base}", standard_url]
        else:
            self.list_urls = [standard_url, source_url]
        return host

    def fetch(self, source_url: str) -> str:
        self._bind_host(source_url)
        return super().fetch(source_url)


class NioAdapter(FeishuRecruitAdapter):
    name = "nio_feishu"; company_name = "蔚来"; host = "nio.jobs.feishu.cn"


class XpengAdapter(FeishuRecruitAdapter):
    name = "xpeng_feishu"; company_name = "小鹏汽车"; host = "xiaopeng.jobs.feishu.cn"


class HorizonAdapter(FeishuRecruitAdapter):
    name = "horizon_feishu"; company_name = "地平线"; host = "horizon.jobs.feishu.cn"


class XiaomiAdapter(FeishuRecruitAdapter):
    name = "xiaomi_feishu"; company_name = "小米"; host = "xiaomi.jobs.f.mioffice.cn"
