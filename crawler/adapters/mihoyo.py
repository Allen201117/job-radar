"""米哈游自建招聘门户适配器（零登录、零浏览器）。

jobs.mihoyo.com 是 UMI/React 空壳 SPA，岗位数据走 ats.openout.mihoyo.com 公开 JSON 接口
（2026-07-06 live 验证，无 cookie 也放行）：
  - 列表：POST /ats-portal/v1/job/list {channelDetailIds:[1], hireType:N}。
    ⚠️ hireType 0=社招（live 实测 597，projectName 全为「社会招聘」）、1=校招/实习（153，
    「2027届秋招/实习生专项」，与社招 id 完全不相交）——不是「0=全部」，两个都要抓。
    total 分页，pageSize 实测 100 可用。
  - 详情：POST /ats-portal/v1/job/info {id, channelDetailIds:[1]} → description+jobRequire（列表行
    jobSummary 常为空，JD 正文靠它逐岗补，httpx 并发、无浏览器；社招/校招 id 均可查）。
逐岗详情页为 hash 路由 SPA（live 验证可渲染标题+JD）：
  - 社招（hireType 0）：jobs.mihoyo.com/#/position/{id}
  - 校招/实习（hireType 1）：jobs.mihoyo.com/#/campus/position/{id}
岗位含新加坡/美国/日本等海外地点，交由 normalizer/geo 按 sources.regions 门控。
"""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_detail_cap


class MihoyoAdapter(BaseAdapter):
    name = "mihoyo"
    company_name = "米哈游 miHoYo"

    LIST_API = "https://ats.openout.mihoyo.com/ats-portal/v1/job/list"
    INFO_API = "https://ats.openout.mihoyo.com/ats-portal/v1/job/info"
    SOCIAL_DETAIL = "https://jobs.mihoyo.com/#/position/{job_id}"
    CAMPUS_DETAIL = "https://jobs.mihoyo.com/#/campus/position/{job_id}"
    PAGE_SIZE = 100
    MAX_PAGES = 20        # 100/页 → 封顶 2000 岗；当前全量 ~600，余量充足
    DETAIL_CAP = 3000     # v1/job/info 是公开 httpx 接口 → 默认全量逐岗补 JD 正文
    DETAIL_WORKERS = 6    # 单 host 并发上限：礼貌 + 防限流

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://jobs.mihoyo.com/",
            "Origin": "https://jobs.mihoyo.com",
        }

    def _fetch_info(self, client: httpx.Client, job_id: str) -> Optional[dict]:
        try:
            resp = client.post(self.INFO_API, json={"id": job_id, "channelDetailIds": [1]})
            resp.raise_for_status()
            data = (resp.json() or {}).get("data")
            return data if isinstance(data, dict) else None
        except Exception:
            return None  # 单岗详情失败不拖垮整源；该岗留薄卡由 enrich 兜底

    def _fetch_board(self, client: httpx.Client, hire_type: int, board: str) -> List[dict]:
        rows: List[dict] = []
        total: Optional[int] = None
        for page in range(1, self.MAX_PAGES + 1):
            payload = {"pageNo": page, "pageSize": self.PAGE_SIZE,
                       "channelDetailIds": [1], "hireType": hire_type}
            resp = client.post(self.LIST_API, json=payload)
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
            chunk = data.get("list") or []
            if not chunk:
                break
            for row in chunk:
                if isinstance(row, dict):
                    row["_board"] = board
            rows.extend(chunk)
            if total is None:
                total = data.get("total")
            if isinstance(total, int) and len(rows) >= total:
                break
            if len(chunk) < self.PAGE_SIZE:
                break
        return rows

    def fetch(self, source_url: str) -> str:
        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers=self._headers()) as client:
            rows = (self._fetch_board(client, 0, "social")
                    + self._fetch_board(client, 1, "campus"))
            if not rows:
                raise RuntimeError("mihoyo: empty v1/job/list response")

            # 逐岗补 JD 正文（列表 jobSummary 常为空；info 给 description+jobRequire）
            cap = resolve_detail_cap(self.DETAIL_CAP)
            targets = [r for r in rows if isinstance(r, dict) and r.get("id")][:cap]
            if targets:
                with ThreadPoolExecutor(max_workers=self.DETAIL_WORKERS) as pool:
                    infos = list(pool.map(
                        lambda r: self._fetch_info(client, str(r["id"])), targets))
                for row, info in zip(targets, infos):
                    if info:
                        row["_info"] = info
        return json.dumps({"list": rows}, ensure_ascii=False)

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        info = row.get("_info") or {}
        description = str(info.get("description") or "").strip()
        require = str(info.get("jobRequire") or "").strip()
        if description or require:
            return (description + ("\n【任职要求】\n" + require if require else "")).strip()
        return str(row.get("jobSummary") or "").strip() or None

    def _map_row(self, row: dict) -> Optional[RawJob]:
        job_id = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not (job_id and title):
            return None
        project = str(row.get("projectName") or "").strip()
        nature = str(row.get("jobNature") or "").strip()
        is_social = row.get("_board") != "campus"
        detail = self.SOCIAL_DETAIL if is_social else self.CAMPUS_DETAIL
        if is_social:
            job_type = "社招"
        elif "实习" in project or "实习" in nature or "实习" in title:
            job_type = "实习"  # 实习生专项等
        else:
            job_type = "校招"  # 校招项目（2027届秋招等）
        addresses = [
            str(a.get("addressDetail") or "").strip()
            for a in (row.get("addressDetailList") or []) if isinstance(a, dict)
        ]
        locations = [a for a in addresses if a]
        return RawJob(
            company=self.company_name,
            title=title,
            location="、".join(dict.fromkeys(locations)) or None,
            job_type=job_type,
            summary=self._summary_of(row),
            jd_url=detail.format(job_id=job_id),
            apply_url=detail.format(job_id=job_id),
            posted_at=None,  # 接口无发布时间字段
        )

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            job = self._map_row(row)
            if job is None or job.jd_url in seen:
                continue
            seen.add(job.jd_url)
            jobs.append(job)
        return jobs
