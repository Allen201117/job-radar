"""
字节跳动 — jobs.bytedance.com（飞书/Lark 招聘平台，客户端渲染 SPA）。

拦截站点自身岗位搜索接口 /api/v1/search/job/posts 的响应，详情页为
jobs.bytedance.com/experienced/position/{id}（社招）。spike 已验证可拿真实岗位。
"""
from typing import Optional
from urllib.parse import quote

from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _kw(term: str) -> str:
    return f"https://jobs.bytedance.com/experienced/position?keyword={quote(term)}"


class BytedanceAdapter(PlaywrightAdapter):
    name = "bytedance"
    company_name = "字节跳动"
    official_hosts = ("jobs.bytedance.com",)
    intercept_match = "/api/v1/search/job/posts"
    detail_template = "https://jobs.bytedance.com/experienced/position/{id}"
    posts_keys = ("data.job_post_list", "job_post_list", "data.posts", "posts")
    # 广度抓取：几个高频方向关键词 + 一个空 query，覆盖更广岗位灌入共享库
    list_urls = [
        _kw("算法"),
        _kw("工程"),
        _kw("产品"),
        _kw("运营"),
        "https://jobs.bytedance.com/experienced/position",
    ]

    def _map(self, post: dict) -> Optional[RawJob]:
        pid = str(post.get("id") or post.get("code") or post.get("job_id") or "").strip()
        title = (post.get("title") or post.get("name") or "").strip()
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
            company="字节跳动",
            title=title,
            location=city or None,
            job_type=job_type or None,
            summary=(post.get("description") or None),
            jd_url=jd_url,
            apply_url=jd_url,
        )
