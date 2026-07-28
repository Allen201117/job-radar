import json
import re
from typing import List

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all


class BaiduAdapter(BaseAdapter):
    """
    百度招聘 — talent.baidu.com

    百度招聘页面服务端渲染 `window.__INITIAL_DATA__`，列表项里的
    postId 与官方点击逻辑共同构成公开详情页 URL：
    /jobs/detail/{recruitType}/{postId}
    """

    name = "baidu"
    DEFAULT_URL = "https://talent.baidu.com/jobs/social-list"
    # recruitType 是百度自带的**招聘类型**（拼详情 URL 也用它），比 postType(岗位类别)可靠。
    _RECRUIT_TYPE = {"SOCIAL": "社招", "CAMPUS": "校招", "INTERN": "实习"}

    # 列表接口（2026-07-28 live 探到）：**form-encoded** POST，JSON body 会被拒
    # （"Illegal argument : recruitType"）。pageSize 被服务端锁死为 10——传 50/100/200 一律返回 0 条，
    # 所以只能 10 条一页翻。curPage 从 1 递增，实测页间零重叠、翻到 total 自然收尾。
    LIST_API = "https://talent.baidu.com/httservice/getPostListNew"
    PAGE_SIZE = 10
    MAX_PAGES = 400          # 安全上限：社招 1571 岗 ≈ 158 页，留足余量
    RECRUIT_TYPES = ("SOCIAL", "CAMPUS", "INTERN")

    def fetch(self, source_url: str) -> str:
        """翻全百度三类招聘（社招/校招/实习）的列表接口，返回统一 JSON 信封。

        旧实现只 GET 一次 SSR 列表页，`__INITIAL_DATA__` 里只带首页 10 条——而接口自报
        社招就有 1571 条（实习 415），即每轮只抓到 0.6%，库里存量因此几乎永不刷新
        （2026-07-28 实测 baidu 源 3 天刷新率 24%）。URL 上加 pageNum/page/curPage 都无效
        （SSR 页恒返第 1 页），真正的翻页在这个 XHR 接口上。
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Referer": source_url or self.DEFAULT_URL,
        }
        rows: List[dict] = []
        totals: List[int] = []
        complete_all = True

        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for recruit_type in self.RECRUIT_TYPES:
                def fetch_page(page: int, rt: str = recruit_type) -> PageResult:
                    resp = client.post(self.LIST_API, data={
                        "recruitType": rt, "pageSize": self.PAGE_SIZE, "curPage": page})
                    resp.raise_for_status()
                    data = (resp.json() or {}).get("data") or {}
                    items = data.get("list") or []
                    # 列表行自己不带 recruitType，但拼详情 URL 要用它 → 按本次请求的类型盖上。
                    for item in items:
                        if isinstance(item, dict):
                            item.setdefault("recruitType", rt)
                    total = data.get("total")
                    return PageResult(items=items, total=total if isinstance(total, int) else None)

                got, total, complete = paginate_all(
                    fetch_page,
                    page_size=self.PAGE_SIZE,
                    first_page=1,
                    max_pages=self.MAX_PAGES,
                    delay_seconds=0.1,
                    label=f"baidu:{recruit_type}",
                )
                rows.extend(got)
                if total is not None:
                    totals.append(total)
                complete_all = complete_all and complete

        self.reported_total = sum(totals) if totals else None
        self.fetch_complete = complete_all
        return json.dumps({"_rows": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        """解析返回内容。"""
        jobs = []

        # 尝试 JSON 解析
        try:
            data = json.loads(html)
            # fetch() 的信封：已翻全的列表行，与 __INITIAL_DATA__ 行同构 → 走同一套映射。
            if isinstance(data, dict) and "_rows" in data:
                return self._rows_to_jobs(data.get("_rows") or [], "SOCIAL")
            rows = (
                data.get("data", {}).get("list", [])
                or data.get("data", {}).get("records", [])
                or data.get("result", {}).get("items", [])
                or []
            )
            for row in rows:
                jobs.append(
                    RawJob(
                        company="百度",
                        title=row.get("title") or row.get("jobName") or row.get("name", ""),
                        location=row.get("location") or row.get("city") or row.get("workCity"),
                        job_type=row.get("jobType") or row.get("recruitType"),
                        summary=row.get("description") or row.get("jobDesc", ""),
                        jd_url=row.get("url") or row.get("jobUrl") or "",
                        posted_at=row.get("publishTime") or row.get("createTime"),
                    )
                )
            return jobs
        except (json.JSONDecodeError, TypeError):
            pass

        jobs.extend(self._parse_initial_data(html))

        return jobs

    def _parse_initial_data(self, html: str) -> List[RawJob]:
        match = re.search(
            r"window\.__INITIAL_DATA__\s*=(.*?);\s*window\.prefix",
            html,
            re.S,
        )
        if not match:
            return []

        raw = match.group(1).strip()
        raw = re.sub(r"(?<=[:\[,])\s*undefined\s*(?=[,}\]])", "null", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        list_data = data.get("listData") or {}
        return self._rows_to_jobs(
            list_data.get("listDetailData") or [],
            list_data.get("recruitType") or "SOCIAL",
        )

    def _rows_to_jobs(self, rows: List[dict], default_recruit_type: str) -> List[RawJob]:
        """列表行 → RawJob。SSR 的 listDetailData 与列表接口的 data.list 同构，共用这一份映射。"""
        jobs: List[RawJob] = []
        for row in rows:
            post_id = row.get("postId")
            title = row.get("name")
            if not post_id or not title:
                continue

            row_recruit_type = row.get("recruitType") or default_recruit_type
            jd_url = f"https://talent.baidu.com/jobs/detail/{row_recruit_type}/{post_id}"
            jobs.append(
                RawJob(
                    company="百度",
                    title=title,
                    location=row.get("workPlace"),
                    # 招聘类型优先用来源 recruitType 映射（社招/校招/实习），postType 只是岗位类别兜底。
                    job_type=self._RECRUIT_TYPE.get(str(row_recruit_type).upper())
                    or row.get("postType")
                    or row.get("projectType"),
                    summary=row.get("workContent") or row.get("serviceCondition"),
                    jd_url=jd_url,
                    apply_url=jd_url,
                    posted_at=row.get("updateDate") or row.get("publishDate"),
                )
            )
        return jobs
