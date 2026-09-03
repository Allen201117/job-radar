"""哔哩哔哩**校园招聘**（jobs.bilibili.com/campus）适配器 —— 零登录、零浏览器。

⚠️ 校招和社招是**两条独立的 API**，别指望给社招接口传个参数就能拿到校招：
- 社招 `POST /api/srs/position/positionList`（adapters/bilibili.py）——行里 `recruitType` 恒为 0，
  传 `recruitType=1/2` 一律返回 `total=0`。2026-09-03 曾据此判「B站校招没开」，**是错的**：
  首页当时就挂着「哔哩哔哩2027届秋季校园招聘正式启动」，只是入口在另一条 API 上。
- 校招 `POST /api/campus/position/positionList`（本文件）——2026-09-04 live 实测
  校招 91 岗 + 实习 281 岗，且列表直接带 `positionDescription` 全文正文。

## 会话
先 `GET /api/auth/v1/csrf/token` 拿匿名 token（`data` 就是 token 字符串），随后每个 POST 带
`X-CSRF`。固定头 `X-AppKey: ops.ehr-api.auth` / `X-UserType: 2`；`X-UserType=1` 直接返 code=-101。
`X-Channel` 实测被忽略（campus/social/school 返回相同结果），仍按页面原样传 campus。

## 两个桶必须分别取
`positionTypeList` / `workTypeList` 的枚举来自站点 JS：**Freshmen="3"（校招）、Intern="0"（实习）**。
⚠️ **不传这两个字段拿到的不是并集**（live: 不传 total=100，而 3→91、0→281）——必须两个桶分别翻，
按 id 去重合并，否则会漏掉一大半实习岗。

## 逐岗 jd_url
`https://jobs.bilibili.com/campus/positions/{id}`（id = 列表行的 `id`）。
2026-09-04 用 id=29738 live 核过：页面渲染的正是该岗（标题/正文/网申截止日期都对得上）。
"""
import json
import time
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class BilibiliCampusAdapter(BaseAdapter):
    name = "bilibili_campus"
    company_name = "哔哩哔哩"

    CSRF_URL = "https://jobs.bilibili.com/api/auth/v1/csrf/token"
    LIST_URL = "https://jobs.bilibili.com/api/campus/position/positionList"
    DETAIL_URL = "https://jobs.bilibili.com/campus/positions/{job_id}"
    official_hosts = ("jobs.bilibili.com",)
    PAGE_SIZE = 50
    MAX_PAGES = 40
    # (枚举值, 桶名)：站点 JS 的 Freshmen="3" / Intern="0"，见文件头「两个桶必须分别取」。
    BUCKETS = (("3", "校园招聘"), ("0", "实习"))

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-AppKey": "ops.ehr-api.auth",
            "X-UserType": "2",
            "X-Channel": "campus",
            "Referer": "https://jobs.bilibili.com/campus/positions",
            "Lunar-Id": f"lunar-{int(time.time() * 1000)}-job-radar",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        rows: List[dict] = []
        seen: set = set()
        bucket_totals: List[int] = []
        buckets_drained: List[bool] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:
            csrf_response = client.get(self.CSRF_URL)
            csrf_response.raise_for_status()
            csrf = str((csrf_response.json() or {}).get("data") or "").strip()
            if not csrf:
                raise RuntimeError("bilibili_campus: anonymous CSRF token unavailable")
            auth = {"X-CSRF": csrf}
            for type_value, bucket_name in self.BUCKETS:
                total, got = None, 0
                for page_no in range(1, self.MAX_PAGES + 1):
                    payload = {
                        "pageNum": page_no, "pageSize": self.PAGE_SIZE,
                        "recruitType": 1,
                        "positionTypeList": [type_value], "workTypeList": [type_value],
                        "positionName": "", "postCodeList": [], "workLocationList": [],
                    }
                    try:
                        response = client.post(self.LIST_URL, json=payload, headers=auth)
                        response.raise_for_status()
                        body = response.json() or {}
                    except (httpx.HTTPError, ValueError):
                        break
                    if body.get("code") != 0:
                        break
                    data = body.get("data") or {}
                    if total is None:
                        total = _int_or_none(data.get("total"))
                    page_rows = data.get("list") or []
                    if not page_rows:
                        break
                    fresh = 0
                    for row in page_rows:
                        key = str(row.get("id") or "")
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        row["_bucket"] = bucket_name
                        rows.append(row)
                        fresh += 1
                    got += len(page_rows)
                    if total is not None and got >= total:
                        break
                    # 末页判据看「这一页有没有带来新岗」，不看页长——短页（限流/抖动）不该收工。
                    if not fresh:
                        break
                if total is not None:
                    bucket_totals.append(total)
                    buckets_drained.append(got >= total)
                else:
                    buckets_drained.append(False)   # 连总数都没拿到 → 本桶不算抓全
        if not rows:
            raise RuntimeError("bilibili_campus: empty campus positionList")
        # 分母 = 两个桶自报之和，且**两个桶都翻干净**才算抓全（任一桶半途而废都不许标 complete）。
        if len(bucket_totals) == len(self.BUCKETS):
            self.reported_total = sum(bucket_totals)
        self.fetch_complete = bool(buckets_drained) and all(buckets_drained)
        return json.dumps({"list": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("positionName") or "").strip()
            if not job_id or not title:
                continue
            location = str(row.get("workLocation") or row.get("workCity") or "").strip()
            if location and not is_china_company_location(location):
                continue
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            summary = str(row.get("positionDescription") or "").strip() or None
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location or None,
                # 三桶分类靠库里的触发器判，这里只如实给「全职/实习」这类岗位性质。
                job_type=str(row.get("positionTypeName") or row.get("_bucket") or "").strip() or None,
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=str(row.get("pushTime") or "").strip() or None,
            ))
        return jobs
