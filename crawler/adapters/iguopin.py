"""国聘（iguopin.com）通用企业岗位适配器，纯 httpx。

source_url 约定：``https://www.iguopin.com/job?company={公司全称的 URL 编码}``。
``company`` 只是本适配器读取的检索词（也兼容 ``keyword``），不是国聘列表页实际
查询串；fetch 会将它传给国聘公开搜索 API。一个源对应一个集团检索词，结果会保留
名称包含该词的在招单位/子公司岗位。

公开链路（2026-07-17 浏览器抓包验证）：
1. POST https://gp-api.iguopin.com/api/jobs/v1/recom-job
   {"search":{"page", "page_size", "keyword"}, "recom":{...}} -> data.list / data.total
2. GET https://gp-api.iguopin.com/api/jobs/v1/info?id={job_id} -> data.contents
3. 稳定单岗页 https://www.iguopin.com/job/detail?id={job_id}

列表的 ``contents`` 常已有正文，但仍逐岗调公开详情接口并仅产出详情读取成功的岗位：
这样 jd_url 的单岗页面和正文都经过真实核验，绝不拿列表链接冒充职位详情。
"""
import json
import os
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from company_name_match import company_name_matches

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


_LIST_API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
_DETAIL_API = "https://gp-api.iguopin.com/api/jobs/v1/info"
_COMPANY_HOME_API = "https://gp-api.iguopin.com/api/company/index/v1/home"
_CHILDREN_API = "https://gp-api.iguopin.com/api/company/index/v1/children-list"
_DETAIL_PAGE = "https://www.iguopin.com/job/detail?id={id}"
_PAGE_SIZE = 20  # 网站自己的列表页大小；与公开 API 实际响应一致
_GROUP_CHILD_CAP = 60
_GROUP_CHILD_PAGE_CAP = 2


class IguopinAdapter(BaseAdapter):
    name = "iguopin"
    max_pages = 200  # 20/页，单一集团检索词最多保护到 4,000 条
    _DETAIL_CAP = 300

    def should_skip(self, source_url: str):
        return None  # JSON POST 不适合 HEAD；由首个 GET/POST 返回真实错误

    def fetch(self, source_url: str) -> str:
        keyword = _company_keyword(source_url)
        if not keyword:
            raise ValueError("iguopin source_url must include ?company={company name}")

        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Origin": "https://www.iguopin.com",
            "Referer": "https://www.iguopin.com/",
        }

        rows, total, complete = self._fetch_rows(keyword, headers, self.max_pages)
        self.reported_total = total
        self.fetch_complete = complete
        group_short_name = self._expand_group_children(rows, headers)
        self._enrich_details(rows, headers)
        # 可选 match token：国聘关键词搜索是模糊匹配（搜「中国建筑」会夹带无关公司岗），
        # 带 &match={token} 时 parse 只放行 company_name 含 token 的岗，保「按公司精准抓取」。
        return json.dumps({
            "list": rows,
            "_match": _match_token(source_url),
            "_group_short_name": group_short_name,
        }, ensure_ascii=False)

    def _fetch_rows(self, keyword: str, headers: dict, max_pages: int):
        def fetch_page(page: int) -> PageResult:
            payload = {
                "search": {"page": page, "page_size": _PAGE_SIZE, "keyword": keyword},
                "recom": {"update_time": True, "company_nature": True, "hot_job": True},
            }
            response = httpx.post(_LIST_API, json=payload, headers=headers,
                                  timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
            body = response.json() or {}
            if body.get("code") != 200:
                raise RuntimeError(f"iguopin list API: {body.get('msg') or body.get('code')}")
            data = body.get("data") or {}
            total = data.get("total")
            return PageResult(items=data.get("list") or [],
                              total=total if isinstance(total, int) else None)

        return paginate_all(
            fetch_page, page_size=_PAGE_SIZE, first_page=1, max_pages=max_pages,
            label=f"iguopin:{keyword}")

    def _expand_group_children(self, rows: List[dict], headers: dict) -> Optional[str]:
        """集团元数据/子公司列表任一异常均静默回退原关键词结果。"""
        company_id = next((str(row.get("company_id") or "").strip()
                           for row in rows if isinstance(row, dict) and row.get("company_id")), "")
        if not company_id:
            return None
        try:
            group_id, group_short_name = self._group_info(company_id, headers)
            if not group_id or not group_short_name:
                return None
            children = self._group_children(group_id, headers)
            if not children:
                return group_short_name
        except Exception:
            return None

        # 默认 60 家、每家最多 2 页（20 条/页）：国网实测 51 家可全覆盖，同时把集团展开
        # 控制在最多 120 次列表调用。两个 cap 均可由环境变量下调/上调，不影响原关键词路径。
        child_cap = _env_cap("IGUOPIN_GROUP_CHILD_CAP", _GROUP_CHILD_CAP)
        page_cap = _env_cap("IGUOPIN_GROUP_PAGE_CAP", _GROUP_CHILD_PAGE_CAP)
        expanded = []
        for child_name in children[:child_cap]:
            try:
                child_rows, _, _ = self._fetch_rows(child_name, headers, page_cap)
            except Exception:
                continue
            for row in child_rows:
                if isinstance(row, dict):
                    row["_group_child"] = True
            expanded.extend(child_rows)
        rows[:] = _dedupe_rows(rows + expanded)
        return group_short_name

    def _group_info(self, company_id: str, headers: dict):
        response = httpx.get(_COMPANY_HOME_API, params={"company_id": company_id}, headers=headers,
                             timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        body = response.json() or {}
        info = (body.get("data") or {}).get("company_info") if body.get("code") == 200 else None
        if not isinstance(info, dict):
            raise ValueError("iguopin company home response missing company_info")

        own_id = str(info.get("id") or company_id).strip()
        group_id = str(info.get("group_id") or "").strip()
        if not group_id and info.get("classify_cn") == "央企(集团)":
            group_id = own_id
        if group_id == own_id or info.get("classify_cn") == "央企(集团)":
            group_short_name = _text(info.get("short_name"))
        else:
            group_short_name = _text(info.get("group_short_name"))
        if not group_id or not group_short_name:
            raise ValueError("iguopin company home response missing group metadata")
        return group_id, group_short_name

    def _group_children(self, group_id: str, headers: dict) -> List[str]:
        response = httpx.get(_CHILDREN_API, params={"company_id": group_id}, headers=headers,
                             timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        body = response.json() or {}
        data = body.get("data") if body.get("code") == 200 else None
        if not isinstance(data, list):
            raise ValueError("iguopin children response missing list")
        names = []
        for item in data:
            name = _text(item.get("name") or item.get("company_name")) if isinstance(item, dict) else None
            if name and name not in names:
                names.append(name)
        return names

    def _enrich_details(self, rows: List[dict], headers: dict) -> None:
        """读取每条公开详情；只有确认存在的逐岗详情才在 parse 中放行。"""
        for row in rows[:resolve_detail_cap(self._DETAIL_CAP)]:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id") or "").strip()
            if not job_id:
                continue
            try:
                response = httpx.get(_DETAIL_API, params={"id": job_id}, headers=headers,
                                     timeout=self.timeout, follow_redirects=True)
                if response.status_code >= 300:
                    continue
                body = response.json() or {}
                detail = body.get("data") if body.get("code") == 200 else None
                if not isinstance(detail, dict) or str(detail.get("job_id") or "") != job_id:
                    continue
                row["_detail_verified"] = True
                row["_jd"] = detail.get("contents") or row.get("contents")
                # Detail 是 title/source of truth，列表的瞬时卡片字段不覆盖它。
                for key in ("job_name", "company_name", "district_list", "education_cn",
                            "experience_cn", "end_time", "recruitment_type_cn"):
                    if detail.get(key) not in (None, ""):
                        row[key] = detail[key]
            except (httpx.HTTPError, ValueError, TypeError):
                continue

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("list") if isinstance(data, dict) else None
        match = (data.get("_match") if isinstance(data, dict) else None) or ""
        group_short_name = (data.get("_group_short_name") if isinstance(data, dict) else None) or ""
        out: List[RawJob] = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("_detail_verified"):
                continue
            job_id = str(row.get("job_id") or "").strip()
            title = str(row.get("job_name") or "").strip()
            if not job_id or not title:
                continue
            company = str(row.get("company_name") or "").strip()
            if match and not row.get("_group_child") and not company_name_matches(company, match):
                continue  # 模糊搜索夹带的无关公司岗，精准过滤掉（严格核名，防同名子串张冠李戴）
            company = _company_with_group_brand(company, group_short_name)
            detail_url = _DETAIL_PAGE.format(id=job_id)
            out.append(RawJob(
                company=company,
                title=title,
                location=_location(row.get("district_list")),
                job_type=_text(row.get("recruitment_type_cn")),
                summary=_text(row.get("_jd")),
                jd_url=detail_url,
                apply_url=detail_url,
                salary_text=_salary_text(row),
                posted_at=_date(row.get("refresh_time") or row.get("update_time")),
                experience=_text(row.get("experience_cn")),
                education=_text(row.get("education_cn")),
                deadline=_text(row.get("end_time")),
            ))
        return out


def _company_keyword(source_url: str) -> str:
    query = parse_qs(urlparse(source_url).query)
    value = (query.get("company") or query.get("keyword") or [""])[0]
    return unquote(value).strip()


def _match_token(source_url: str) -> str:
    """可选精准过滤词：只放行 company_name 含它的岗（应对国聘关键词的模糊夹带）。"""
    value = (parse_qs(urlparse(source_url).query).get("match") or [""])[0]
    return unquote(value).strip()


def _env_cap(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return max(0, int(raw)) if raw not in (None, "") else default
    except ValueError:
        return default


def _dedupe_rows(rows: List[dict]) -> List[dict]:
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("job_id") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    return out


def _company_with_group_brand(company: str, group_short_name: str) -> str:
    company = (company or "").strip()
    brand = (group_short_name or "").strip()
    if not company or not brand or brand in company:
        return company
    return f"{company}（{brand}）"


def _location(district_list) -> Optional[str]:
    if not isinstance(district_list, list):
        return None
    values = []
    for item in district_list:
        if isinstance(item, dict) and _text(item.get("area_cn")):
            values.append(_text(item.get("area_cn")))
    return "、".join(dict.fromkeys(values)) or None


def _salary_text(row: dict) -> Optional[str]:
    if row.get("is_negotiable"):
        return "面议"
    lo, hi = row.get("min_wage"), row.get("max_wage")
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if lo <= 0 and hi <= 0:
        return None
    unit = _text(row.get("wage_unit_cn")) or "元/月"
    if lo > 0 and hi > 0:
        return f"{lo:g}-{hi:g}{unit}"
    return f"{max(lo, hi):g}{unit}"


def _date(value) -> Optional[str]:
    text = _text(value)
    return text[:10] if text else None


def _text(value) -> Optional[str]:
    text = str(value or "").strip()
    return text or None
