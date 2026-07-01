"""
字节跳动 — jobs.bytedance.com（飞书/Lark 招聘平台，客户端渲染 SPA）。

拦截站点自身岗位搜索接口 /api/v1/search/job/posts 的响应，详情页为
jobs.bytedance.com/experienced/position/{id}（社招）。spike 已验证可拿真实岗位。
"""
from typing import Optional
from urllib.parse import quote

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _kw(term: str) -> str:
    return f"https://jobs.bytedance.com/experienced/position?keyword={quote(term)}"


def _campus_kw(term: str) -> str:
    return f"https://jobs.bytedance.com/campus/position?keyword={quote(term)}"


class BytedanceAdapter(PlaywrightAdapter):
    name = "bytedance"
    # 招聘类型由**路由变体**决定（/experienced=社招），比 job_category(职能:研发/市场) 可靠。
    # 校招变体覆盖为"校招"；/campus 里的实习岗靠读取端"标题实习"信号盖成实习，故此处给"校招"即可。
    recruit_type = "社招"
    company_name = "字节跳动"
    official_hosts = ("jobs.bytedance.com",)
    intercept_match = "/api/v1/search/job/posts"
    detail_template = "https://jobs.bytedance.com/experienced/position/{id}/detail"
    posts_keys = ("data.job_post_list", "job_post_list", "data.posts", "posts")
    # 广度抓取：多个高频方向关键词 + 一个空 query，覆盖更广岗位灌入共享库（每日量目标 ≥50）
    list_urls = [
        _kw("算法"),
        _kw("工程"),
        _kw("产品"),
        _kw("运营"),
        _kw("数据"),
        _kw("设计"),
        _kw("测试"),
        _kw("销售"),
        _kw("市场"),
        _kw("财务"),
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

        desc = (post.get("description") or "").strip()
        req = (post.get("requirement") or "").strip()
        summary = (desc + ("　【职位要求】" + req if req else "")).strip() or None
        jd_url = self.detail_template.format(id=pid)
        return RawJob(
            company="字节跳动",
            title=title,
            location=city or None,
            job_type=self.recruit_type or job_type or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )


class BytedanceCampusAdapter(BytedanceAdapter):
    """字节跳动校招 / 实习 — jobs.bytedance.com/campus。

    与社招（/experienced）同一飞书系平台、同一拦截接口 /api/v1/search/job/posts，
    仅列表/详情路径换成 /campus。全部为校招/实习：job_type 直给"校招"，其中的实习岗由读取端
    "标题实习"信号盖成实习（recruitmentCategory 层1 优先于校招）。
    """

    name = "bytedance_campus"
    recruit_type = "校招"
    detail_template = "https://jobs.bytedance.com/campus/position/{id}/detail"
    list_urls = [
        _campus_kw("算法"),
        _campus_kw("研发"),
        _campus_kw("产品"),
        _campus_kw("实习"),
        _campus_kw("数据"),
        _campus_kw("设计"),
        _campus_kw("运营"),
        "https://jobs.bytedance.com/campus/position",
    ]
