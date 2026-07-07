"""
字节跳动 — jobs.bytedance.com（飞书/Lark 招聘平台，公开 posts API）。

为什么不用浏览器：字节与飞书招聘同源接口 `/api/v1/search/job/posts` 已确认可冷启动
httpx 直连，无签名 / token / cookie；旧浏览器被动拦截只翻 4 页 + 关键词枚举，会把 2 万级
岗位截成几十条。本适配器按 recruitment_id 分轨道，服务端 offset/limit 翻页，社招触达
count 封顶时用一级职类 + 城市切片把单片压到 1 万以内。
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set
from urllib.parse import quote

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter, _UA


log = logging.getLogger(__name__)

_POSTS_URL = "https://jobs.bytedance.com/api/v1/search/job/posts"
_COUNT_CAP = 10000
_DEFAULT_PAGE_LIMIT = 200
_DEFAULT_MAX_JOBS = 25000
_DEFAULT_SAMPLE_JOBS = 2000
_DEFAULT_REQ_INTERVAL_S = 3.0
_DEFAULT_405_BACKOFF_S = 30.0
_DEFAULT_MAX_RETRIES = 3


def _kw(term: str) -> str:
    return f"https://jobs.bytedance.com/experienced/position?keyword={quote(term)}"


def _campus_kw(term: str) -> str:
    return f"https://jobs.bytedance.com/campus/position?keyword={quote(term)}"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw not in (None, ""):
        try:
            return max(minimum, int(raw))
        except (TypeError, ValueError):
            pass
    return default


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw not in (None, ""):
        try:
            return max(minimum, float(raw))
        except (TypeError, ValueError):
            pass
    return default


def _as_count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def page_offsets(count: int, limit: int) -> List[int]:
    """为什么抽成纯函数：分页边界最容易 off-by-one，测试直接覆盖 0..count 的 offset 规划。"""
    total = _as_count(count)
    step = max(1, int(limit or 1))
    return list(range(0, total, step))


def build_search_body(
    recruitment_id: str,
    offset: int,
    limit: int,
    *,
    category_id: Optional[str] = None,
    city_code: Optional[str] = None,
) -> dict:
    """构造字节 posts API body；城市参数名必须是 location_code_list，city_code_list 会被忽略。"""
    body = {
        "keyword": "",
        "limit": int(limit),
        "offset": int(offset),
        "recruitment_id_list": [str(recruitment_id)],
    }
    if category_id:
        body["job_category_id_list"] = [str(category_id)]
    if city_code:
        body["location_code_list"] = [str(city_code)]
    return body


def primary_category_id(post: dict) -> Optional[str]:
    """返回一级职类 id：优先 job_category.parent.id，没有 parent 时自身就是一级。"""
    if not isinstance(post, dict):
        return None
    cat = post.get("job_category")
    if not isinstance(cat, dict):
        return None
    parent = cat.get("parent")
    if isinstance(parent, dict) and parent.get("id"):
        return str(parent.get("id")).strip() or None
    if cat.get("id"):
        return str(cat.get("id")).strip() or None
    return None


def collect_primary_category_ids(posts: List[dict]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for post in posts or []:
        cid = primary_category_id(post)
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def collect_city_codes(posts: List[dict]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for post in posts or []:
        city_list = (post or {}).get("city_list")
        if not isinstance(city_list, list):
            continue
        for city in city_list:
            if not isinstance(city, dict):
                continue
            code = str(city.get("code") or "").strip()
            if code and code not in seen:
                seen.add(code)
                out.append(code)
    return out


def _post_id(post: dict) -> str:
    return str((post or {}).get("id") or "").strip()


def merge_unique_posts(target: List[dict], seen: Set[str], posts: List[dict], max_jobs: int) -> bool:
    """按雪花 id 去重合并；返回是否撞到安全上限。"""
    for post in posts or []:
        pid = _post_id(post)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        target.append(post)
        if len(target) >= max_jobs:
            return True
    return False


def reconcile_complete(total: int, covered_counts: List[int]) -> bool:
    """父级 total 必须被子切片 count 覆盖；采样漏切片时宁可标不完整，也不误开 absence。"""
    return sum(_as_count(c) for c in (covered_counts or [])) >= _as_count(total)


@dataclass
class BytedancePage:
    count: int = 0
    jobs: List[dict] = field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None


@dataclass
class BytedanceFetchResult:
    jobs: List[dict]
    total: Optional[int] = None
    complete: bool = False
    reached: bool = True
    skipped_pages: int = 0
    hit_max_jobs: bool = False


FetchPage = Callable[[str, int, int, Optional[str], Optional[str]], BytedancePage]


def collect_bytedance_track(
    fetch_page: FetchPage,
    recruitment_id: str,
    *,
    page_limit: int = _DEFAULT_PAGE_LIMIT,
    max_jobs: int = _DEFAULT_MAX_JOBS,
    sample_limit: int = _DEFAULT_SAMPLE_JOBS,
    count_cap: int = _COUNT_CAP,
) -> BytedanceFetchResult:
    """按一个招聘轨道抓全岗位，IO 通过 fetch_page 注入，便于单测切片规划。

    策略：
    - count < 10000：直接 offset 翻到 count；
    - count >= 10000：先采样一级职类；单职类仍封顶时再采样城市；
    - 任一叶子页失败 / 叶子仍封顶 / 撞安全上限，都保留已抓数据但 complete=False。
    """
    rows: List[dict] = []
    seen: Set[str] = set()
    skipped_pages = 0
    complete = True
    hit_max_jobs = False
    category_counts: List[int] = []

    def safe_fetch(offset: int, limit: int, category_id: Optional[str] = None,
                   city_code: Optional[str] = None) -> BytedancePage:
        try:
            page = fetch_page(str(recruitment_id), int(offset), int(limit), category_id, city_code)
        except Exception as exc:
            return BytedancePage(ok=False, error=f"{type(exc).__name__}: {exc}")
        if not isinstance(page, BytedancePage):
            return BytedancePage(ok=False, error="invalid page object")
        page.count = _as_count(page.count)
        page.jobs = page.jobs if isinstance(page.jobs, list) else []
        return page

    def mark_skip(page: BytedancePage, scope: str) -> None:
        nonlocal skipped_pages, complete
        skipped_pages += 1
        complete = False
        log.warning("bytedance posts page skipped scope=%s error=%s", scope, page.error or "unknown")

    def sample_posts(category_id: Optional[str], city_code: Optional[str], total: int) -> List[dict]:
        nonlocal complete
        out: List[dict] = []
        target = min(_as_count(total), max(0, int(sample_limit or 0)))
        for offset in page_offsets(target, page_limit):
            page = safe_fetch(offset, page_limit, category_id, city_code)
            if not page.ok:
                mark_skip(page, f"sample cat={category_id or '-'} city={city_code or '-'} offset={offset}")
                continue
            out.extend(page.jobs)
        if target > 0 and not out:
            complete = False
        return out

    def fetch_leaf(category_id: Optional[str], city_code: Optional[str], total: int) -> None:
        nonlocal complete, hit_max_jobs
        leaf_total = min(_as_count(total), count_cap)
        if total >= count_cap:
            # 叶子仍达到封顶值，说明还可能有不可翻出的尾部；保留前 1 万但不能声明抓全。
            complete = False
        for offset in page_offsets(leaf_total, page_limit):
            if len(rows) >= max_jobs:
                hit_max_jobs = True
                complete = False
                return
            page = safe_fetch(offset, page_limit, category_id, city_code)
            scope = f"leaf cat={category_id or '-'} city={city_code or '-'} offset={offset}"
            if not page.ok:
                mark_skip(page, scope)
                continue
            if not page.jobs and offset < leaf_total:
                complete = False
                log.warning("bytedance posts empty page before expected end scope=%s", scope)
                return
            if merge_unique_posts(rows, seen, page.jobs, max_jobs):
                hit_max_jobs = True
                complete = False
                return

    root = safe_fetch(0, 1)
    if not root.ok:
        return BytedanceFetchResult(
            jobs=[], total=None, complete=False, reached=False, skipped_pages=1
        )

    total = root.count
    if total < count_cap:
        fetch_leaf(None, None, total)
        return BytedanceFetchResult(
            jobs=rows,
            total=total,
            complete=complete and not hit_max_jobs and skipped_pages == 0,
            skipped_pages=skipped_pages,
            hit_max_jobs=hit_max_jobs,
        )

    sample = sample_posts(None, None, total)
    categories = collect_primary_category_ids(sample)
    if not categories:
        complete = False
        log.warning("bytedance posts capped root but no category ids sampled; fetching capped root only")
        fetch_leaf(None, None, min(total, count_cap))
        return BytedanceFetchResult(
            jobs=rows,
            total=total,
            complete=False,
            skipped_pages=skipped_pages,
            hit_max_jobs=hit_max_jobs,
        )

    for category_id in categories:
        if len(rows) >= max_jobs:
            hit_max_jobs = True
            complete = False
            break
        cat_probe = safe_fetch(0, 1, category_id, None)
        if not cat_probe.ok:
            mark_skip(cat_probe, f"probe cat={category_id}")
            continue
        category_counts.append(cat_probe.count)
        if cat_probe.count < count_cap:
            fetch_leaf(category_id, None, cat_probe.count)
            continue

        city_sample = sample_posts(category_id, None, cat_probe.count)
        cities = collect_city_codes(city_sample)
        city_counts: List[int] = []
        if not cities:
            complete = False
            log.warning("bytedance posts capped category=%s but no city codes sampled", category_id)
            fetch_leaf(category_id, None, min(cat_probe.count, count_cap))
            continue
        for city_code in cities:
            if len(rows) >= max_jobs:
                hit_max_jobs = True
                complete = False
                break
            city_probe = safe_fetch(0, 1, category_id, city_code)
            if not city_probe.ok:
                mark_skip(city_probe, f"probe cat={category_id} city={city_code}")
                continue
            city_counts.append(city_probe.count)
            fetch_leaf(category_id, city_code, min(city_probe.count, count_cap))
        if not reconcile_complete(cat_probe.count, city_counts):
            complete = False
            log.warning(
                "bytedance city sample undercovered category=%s total=%s covered=%s fetched=%s; mark incomplete",
                category_id, cat_probe.count, sum(_as_count(c) for c in city_counts), len(rows),
            )

    if not reconcile_complete(total, category_counts):
        complete = False
        log.warning(
            "bytedance category sample undercovered total=%s covered=%s fetched=%s; mark incomplete",
            total, sum(_as_count(c) for c in category_counts), len(rows),
        )

    return BytedanceFetchResult(
        jobs=rows,
        total=total,
        complete=complete and not hit_max_jobs and skipped_pages == 0,
        skipped_pages=skipped_pages,
        hit_max_jobs=hit_max_jobs,
    )


def map_recruit_type(recruit_type: dict, fallback: str = "") -> Optional[str]:
    """把字节 recruit_type 映射为产品侧招聘类型，而不是把职类误塞进 job_type。"""
    if not isinstance(recruit_type, dict):
        return fallback or None
    name = str(recruit_type.get("name") or "").strip()
    parent = recruit_type.get("parent")
    parent_name = str((parent or {}).get("name") or "").strip() if isinstance(parent, dict) else ""
    text = f"{parent_name} {name}"
    if "暑期实习" in text:
        return "暑期实习"
    if "日常实习" in text:
        return "日常实习"
    if "实习" in text:
        return "实习"
    if "社" in parent_name or "社会招聘" in text:
        return "社招"
    if "校" in parent_name or "校园招聘" in text or "应届" in text:
        return "校招"
    return fallback or None


class BytedanceAdapter(PlaywrightAdapter):
    name = "bytedance"
    recruitment_id = "1"
    recruit_type = "社招"
    board = "experienced"
    company_name = "字节跳动"
    official_hosts = ("jobs.bytedance.com",)
    intercept_match = "/api/v1/search/job/posts"
    detail_template = "https://jobs.bytedance.com/experienced/position/{id}/detail"
    posts_keys = ("data.job_post_list", "job_post_list", "data.posts", "posts")
    list_urls = [
        _kw("算法"),
        _kw("工程"),
        _kw("产品"),
        _kw("运营"),
        _kw("数据"),
        _kw("设计"),
        _kw("测试"),
        _kw("销售"),
        _kw("市场"),
        _kw("财务"),
        "https://jobs.bytedance.com/experienced/position",
    ]

    # list-absence 探活只在 fetch_complete=True 时才会进入 run.py；任何跳页/封顶/安全上限都置 False。
    supports_absence_liveness = True
    fetch_complete = False
    _HTTPX_TIMEOUT = 30

    def __init__(self):
        self.page_limit = _env_int("BYTEDANCE_PAGE_LIMIT", _DEFAULT_PAGE_LIMIT)
        self.max_jobs = _env_int("BYTEDANCE_MAX_JOBS", _DEFAULT_MAX_JOBS)
        self.sample_limit = _env_int("BYTEDANCE_SAMPLE_JOBS", _DEFAULT_SAMPLE_JOBS)
        self.request_interval_s = _env_float("BYTEDANCE_REQ_INTERVAL_S", _DEFAULT_REQ_INTERVAL_S)
        self.retry_backoff_s = _env_float("BYTEDANCE_405_BACKOFF_S", _DEFAULT_405_BACKOFF_S)
        self.max_retries = _env_int("BYTEDANCE_MAX_RETRIES", _DEFAULT_MAX_RETRIES, minimum=0)
        self.fetch_complete = False
        self._last_request_at: Optional[float] = None

    def _headers(self) -> dict:
        return {
            "User-Agent": _UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://jobs.bytedance.com",
            "Referer": f"https://jobs.bytedance.com/{self.board}/position",
        }

    def _wait_for_rate_limit(self) -> None:
        if self.request_interval_s <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            wait_s = self.request_interval_s - (now - self._last_request_at)
            if wait_s > 0:
                time.sleep(wait_s)
        self._last_request_at = time.monotonic()

    def _request_page(self, client, body: dict) -> BytedancePage:
        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()
            try:
                resp = client.post(_POSTS_URL, json=body)
                status = getattr(resp, "status_code", 200)
                if status == 405:
                    if attempt < self.max_retries:
                        log.warning(
                            "bytedance posts HTTP 405; backing off %.1fs before retry %s/%s",
                            self.retry_backoff_s, attempt + 1, self.max_retries,
                        )
                        time.sleep(self.retry_backoff_s)
                        continue
                    return BytedancePage(ok=False, error="HTTP 405 after retries")
                if hasattr(resp, "raise_for_status"):
                    resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                return BytedancePage(ok=False, error=f"{type(exc).__name__}: {exc}")

            data = (payload or {}).get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                return BytedancePage(ok=False, error="missing data")
            jobs = data.get("job_post_list") or []
            if not isinstance(jobs, list):
                return BytedancePage(ok=False, error="job_post_list is not list")
            return BytedancePage(count=_as_count(data.get("count")), jobs=jobs)
        return BytedancePage(ok=False, error="retry loop exhausted")

    def _httpx_fetch(self) -> BytedanceFetchResult:
        with httpx.Client(
            timeout=self._HTTPX_TIMEOUT,
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            def fetch_page(
                rid: str,
                offset: int,
                limit: int,
                category_id: Optional[str] = None,
                city_code: Optional[str] = None,
            ) -> BytedancePage:
                body = build_search_body(
                    rid, offset, limit, category_id=category_id, city_code=city_code
                )
                return self._request_page(client, body)

            return collect_bytedance_track(
                fetch_page,
                self.recruitment_id,
                page_limit=self.page_limit,
                max_jobs=self.max_jobs,
                sample_limit=self.sample_limit,
            )

    def fetch(self, source_url: str) -> str:
        self.fetch_complete = False
        result = self._httpx_fetch()
        if not result.reached:
            raise RuntimeError(f"{self.name}: posts API not reached")
        self.fetch_complete = bool(result.complete)
        if result.hit_max_jobs:
            log.warning("%s hit BYTEDANCE_MAX_JOBS=%s; fetch_complete=False", self.name, self.max_jobs)
        if result.skipped_pages:
            log.warning("%s skipped %s pages; fetch_complete=False", self.name, result.skipped_pages)
        count = len(result.jobs) if (result.total or 0) >= _COUNT_CAP else (result.total or len(result.jobs))
        return json.dumps(
            {"_intercepted": [{"data": {"job_post_list": result.jobs, "count": count}}]},
            ensure_ascii=False,
        )

    def _map(self, post: dict) -> Optional[RawJob]:
        pid = _post_id(post)
        title = (post.get("title") or post.get("name") or "").strip()
        if not pid or not title:
            return None

        city = ""
        cl = post.get("city_list")
        if isinstance(cl, list) and cl and isinstance(cl[0], dict):
            city = cl[0].get("name") or ""
        if not city:
            ci = post.get("city_info")
            if isinstance(ci, dict):
                city = ci.get("name") or ""

        desc = (post.get("description") or "").strip()
        req = (post.get("requirement") or "").strip()
        summary = (desc + ("\n\n【职位要求】" + req if req else "")).strip() or None

        job_type = map_recruit_type(post.get("recruit_type") or {}, self.recruit_type)

        jd_url = self.detail_template.format(id=pid)
        return RawJob(
            company=self.company_name,
            title=title,
            location=city or None,
            job_type=job_type or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )


class BytedanceCampusAdapter(BytedanceAdapter):
    """字节跳动校招 / 实习：同一 posts API，仅 recruitment_id_list=["2"] 与详情路径不同。"""

    name = "bytedance_campus"
    recruitment_id = "2"
    recruit_type = "校招"
    board = "campus"
    detail_template = "https://jobs.bytedance.com/campus/position/{id}/detail"
    list_urls = [
        _campus_kw("算法"),
        _campus_kw("研发"),
        _campus_kw("产品"),
        _campus_kw("实习"),
        _campus_kw("数据"),
        _campus_kw("设计"),
        _campus_kw("运营"),
        "https://jobs.bytedance.com/campus/position",
    ]
