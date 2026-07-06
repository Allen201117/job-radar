"""蚂蚁集团自建招聘门户适配器（零登录、零浏览器）。

talent.antgroup.com 是 UMI SPA，岗位数据走 hrcareersweb.antgroup.com 公开 JSON 接口
（2026-07-06 live 验证，无 ctoken/cookie 也放行）：
  - 社招：POST /api/social/position/search（channel=group_official_site，totalCount 分页）
  - 校招/实习：POST /api/campus/position/search（channel=campus_group_official_site）
pageSize 实测 ≤30 稳定（50 返回空）。列表行自带 description+requirement 作 summary。
逐岗详情页（live 验证可渲染标题+JD）：
  - 社招：talent.antgroup.com/off-campus-position?positionId={id}
  - 校招：talent.antgroup.com/campus-position?positionId={id}
⚠️ source_url 必须用根路径 https://talent.antgroup.com/（迁移 175）：社招详情页与列表页
/off-campus-position 同 host+path、仅差 ?positionId=，normalizer _url_key 忽略 query →
用列表页作 source_url 会把全部社招岗误判「jd_url equals source url」拦掉。
"""
import json
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class AntGroupAdapter(BaseAdapter):
    name = "antgroup"
    company_name = "蚂蚁集团"

    API = "https://hrcareersweb.antgroup.com/api/{board}/position/search"
    SOCIAL_DETAIL = "https://talent.antgroup.com/off-campus-position?positionId={job_id}"
    CAMPUS_DETAIL = "https://talent.antgroup.com/campus-position?positionId={job_id}"
    PAGE_SIZE = 30  # 接口 live 实测：30 稳定返回，50 返回空
    MAX_PAGES = 80  # 30/页 → 封顶 2400 岗；当前社招 ~947 + 校招 ~328，余量充足

    _BOARDS = (
        ("social", "group_official_site"),
        ("campus", "campus_group_official_site"),
    )

    def _fetch_board(self, client: httpx.Client, board: str, channel: str) -> List[dict]:
        rows: List[dict] = []
        total: Optional[int] = None
        for page in range(1, self.MAX_PAGES + 1):
            payload = {
                "key": "", "regions": "", "categories": "", "subCategories": "",
                "bgCode": "", "socialQrCode": "",
                "pageIndex": page, "pageSize": self.PAGE_SIZE,
                "channel": channel, "language": "zh",
            }
            resp = client.post(self.API.format(board=board), json=payload)
            resp.raise_for_status()
            data = resp.json() or {}
            chunk = data.get("content") or []
            if not chunk:
                break
            rows.extend(chunk)
            if total is None:
                total = data.get("totalCount")
            if isinstance(total, int) and len(rows) >= total:
                break
            if len(chunk) < self.PAGE_SIZE:
                break
        return rows

    def fetch(self, source_url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://talent.antgroup.com/",
            "Origin": "https://talent.antgroup.com",
        }
        out = {}
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for board, channel in self._BOARDS:
                out[board] = self._fetch_board(client, board, channel)
        if not any(out.values()):
            raise RuntimeError("antgroup: empty position/search response")
        return json.dumps(out, ensure_ascii=False)

    @staticmethod
    def _experience_text(row: dict) -> Optional[str]:
        exp = row.get("experience")
        if not isinstance(exp, dict):
            return None
        low, high = exp.get("from"), exp.get("to")
        if isinstance(low, int) and isinstance(high, int):
            return f"{low}-{high}年"
        if isinstance(low, int) and low > 0:
            return f"{low}年以上"
        return None

    def _map_row(self, row: dict, board: str) -> Optional[RawJob]:
        job_id = str(row.get("id") or "").strip()
        title = str(row.get("name") or "").strip()
        if not (job_id and title):
            return None
        detail = self.SOCIAL_DETAIL if board == "social" else self.CAMPUS_DETAIL
        jd_url = detail.format(job_id=job_id)
        locations = [str(c).strip() for c in (row.get("workLocations") or []) if str(c).strip()]
        description = str(row.get("description") or "").strip()
        requirement = str(row.get("requirement") or "").strip()
        summary = (
            description + ("\n【任职要求】\n" + requirement if requirement else "")
        ).strip() or None
        if board == "social":
            job_type = "社招"
        else:
            job_type = "实习" if "实习" in title else "校招"
        return RawJob(
            company=self.company_name,
            title=title,
            location="、".join(dict.fromkeys(locations)) or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(row),
            experience=self._experience_text(row),
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
