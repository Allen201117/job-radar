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
from concurrent.futures import ThreadPoolExecutor
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
_DETAIL_WORKERS = 3


class IguopinAdapter(BaseAdapter):
    name = "iguopin"
    max_pages = 200  # 20/页，单一集团检索词最多保护到 4,000 条
    _DETAIL_CAP = 300

    def should_skip(self, source_url: str):
        if resolve_detail_cap(self._DETAIL_CAP) == 0:
            print("[iguopin] 需详情核验、快档 cap=0 → 跳过本轮")
            return "iguopin requires detail verification; CRAWL_DETAIL_CAP=0"
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
        group_short_name, group_id = self._expand_group_children(rows, headers)
        group_ok = self._group_membership_checker(group_id, headers) if group_id else None
        # 可选 match token：国聘关键词搜索是模糊匹配（搜「中国建筑」会夹带无关公司岗），
        # 带 &match={token} 时只放行 company_name 含 token 的岗，保「按公司精准抓取」。
        match = _match_token(source_url)
        listed = len(rows)
        # 即使没配 match，集团展开进来的行也要过归属核验——旁路必须堵死。
        if match or group_ok:
            rows[:] = [row for row in rows if _row_passes_match(row, match, group_ok)]
        # 归属核验只有 fetch 做得了（要联网查国聘的集团口径），parse 里没有这个能力。
        # 打个标把结论带下去，否则 parse 的那道复查会按「名字核名」把真子公司再毙一次
        # （鼎和财产保险/国网江苏 名字里都不含集团名）。
        for row in rows:
            if isinstance(row, dict):
                row["_attribution_ok"] = True
        verified = self._enrich_details(rows, headers)
        print(f"[iguopin] keyword={keyword} listed={listed} matched={len(rows)} verified={verified}")
        return json.dumps({
            "list": rows,
            "_match": match,
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

    def _expand_group_children(self, rows: List[dict], headers: dict):
        """返回 (group_short_name, group_id)；集团元数据/子公司列表任一异常均静默回退原关键词结果。"""
        company_id = next((str(row.get("company_id") or "").strip()
                           for row in rows if isinstance(row, dict) and row.get("company_id")), "")
        if not company_id:
            return None, ""
        try:
            group_id, group_short_name = self._group_info(company_id, headers)
            if not group_id or not group_short_name:
                return None, ""
            children = self._group_children(group_id, headers)
            if not children:
                return group_short_name, group_id
        except Exception:
            return None, ""

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
                    # 记**是哪个子公司名把这条搜回来的**，而不是只记一个 True。
                    # 下游要用它逐条核名——国聘的关键词搜索是模糊的，拿子公司名去搜同样会
                    # 捞回不相干的公司（见 _row_passes_match 的注释）。
                    row["_group_child"] = child_name
            expanded.extend(child_rows)
        rows[:] = _dedupe_rows(rows + expanded)
        return group_short_name, group_id

    def _company_group_id(self, company_id: str, headers: dict):
        """查这家公司在国聘口径下的集团 id。三种返回值，语义必须分开：
          · "xxx" = 有集团；  · ""  = **查到了、但它没有集团**（独立公司，定论）；
          · None = 请求/解析失败（暂时不知道）。
        把「没有集团」和「查不到」混成一种，正是张冠李戴修不掉的原因：
        中国（海南）改革发展研究院在国聘上写着「民营企业、无集团」，
        当成「查不到 → 保守放行」就永远挡不住它。
        """
        try:
            response = httpx.get(_COMPANY_HOME_API, params={"company_id": company_id},
                                 headers=headers, timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
            body = response.json() or {}
            if body.get("code") != 200:
                return None
            info = (body.get("data") or {}).get("company_info")
            if not isinstance(info, dict):
                return None
            own_id = str(info.get("id") or company_id).strip()
            group_id = str(info.get("group_id") or "").strip()
            if not group_id and info.get("classify_cn") == "央企(集团)":
                group_id = own_id      # 集团本体，自己就是自己的集团
            return group_id            # 可能是 ""，那是「无集团」的定论
        except Exception:
            return None

    def _group_membership_checker(self, group_id: str, headers: dict):
        """返回 `ok(row) -> bool`：这条岗的公司在**国聘自己的口径**下是否真属于本集团。

        判据是 group_id，不是名字——名字核不住：鼎和财产保险是南方电网真子公司、
        名字里却没有「南方电网」；反过来「中国（海南）改革发展研究院」名字里有「海南」，
        被「海南电网有限责任公司」这个关键词搜了回来，实际是民营企业。
        按 company_id 缓存，一家公司只查一次（单源实测 20~100 家，成本可接受）。

        失败语义：查到「无集团」→ **拒**（定论）；请求失败 → 放行（暂时不知道，下轮重查，
        宁可多留一条待发现的错归属，也不因为对方接口抖一下就丢掉整源真岗）。
        """
        cache: dict = {}

        def ok(row) -> bool:
            cid = str((row or {}).get("company_id") or "").strip()
            if not cid:
                return True
            if cid not in cache:
                found = self._company_group_id(cid, headers)
                cache[cid] = True if found is None else (str(found) == str(group_id))
            return cache[cid]

        return ok

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

    def _enrich_details(self, rows: List[dict], headers: dict) -> int:
        """读取每条公开详情；只有确认存在的逐岗详情才在 parse 中放行。"""
        def enrich_row(row: dict) -> bool:
            job_id = str(row.get("job_id") or "").strip()
            if not job_id:
                return False
            try:
                response = httpx.get(_DETAIL_API, params={"id": job_id}, headers=headers,
                                     timeout=self.timeout, follow_redirects=True)
                if response.status_code >= 300:
                    return False
                body = response.json() or {}
                detail = body.get("data") if body.get("code") == 200 else None
                if not isinstance(detail, dict) or str(detail.get("job_id") or "") != job_id:
                    return False
                row["_detail_verified"] = True
                row["_jd"] = detail.get("contents") or row.get("contents")
                # Detail 是 title/source of truth，列表的瞬时卡片字段不覆盖它。
                for key in ("job_name", "company_name", "district_list", "education_cn",
                            "experience_cn", "end_time", "recruitment_type_cn"):
                    if detail.get(key) not in (None, ""):
                        row[key] = detail[key]
                return True
            except (httpx.HTTPError, ValueError, TypeError):
                return False

        detail_rows = [row for row in rows[:resolve_detail_cap(self._DETAIL_CAP)]
                       if isinstance(row, dict)]
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            return sum(executor.map(enrich_row, detail_rows))

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
            # fetch 已按国聘集团口径核过归属的行直接放行；没核过的（非本 adapter 产出的
            # payload）仍走严格核名，防模糊搜索夹带的同名子串张冠李戴。
            if not row.get("_attribution_ok") and not _row_passes_match(row, match):
                continue
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


def _row_passes_match(row: dict, match: str, group_ok=None) -> bool:
    """放行列表行。分两条路，判据不同：

    ① 直接关键词搜出来的行 → 按 source_url 的 `match` 核名（防「搜中国建筑夹带无关公司」）。
    ② 集团子公司展开出来的行 → **不能豁免**，改用国聘自己的集团归属核验（`group_ok`）。

    ⚠️ 2026-09-04 实测的张冠李戴：南方电网的子公司名单里有「海南电网有限责任公司」，
    adapter 拿它去关键词搜，而**国聘的搜索是按集团模糊匹配的**，回来的既有真兄弟公司
    （鼎和财产保险，名字里没有「南方电网」），也有毫不相干的
    「中国（海南）改革发展研究院有限责任公司」「洋浦国际投资咨询有限公司」「海南健康发展研究院」。
    国聘自己的公司主页写得很清楚：这三家分别是**民营企业 / 洋浦经济开发区 / 事业单位**，
    与南方电网无关。旧写法对 `_group_child` 直接 return True、整个跳过核验 →
    它们被打上「（南方电网）」入库。归属准确性是红线，不能有旁路。

    为什么不能用「子公司名核名」代替：国聘搜索是集团级的，搜「海南电网有限责任公司」
    返回的鼎和保险是**真兄弟公司但名字对不上**，按名字核会把真岗全毙掉（实测放行 0 条）。
    唯一可信的判据是国聘自己的 group_id —— 见 `_group_membership_ok`。
    """
    if not isinstance(row, dict):
        return False
    name = str(row.get("company_name") or "").strip()
    if group_ok is not None:
        # 有集团口径时它对**所有**行生效，不只对 _group_child：
        # 直接关键词搜出来的鼎和财产保险也是南方电网真子公司，按名字核会被误杀。
        return bool(group_ok(row))
    if not match:
        return True
    return company_name_matches(name, match)


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
