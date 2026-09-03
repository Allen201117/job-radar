"""网易**校园招聘**（campus.163.com）适配器 —— 零登录、零浏览器。

2026-09-03 曾判「网易校招接口未解」。实际上它有一套完全公开的 JSON API，难点不在鉴权，
在**「哪些项目还开着」**：这个后台把 2019 年至今的 93 个招聘项目全留着，接口对早已结束的
项目照样返回岗位（projectId=1 还能返 2019 届的岗），`projectStatus` 恒为 1、毫无区分度。
照单全收 = 把七年前的死岗当在招入库。

## 接口（campus.163.com 与 campus.game.163.com 共用同一后端）
- 导航（当前开放的项目）：`GET /api/campuspc/project/navigation/list`
- 项目信息：`GET /api/campuspc/project/banner?projectId={id}` → `data.projectName`
- 岗位列表：`GET /api/campuspc/position/getJobList?projectId={id}&currentPage=&pageSize=`
  → `data.total` / `data.pages` / `data.list[]`，行里**直接带**
    `positionDescription`（岗位职责）+ `positionRequirement`（岗位要求），不用逐岗富化。

## 怎么判「这个项目还开着」
唯一可靠的信号是**项目名里的届次**（"2027届雷火秋季校园招聘"）。规则：
  ① 名字含「测试」/「勿动」→ 丢（后台里真有 4 个这种项目，其中一个还挂着 3 个岗）；
  ② 名字能解析出届次 → 届次 ≥ 本轮目标届（campus_cycle_backlog.current_cohort）才要；
  ③ 名字没有届次（如「《蛋仔派对》AI实习专项」）→ 只有**导航接口列出来的**才要
     （导航 = 站点自己声明当前在招，比我们猜可靠）。
2026-09-04 实测这套规则选出 2027/2028 届共 8 个项目、250 个岗；被挡掉的包括
「2026届互联网校招-秋招」「2025届互联网秋季校园招聘」等 5 个仍能返回岗位的过期项目。

## projectId 扫描窗口
projectId 是**按时间递增**的（1=2019届 … 104=2027届，93 个项目逐一核对过），所以只需在
导航里最大的 id 附近开一个窗口扫，不必从 1 扫到底。窗口随导航 id 自然前移，明年不用改代码。

## 逐岗 jd_url
`https://campus.163.com/app/detail/index?id={id}`（id = 列表行的 `id`）。
⚠️ 路由是**点击卡片后拦截到的**，不是猜的。三个项目族（互娱 102 / 雷火 77 / 互联网 103）
各取一个岗 live 核过：都在 campus.163.com 这一个域名下正常渲染，不需要按项目切 host
（导航里互娱指向 campus.game.163.com，但那只是入口页，详情页两边通用）。

## 为什么不按「网易有道 / 网易云音乐」派生子公司
岗位名里确实带后缀（"全栈开发工程师-网易有道"）。但必投清单里 网易 的 pattern 是 `%网易%`，
派生与否都命中，收益为零；而拆错公司名会直接踩「归属准确性」红线。社招侧 netease.py 按
`productName` 派生是因为那边有独立字段，这里没有，不用正则从标题里抠。
"""
import json
import re
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location

_COHORT_RE = re.compile(r"(20\d\d)\s*届")
_TEST_MARKERS = ("测试", "勿动")


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def cohort_year(now=None) -> int:
    """本轮目标届别的年份。与 campus_cycle_backlog.current_cohort 同口径（5 月起滚到下一届），
    这里不 import 它：那个模块要连 Supabase，adapter 层不该被拖进去。改一处务必想到另一处。"""
    now = now or datetime.now(timezone.utc)
    return now.year + 1 if now.month >= 5 else now.year


def project_is_current(name: str, in_navigation: bool, target_year: int) -> bool:
    """这个招聘项目算不算「当前在招」。见文件头「怎么判这个项目还开着」。"""
    text = str(name or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _TEST_MARKERS):
        return False
    years = [int(y) for y in _COHORT_RE.findall(text)]
    if years:
        return max(years) >= target_year
    return bool(in_navigation)   # 没有届次就只信导航，不猜


class NeteaseCampusAdapter(BaseAdapter):
    name = "netease_campus"
    company_name = "网易"
    official_hosts = ("campus.163.com", "campus.game.163.com")

    ORIGIN = "https://campus.163.com"
    NAV_URL = ORIGIN + "/api/campuspc/project/navigation/list"
    BANNER_URL = ORIGIN + "/api/campuspc/project/banner"
    LIST_URL = ORIGIN + "/api/campuspc/position/getJobList"
    DETAIL_URL = ORIGIN + "/app/detail/index?id={job_id}"

    PAGE_SIZE = 50
    MAX_PAGES = 40
    # 扫描窗口：以导航里最大的 projectId 为锚，往回 45 / 往前 40。往回是为了捞导航没列、
    # 但届次仍在有效期内的项目（雷火/互娱的实习专项就属于这类）；往前是为了在新项目上线、
    # 导航还没更新时也能发现它。
    SCAN_BACK = 45
    SCAN_AHEAD = 40
    FALLBACK_ANCHOR = 104   # 导航整个取不到时的锚点（2026-09 时的最大 projectId）

    def _params(self, **extra) -> dict:
        return dict(timeStamp=int(time.time() * 1000), **extra)

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": self.ORIGIN + "/",
        }

    @staticmethod
    def _navigation_project_ids(payload) -> set:
        """从导航树里抠出 `.../position?id=NN` 的 projectId。取不到就返回空集合（降级到窗口扫描）。"""
        ids = set()

        def walk(nodes):
            for node in nodes or []:
                if not isinstance(node, dict):
                    continue
                match = re.search(r"position\?id=(\d+)", str(node.get("link") or ""))
                if match:
                    ids.add(int(match.group(1)))
                walk(node.get("children"))

        walk((payload or {}).get("data") or [])
        return ids

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        target_year = cohort_year()
        rows: List[dict] = []
        seen: set = set()
        project_totals: List[int] = []
        projects_drained: List[bool] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:
            nav_ids: set = set()
            try:
                nav_ids = self._navigation_project_ids(client.get(self.NAV_URL, params=self._params()).json())
            except (httpx.HTTPError, ValueError):
                pass   # 导航挂了不致命：窗口扫描 + 届次规则仍能选出当前项目
            anchor = max(nav_ids) if nav_ids else self.FALLBACK_ANCHOR
            window = range(max(1, anchor - self.SCAN_BACK), anchor + self.SCAN_AHEAD + 1)

            current: List[int] = []
            for project_id in window:
                try:
                    banner = client.get(self.BANNER_URL, params=self._params(projectId=project_id)).json()
                except (httpx.HTTPError, ValueError):
                    continue
                data = banner.get("data")
                project_name = (data or {}).get("projectName") if isinstance(data, dict) else None
                if not project_name:
                    continue   # 该 id 没有项目
                if project_is_current(project_name, project_id in nav_ids, target_year):
                    current.append(project_id)

            for project_id in current:
                total, got = None, 0
                for page in range(1, self.MAX_PAGES + 1):
                    try:
                        payload = client.get(self.LIST_URL, params=self._params(
                            projectId=project_id, currentPage=page, pageSize=self.PAGE_SIZE)).json()
                    except (httpx.HTTPError, ValueError):
                        break
                    data = payload.get("data") or {}
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
                        rows.append(row)
                        fresh += 1
                    got += len(page_rows)
                    if total is not None and got >= total:
                        break
                    # 末页判据看「这一页有没有带来新岗」，不看页长——短页不该收工。
                    if not fresh:
                        break
                if total is not None:
                    project_totals.append(total)
                    projects_drained.append(got >= total)
                else:
                    projects_drained.append(False)
        if not rows:
            raise RuntimeError("netease_campus: 没有选出任何当前在招项目（导航与届次规则都没命中）")
        if len(project_totals) == len(projects_drained):
            self.reported_total = sum(project_totals)
        self.fetch_complete = bool(projects_drained) and all(projects_drained)
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
            # workPlaceName 是逗号分隔的多地点串（"杭州,上海,广州"）；取首个作主地点，
            # 全串留在正文里，别丢掉「多地可投」这个对校招用户重要的信息。
            places = str(row.get("workPlaceName") or "").strip()
            location = places.split(",")[0].strip() if places else ""
            if location and not is_china_company_location(location):
                continue
            bits = []
            if places:
                bits.append(f"工作地点：{places}")
            desc = str(row.get("positionDescription") or "").strip()
            req = str(row.get("positionRequirement") or "").strip()
            if desc:
                bits.append("岗位描述：" + desc)
            if req:
                bits.append("岗位要求：" + req)
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location or None,
                job_type=str(row.get("positionTypeName") or "").strip() or None,
                summary="\n".join(bits).strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
            ))
        return jobs
