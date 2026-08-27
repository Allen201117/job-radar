import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import List

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, RawJob


logger = logging.getLogger(__name__)


class JdAdapter(BaseAdapter):
    """
    京东招聘 — zhaopin.jd.com

    尝试京东社招 API + HTML 解析兜底。
    """

    name = "jd"
    LIST_PAGE_URL = "https://zhaopin.jd.com/web/job/job_info_list/3"
    API_URL = "https://zhaopin.jd.com/web/job/job_list"
    DETAIL_URL = "https://zhaopin.jd.com/web/job-info-detail"
    PAGE_SIZE = 100
    MAX_PAGES = 100
    PAGE_DELAY_SECONDS = 0.1

    def fetch(self, source_url: str) -> str:
        """Fetch the public JD social-recruitment list API.

        校招/实习在 campus.jd.com 独立门户，当前接口无 recruitType 参数，本 adapter 只抓社招。
        """
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://zhaopin.jd.com",
            "Referer": self.LIST_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        rows = []
        page = 1
        while True:
            if page > self.MAX_PAGES:
                logger.warning("jd: stopped at safety page cap %s", self.MAX_PAGES)
                self.reported_total = None
                self.fetch_complete = False
                break
            data = {
                "pageIndex": str(page),
                "pageSize": str(self.PAGE_SIZE),
                "workCityJson": "[]",
                "jobTypeJson": "[]",
                "jobSearch": "",
                "depTypeJson": "[]",
            }
            resp = httpx.post(
                self.API_URL,
                headers=headers,
                data=data,
                timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            payload = resp.json()
            page_rows = payload if isinstance(payload, list) else _find_job_list(payload)
            rows.extend(page_rows)
            if len(page_rows) < self.PAGE_SIZE:
                self.reported_total = len(rows)
                self.fetch_complete = True
                break
            page += 1
            time.sleep(self.PAGE_DELAY_SECONDS)
        return json.dumps(rows, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        jobs = []

        # 尝试提取嵌入的 JSON 数据
        try:
            data = json.loads(html)
            rows = data if isinstance(data, list) else _find_job_list(data)
            jobs = [_format_jd_job(row) for row in rows]
            return [job for job in jobs if job.title and job.jd_url]
        except (json.JSONDecodeError, TypeError):
            pass

        for match in re.finditer(
            r'(?:window\.__INITIAL_STATE__|window\.__NUXT__|window\.__DATA__)\s*=\s*(\{.+?\});',
            html,
            re.DOTALL,
        ):
            try:
                data = json.loads(match.group(1))
                # 递归查找 job list
                rows = _find_job_list(data)
                jobs.extend(_format_jd_job(row) for row in rows)
                if jobs:
                    return [job for job in jobs if job.title and job.jd_url]
            except (json.JSONDecodeError, TypeError):
                pass

        # HTML 解析兜底
        try:
            tree = HTMLParser(html)
            for card in tree.css(".job-card, .job-item, .position-item, li, tr"):
                title_el = card.css_first(".job-title, .title, h3, a, td")
                loc_el = card.css_first(".location, .city, .addr, td:nth-child(3)")
                link_el = card.css_first("a[href]")

                title = title_el.text(strip=True) if title_el else ""
                location = loc_el.text(strip=True) if loc_el else None
                jd_url = ""
                if link_el:
                    href = link_el.attrs.get("href", "")
                    if href and not href.startswith("http"):
                        href = "https://zhaopin.jd.com" + href
                    jd_url = href

                if title and len(title) > 2:
                    jobs.append(
                        RawJob(
                            company="京东",
                            title=title,
                            location=location,
                            jd_url=jd_url,
                        )
                    )
        except Exception:
            pass

        return jobs


# 京东列表行逐岗自报事业群名 positionDeptName，取值来自京东官方 BU 字典
# （POST /web/job/job_allparams 的 deptList，2026-08-27 live 核实共 10 个顶层事业群；
# 同批 1740 条列表里实际出现 9 个，且**永远是顶层名、不带下级路径**，兄弟字段
# positionDeptCode / positionDeptCodeFullpath 全为空串 → 只能按名字精确匹配）。
#
# 必投清单（lib/must-apply-list.json）把「京东科技」「京东物流」记成独立公司
# （pattern 分别是 %京东科技% / %京东物流%），而本 adapter 过去把 company 硬编码成「京东」，
# 于是这两家明明有在招岗却被算成覆盖缺口。这里按部门把它们派生出来：
# crawler/normalizer.normalize() 里是 `"company": raw.company or company`，
# 即 RawJob.company 非空时覆盖 sources.company，留空则回落 sources.company（「京东」）。
#
# ⚠️ 本设计成立的前提：「京东」在必投清单里是子串匹配 %京东%，而「京东科技」「京东物流」
# 都含「京东」二字 → 派生之后京东母公司**仍然算覆盖**，不会顾此失彼。
#
# 只映这两家、其余一律回落的理由：
#   - 「国际事业部」「探索研究院」（live 共 60 岗）不含「京东」二字，一旦派生反而会把这些岗
#     踢出京东的覆盖统计 —— 净亏，绝不派生。
#   - 京东零售 / 京东健康 / 京东工业 / 京东产发 / 京东集团 目前不在必投清单里，派生了换不来
#     任何覆盖收益，按最小改动留空回落；将来清单收录了，往下表加一行即可。
#   - ⚠️「京东方」(BOE) 是毫不相干的另一家公司（清单里独立一行 %京东方%），任何时候都不许派生到它。
# 新增映射前请先核对 lib/must-apply-list.json 里的写法，逐字一致，别凭印象编。
_DEPT_TO_COMPANY = {
    "京东科技": "京东科技",
    "京东物流": "京东物流",
}


def _derive_company(row: dict) -> str:
    """按列表行自报的事业群派生子公司归属；未知/缺失部门返回 "" 回落 sources.company。"""
    dept = (row.get("positionDeptName") or "").strip()
    return _DEPT_TO_COMPANY.get(dept, "")


def _format_jd_job(row: dict) -> RawJob:
    requirement_id = str(row.get("requirementId") or row.get("requementId") or "").strip()
    jd_url = f"{JdAdapter.DETAIL_URL}?requementId={requirement_id}" if requirement_id else ""
    work_content = row.get("workContent") or row.get("description") or row.get("jobDesc") or ""
    qualification = row.get("qualification") or ""
    summary = "\n".join(part for part in [work_content, qualification] if part)

    return RawJob(
        company=_derive_company(row),
        title=(
            row.get("positionNameOpen")
            or row.get("positionName")
            or row.get("title")
            or row.get("jobName")
            or row.get("name")
            or ""
        ),
        location=row.get("workCity") or row.get("location") or row.get("city") or row.get("workCityName"),
        # 本 adapter 只抓社招门户（校招/实习在 campus.jd.com 未接）；接口的 jobType 是职能分类
        # （运营类/研发类…）不是招聘类型，直接标「社招」保持 job_type 语义一致（与其它 adapter 同口径）。
        job_type="社招",
        summary=summary or None,
        jd_url=jd_url,
        apply_url=jd_url,
        posted_at=_format_posted_at(row),
    )


def _format_posted_at(row: dict):
    if row.get("formatPublishTime"):
        return row.get("formatPublishTime")

    value = row.get("publishTime") or row.get("createTime")
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    return value


def _find_job_list(obj, depth=0):
    """递归查找 job list。"""
    if depth > 5:
        return []
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("positionNameOpen", "requirementId", "title", "jobName", "name")):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _find_job_list(v, depth + 1)
            if result:
                return result
    if isinstance(obj, list):
        for item in obj:
            result = _find_job_list(item, depth + 1)
            if result:
                return result
    return []
