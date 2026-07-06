"""腾讯音乐（TME）自建招聘门户适配器（零登录、零浏览器）。

join.tencentmusic.com 是 Nuxt SSR+SPA，但岗位数据走公开 JSON 接口（2026-07-06 live 验证）：
  - 社招：POST /api/job/list（_meta.total_count 分页，ss 实测 100 可用）
  - 校招/实习/技术大咖：POST /api/uc-job/list（同分页口径）
逐岗详情页为 SSR 直出正文：/social|campus/post-details/?id={id}（两板块均 live 验证可渲染标题+JD）。
列表行自带 duty（岗位描述）作 summary，无需逐岗 detail。
"""
import json
from typing import List

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class TencentMusicAdapter(BaseAdapter):
    name = "tencent_music"
    company_name = "腾讯音乐 TME"

    SOCIAL_API = "https://join.tencentmusic.com/api/job/list"
    CAMPUS_API = "https://join.tencentmusic.com/api/uc-job/list"
    SOCIAL_DETAIL = "https://join.tencentmusic.com/social/post-details/?id={job_id}"
    CAMPUS_DETAIL = "https://join.tencentmusic.com/campus/post-details/?id={job_id}"
    PAGE_SIZE = 100
    MAX_PAGES = 30  # 100/页 → 封顶 3000 岗；当前社招 ~118 + 校招 ~129，余量充足

    def _fetch_board(self, client: httpx.Client, api: str, payload_base: dict) -> List[dict]:
        rows: List[dict] = []
        for page in range(1, self.MAX_PAGES + 1):
            payload = dict(payload_base, page=page, ss=self.PAGE_SIZE)
            resp = client.post(api, json=payload)
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
            items = data.get("items") or []
            if not items:
                break
            rows.extend(items)
            meta = data.get("_meta") or {}
            page_count = meta.get("page_count")
            if isinstance(page_count, int) and page >= page_count:
                break
            if len(items) < self.PAGE_SIZE:
                break
        return rows

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://join.tencentmusic.com/social",
            "Origin": "https://join.tencentmusic.com",
        }
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            social = self._fetch_board(client, self.SOCIAL_API, {
                "job_class": [], "work_city": "", "setid": "", "deptids": "",
                "keyword": "", "order_by": "is_recommend",
            })
            campus = self._fetch_board(client, self.CAMPUS_API, {
                "keyword": "", "work_city": "", "zp_type": "", "job_class": [],
            })
        if not social and not campus:
            raise RuntimeError("tencent_music: empty job/list + uc-job/list response")
        return json.dumps({"social": social, "campus": campus}, ensure_ascii=False)

    def _map_row(self, row: dict, board: str) -> RawJob:
        job_id = str(row.get("id") or "").strip()
        title = str(row.get("name") or "").strip()
        if not (job_id and title):
            return None
        detail = self.SOCIAL_DETAIL if board == "social" else self.CAMPUS_DETAIL
        jd_url = detail.format(job_id=job_id)
        if board == "social":
            job_type = "社招"
        else:
            # 校招板块自报家门（uc_type：应届生/实习生/日常实习生/技术大咖）；
            # 「技术大咖」非招聘类型词 → normalizer 退回正文推断，不误标校招。
            job_type = str(row.get("job_type_descr") or "").strip() or "校招"
        summary = str(row.get("duty") or "").strip() or None
        return RawJob(
            company=self.company_name,
            title=title,
            location=str(row.get("work_city") or "").strip() or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.coerce_iso_date(row.get("date")),
        )

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        seen = set()
        for board in ("social", "campus"):
            for row in data.get(board) or []:
                if not isinstance(row, dict):
                    continue
                job = self._map_row(row, board)
                if job is None or job.jd_url in seen:
                    continue
                seen.add(job.jd_url)
                jobs.append(job)
        return jobs
