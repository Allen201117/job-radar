"""
海尔招聘 — maker.haier.net（公开 JSON 列表 + SSR 详情，纯 httpx 零浏览器）。

2026-07-16 live 重写（旧版对着入口页猜 JSON 嵌入/HTML 卡片，从未产出、源被禁用多时）：
- 列表：GET /client/job/searchdata.html?page={n}&pagesize=50 → {status:1, data:{count, list:[...]}}
  （浏览器抓包坐实的真实 XHR；count=在招总数，live 实测 636）。
- 详情：/client/job/detail.html?id={id} 是 SSR，正文在 div.cb-wordwrap（岗位职责/任职要求两段）；
  bogus id 也返回 200 但无标题正文，质量门（标题核验）能挡住。
- jd_url = detail.html?id={id}（逐岗稳定链接，live 验证 200）。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap

_LIST_API = "https://maker.haier.net/client/job/searchdata.html"
_DETAIL_URL = "https://maker.haier.net/client/job/detail.html?id={id}"
_PAGE_SIZE = 50


class HaierAdapter(BaseAdapter):
    name = "haier"
    max_pages = 60  # 50/页 → 3000 岗安全上限（live count 636）

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json",
                   "Referer": "https://maker.haier.net/client/job/index"}

        def fetch_page(page: int) -> PageResult:
            r = httpx.get(_LIST_API,
                          params={"page": page, "pagesize": _PAGE_SIZE, "key": "", "source": "", "core_job": ""},
                          headers=headers, timeout=self.timeout, follow_redirects=True)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            total = data.get("count")
            return PageResult(items=data.get("list") or [], total=total if isinstance(total, int) else None)

        rows, total, complete = paginate_all(
            fetch_page, page_size=_PAGE_SIZE, first_page=1,
            max_pages=self.max_pages, label="haier:maker.haier.net")
        self.reported_total = total
        self.fetch_complete = complete
        self._enrich_descriptions(rows, headers)
        return json.dumps({"list": rows}, ensure_ascii=False)

    _DETAIL_CAP = 300  # 逐岗 detail 补正文上限，防夜间全量被拖垮

    def _enrich_descriptions(self, rows: List[dict], headers: dict):
        """SSR 详情页 div.cb-wordwrap = 岗位职责/任职要求正文，拼接挂 row['_jd']；失败静默（薄卡入库不阻断）。"""
        from selectolax.parser import HTMLParser
        n = 0
        for row in rows:
            if n >= resolve_detail_cap(self._DETAIL_CAP):
                break
            jid = str(row.get("id") or "").strip()
            if not jid:
                continue
            try:
                r = httpx.get(_DETAIL_URL.format(id=jid), headers={**headers, "Accept": "text/html"},
                              timeout=self.timeout, follow_redirects=True)
                if r.status_code >= 300:
                    continue
                tree = HTMLParser(r.text)
                parts = [node.text(separator=" ", strip=True) for node in tree.css("div.cb-wordwrap")]
                body = "\n".join(x for x in parts if x)
                if body.strip():
                    row["_jd"] = body
                n += 1
            except Exception:
                continue

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("list") if isinstance(data, dict) else None
        out: List[RawJob] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            title = (row.get("job_name") or "").strip()
            jid = str(row.get("id") or "").strip()
            if not title or not jid:
                continue
            out.append(RawJob(
                company="海尔",
                title=title,
                location=(row.get("location") or "").strip() or None,
                job_type=None,  # 站点不区分板块；由 normalizer 从标题/正文推断
                summary=row.get("_jd"),
                jd_url=_DETAIL_URL.format(id=jid),
                apply_url=_DETAIL_URL.format(id=jid),
                salary_text=_salary_text(row),
                posted_at=(row.get("update_time") or "")[:10] or None,
            ))
        return out


def _salary_text(row: dict) -> Optional[str]:
    lo, hi = row.get("min_yearly_salary"), row.get("yearly_salary")
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if lo_f <= 0 or hi_f <= 0:
        return None
    return f"{lo_f:g}-{hi_f:g}万/年"
