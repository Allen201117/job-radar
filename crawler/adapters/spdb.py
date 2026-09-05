"""上海浦东发展银行（浦发银行）自建招聘门户适配器（纯 httpx、零鉴权）。

2026-09-05 live 核实的三件事：
  1. 列表接口 POST /socialJobJsonList **必须带 Referer**，否则返回 HTTP 500 +
     {"message":"Referer error"}。这不是反爬拦截、只是站点自己的防盗链，带上即通。
  2. `pageSize` 参数**不生效**（服务端恒返 10 条/页），所以翻页只能按 pageNo 一页页翻，
     以接口自报的 `totalRowCount` 收尾。
  3. 社招与校招是**同一个列表接口**，靠行内的 `recuitType` 区分（11=社招 / 12=校招），
     而逐岗详情 URL 的 `type` 必须与之对应（1=社招 / 2=校招）——用错 type 打不开。

正文只在详情页（列表 JSON 一个字都不带），故逐岗 GET /jobDetail 抓 summary。
不存在的 jobId 会返回 HTTP 200 + 「500 您访问的页面出错了！」骨架页，
所以判「这条详情有没有内容」只能看正文区块，不能看状态码。
"""
import json
import re
from typing import List, Optional

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap
from .cn_portal_tls import make_transport


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class SpdbAdapter(BaseAdapter):
    name = "spdb"

    LIST_API = "https://job.spdb.com.cn/socialJobJsonList"
    LIST_REFERER = "https://job.spdb.com.cn/socialJob"
    DETAIL_URL = "https://job.spdb.com.cn/jobDetail?jobId={job_id}&type={type_code}"
    PAGE_SIZE = 10          # 服务端硬定 10 条/页，pageSize 参数无效（2026-09-05 live 实测）
    MAX_PAGES = 200
    _DETAIL_CAP = 250

    # 详情页正文夹在「返回列表」导航与页脚版权之间；两个锚点都是站点模板固定文案。
    _BODY_START = "返回列表"
    _BODY_END = "All rights reserved"

    @classmethod
    def _detail_body(cls, html: str) -> str:
        tree = HTMLParser(html or "")
        for node in tree.css("script,style,noscript"):
            node.decompose()
        text = re.sub(r"\s+", " ", tree.body.text() if tree.body else "")
        start = text.find(cls._BODY_START)
        end = text.find(cls._BODY_END)
        if start < 0 or end <= start:
            return ""
        return text[start + len(cls._BODY_START):end].strip()

    @staticmethod
    def _type_code(row: dict) -> int:
        """recuitType 11=社招 → type=1；12=校招 → type=2。未知值按社招兜底。"""
        return 2 if str((row or {}).get("recuitType") or "").strip() == "12" else 1

    @classmethod
    def _summary_of(cls, row: dict, title: str) -> Optional[str]:
        body = _clean(row.get("_detail_body"))
        if not body:
            return None
        # 正文开头会重复「岗位名 部门名 招聘类别：…」这一段元信息，去掉标题前缀更干净。
        if title and body.startswith(title):
            body = body[len(title):].strip()
        return body or None

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Referer": self.LIST_REFERER,   # 缺它整个列表接口 500，见模块 docstring
        }
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers,
                          transport=make_transport()) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.post(self.LIST_API, data={"pageNo": page})
                response.raise_for_status()
                payload = response.json() or {}
                rows = payload.get("rows")
                if not isinstance(rows, list):
                    raise RuntimeError("spdb: socialJobJsonList rows is not a list")
                return PageResult(items=rows, total=_int_or_none(payload.get("totalRowCount")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="spdb",
            )
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in rows[:cap] if cap else []:
                job_id = str((row or {}).get("openningJobId") or "").strip()
                if not job_id:
                    continue
                try:
                    response = client.get(self.DETAIL_URL.format(
                        job_id=job_id, type_code=self._type_code(row)))
                    response.raise_for_status()
                    row["_detail_body"] = self._detail_body(response.text)
                except httpx.HTTPError:
                    continue
        if not rows:
            raise RuntimeError("spdb: socialJobJsonList returned no jobs")
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("openningJobId") or "").strip()
            title = _clean(row.get("positionName") or row.get("posnDescr"))
            if not (job_id and title):
                continue
            jd_url = self.DETAIL_URL.format(job_id=job_id, type_code=self._type_code(row))
            deadline = _clean(row.get("closeDt"))
            jobs.append(RawJob(
                company="", title=title,
                location=_clean(row.get("prmLocArea") or row.get("address")) or None,
                job_type="校招" if self._type_code(row) == 2 else "社招",
                summary=self._summary_of(row, title),
                jd_url=jd_url, apply_url=jd_url,
                posted_at=_clean(row.get("desiredStartDt")) or None,
                # 常青岗写的是 2100-12-31 这种哨兵值，当成「无截止」不往下游传。
                deadline=None if deadline.startswith("2100") else (deadline or None),
                education=_clean(row.get("hpsDegreeRql")) or None,
            ))
        return jobs
