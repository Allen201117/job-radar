"""顺丰官方社会招聘公开接口适配器（零登录、零浏览器）。"""
import json
import logging
import time
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_page_cap
from .china_location import is_china_company_location

logger = logging.getLogger(__name__)


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_numbers(total_pages: int, max_pages: int) -> List[int]:
    """Return one-based pages bounded by a defensive hard cap."""
    last_page = min(max(1, total_pages), max(1, max_pages))
    return list(range(1, last_page + 1))


class SfExpressAdapter(BaseAdapter):
    name = "sf_express"
    company_name = "顺丰"

    API_URL = "https://hr.sf-express.com/SearchJob.do"
    DETAIL_URL = "https://hr.sf-express.com/JobSearchById/{job_id},{position_type}"
    # 页数上限只作「防死循环」兜底，真正收尾靠接口自报的 totalPage（见 fetch）。
    # 旧的硬编码 50 页 × 10 条/页 = 500 条：顺丰自报 2,184 岗时只抓到 498，status 还是 success
    # （2026-09-04 crawl_runs 实测）。现按 CRAWL_MAX_JOBS 换算，与其它源同一个旋钮。
    MAX_PAGES = None
    _short_pages: List[tuple] = []
    PAGE_RETRIES = 4
    PAGE_RETRY_DELAY = 0.75
    # 翻 200+ 页会被顺丰按量限流（CI 上第 43 页就开始返 listObj=None）。每页之间歇一下，
    # 换来的是「一轮抓全 2,164 个岗」而不是「抓 420 个然后被限流踢出去」。
    # 200 页 × 0.35s ≈ 70s，在 daily 快档 50min 预算里可以忽略。
    PAGE_DELAY = 0.35

    def should_skip(self, source_url: str) -> Optional[str]:
        return None

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://hr.sf-express.com/jobMainHandler/main/9999",
            "Origin": "https://hr.sf-express.com",
        }

    @staticmethod
    def _payload(page_number: int) -> dict:
        return {
            "workAddress": "",
            "currentPage": page_number,
            "outName": "",
            "category": "",
            "identification": "",
        }

    def _fetch_page(
        self,
        client: httpx.Client,
        page_number: int,
        expected_rows: Optional[int] = None,
    ) -> dict:
        """抓一页；短页会重试 PAGE_RETRIES 次（治接口偶发抖动）。

        ⚠️ 重试用尽后**返回拿到的那一页，不抛异常**。旧实现在这里 raise，后果是
        「最后一页少 2 条 → 整个源 2,164 个岗全部丢掉」：expected_rows 是拿**首页**读到的
        totalResult 算出来的，而翻 217 页要几分钟，期间顺丰上下架会让真实总数漂移，
        末页实际条数必然可能小于当初的算术预期（2026-09-04 实测 page 217 expected 6 got 4，
        整源直接 failed）。少抓几条是「没抓全」，交给 fetch_complete 如实记录即可；
        把整源炸掉是把 2,164 个在招岗一起扔了，两者代价差三个数量级。
        真正一条都没拿到（listObj 不是 list）时才抛——那是接口坏了，不是短页。
        """
        last_data = None
        last_count = None
        for attempt in range(self.PAGE_RETRIES):
            response = client.post(self.API_URL, json=self._payload(page_number))
            response.raise_for_status()
            data = (response.json() or {}).get("JobSearchList") or {}
            rows = data.get("listObj")
            if isinstance(rows, list):
                last_data = data
                last_count = len(rows)
                if expected_rows is None or last_count >= expected_rows:
                    return data
            if attempt + 1 < self.PAGE_RETRIES:
                time.sleep(
                    self.PAGE_RETRY_DELAY * (attempt + 1)
                    + (page_number % 3) * 0.1
                )
        if last_data is not None:
            self._short_pages.append((page_number, last_count, expected_rows))
            return last_data
        raise RuntimeError(
            f"sf_express: invalid SearchJob page {page_number}; "
            f"expected {expected_rows}, got {last_count}"
        )

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        self._short_pages = []   # [(页号, 实际条数, 预期条数)]，重试用尽仍短的页；只用于诚实记账
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            first_page = self._fetch_page(client, 1)
            total_pages = int(first_page.get("totalPage") or 1)
            total_result = _int_or_none(first_page.get("totalResult"))
            if total_result is not None:
                self.reported_total = total_result
            page_size = int(first_page.get("showCount") or len(first_page.get("listObj") or []))
            max_pages = self.MAX_PAGES or resolve_page_cap(max(1, page_size))
            pages = _page_numbers(total_pages, max_pages)
            rows = list(first_page.get("listObj") or [])

            remaining = pages[1:]
            for page_number in remaining:
                expected_rows = page_size
                if total_result:
                    expected_rows = min(
                        page_size,
                        max(0, total_result - (page_number - 1) * page_size),
                    )
                # 「尽力而为」翻页（与 base.paginate_all 同口径）：首页失败才上抛记 failed，
                # 后续页失败 → 保留已抓到的，停止，让 fetch_complete 如实记「没抓全」。
                # 顺丰会按量限流：本机顺畅翻完 217 页，CI 上（共享出口 IP + 与其它源并发）
                # 第 43 页就开始返 listObj=None。旧写法在这里 raise → 整源 failed、
                # 已经抓到的 420 个在招岗一起丢掉，下一轮 HEAD 预检还会因为刚被限流而 skip，
                # 于是顺丰连着两条 crawl_run 一个岗都没入 —— 这正是 2026-09-04 线上实测到的。
                try:
                    page_data = self._fetch_page(
                        client,
                        page_number,
                        expected_rows=expected_rows,
                    )
                except RuntimeError:
                    self._short_pages.append((page_number, None, expected_rows))
                    break
                rows.extend(page_data.get("listObj") or [])
                if self.PAGE_DELAY:
                    time.sleep(self.PAGE_DELAY)

        rows_by_key = {}
        for row in rows:
            key = (
                str((row or {}).get("id") or "").strip(),
                str((row or {}).get("positionType") or "").strip(),
            )
            if all(key):
                rows_by_key[key] = row
        if not rows_by_key:
            raise RuntimeError("sf_express: empty SearchJob response")
        # 抓全 = 拿到自报总数那么多条。末页短一点（对方在我们翻页期间下架了岗）不算失败，
        # 只是 fetch_complete=False —— 诚实记账，不伪装成功也不把整源判死。
        self.fetch_complete = (
            self.reported_total is not None and len(rows_by_key) >= self.reported_total
        )
        if self._short_pages:
            logger.info("sf_express: %d 页重试后仍短（%s），按已抓到的 %d 条记账",
                        len(self._short_pages), self._short_pages[:3], len(rows_by_key))
        return json.dumps({"jobs": list(rows_by_key.values())}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            position_type = str(row.get("positionType") or "").strip()
            title = str(row.get("outName") or "").strip()
            location = str(row.get("workAddress") or "").strip()
            if not (
                job_id
                and position_type
                and title
                and is_china_company_location(location)
            ):
                continue

            duty = str(row.get("mainDuty") or "").strip()
            requirement = str(row.get("positionReq") or "").strip()
            summary = (
                duty + ("\n\n【岗位要求】\n" + requirement if requirement else "")
            ).strip() or None
            jd_url = self.DETAIL_URL.format(
                job_id=job_id,
                position_type=position_type,
            )
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type="社会招聘",
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                salary_text=(
                    str(row.get("salaryRangeTxt") or "").strip() or None
                ),
                posted_at=(
                    str(row.get("publishTime") or "")[:10] or None
                ),
                experience=(
                    str(row.get("workYearTxt") or "").strip() or None
                ),
                education=(
                    str(row.get("educationReqTxt") or "").strip() or None
                ),
            ))
        return jobs
