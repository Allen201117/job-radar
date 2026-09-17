"""美的集团**校园招聘**门户 careers.midea.com 适配器（自建 iHR，纯 httpx，零登录、零浏览器）。

⚠️ 与 `midea.py`（社招）是**两套 host、两套后端**，别混：
    社招 recruit.midea.com（form-encoded，端点见 `adapters/midea.py` 的 LIST_API）
    校招 careers.midea.com/backend/school/position/common/…（JSON）
岗位 id 空间不相干（社招 positionId 是 iHR 内码，校招是另一套 32 位 hex），jd_url 也不同。

## 接口（2026-09-18 live 探明，零鉴权）
① 招聘项目：`GET /backend/school/position/common/project/list?status=1`
   → `data:[{projectRuleId, projectRuleName, employementCategory, projectType, numberOfSessions, status}]`
   实测 4 个在跑：日常实习生招聘通道(9)/校企合作实习招聘通道(7)/2027届美的星校园招聘(1)/2027应届博士校园招聘(5)。
   **项目是动态的**（同事 2026-09-18 凌晨看到的是 3 个，几小时后是 4 个）→ 必须每轮现查，
   不许把 projectRuleId 硬编码进代码或 sources 行。
② 岗位：`POST /backend/school/position/common/position/list`
   body `{"projectRuleId":…, "pageIndex":N, "pageSize":20}`
   → `data:{total, info:{pageIndex,pageSize,totalPage,…}, data:[岗位…]}`
③ 详情：`POST /backend/school/position/common/position/details` body `{"positionId":…}`
   → 只在探活时用（判死信号见 enrich._detail_midea_campus）。**抓取不需要它**：
   列表行的 `projectPositionDto` 自带 `jobResponsibility` + `jobRequirement` 全文
   （live 535/535 行都有正文，零薄卡）。

⚠️ **别想着靠页面文案判死——详情页不随撤岗消失**（2026-09-18 Playwright 真渲染实测）：
   已撤下的 `8a5ea6d6…232160`（publishStatus=2）照样渲染出完整岗位名 + 职责 + 要求 +
   **「立即投递」按钮**（576 字），与在招岗肉眼无差；只有 positionId 彻底不存在时
   才渲染出 110 字的空壳。同 CLAUDE.md 里浦发那条边界。
   ⇒ 判死只能读接口字段，`audit_dead_links` 的 DEAD_MARKERS 对这个源一条都匹配不上；
     且库里留着撤岗时用户会看到一个「可以投递」的完整页面，sweep 覆盖率比一般源更要紧。

## 🚩 这个源最大的坑：翻页参数是 `pageIndex`，不是 `pageNum`
`pageNum` 会被**静默忽略**——HTTP 200、`total` 正确、`info.pageIndex` 恒为 1、
每页回的是**同一批** 20 条。2026-09-18 实测：按 pageNum 翻 8 页拿回 160 行，去重后只有 20 个
positionId，而 total=152。换成 `pageIndex` 后 152/152 抓全、零重复。
`pageSize` 同样有坑：**服务端硬顶 20**（请求 50/100/200 一律回 20，`info.pageSize` 也回 20），
小于 20 才如实生效。
→ 所以本 adapter 的收尾判据是「这一页有没有带来**新的 positionId**」+「够不够自报 total」，
  而不是「本页条数 < pageSize」（后者在这个接口上永远为假，会无限翻页）。

## 逐岗 jd_url
`https://careers.midea.com/schoolOut/post/details?positionId={positionId}`
—— 站点自己拼的：`goPostDetails: e => window.open(router.resolve({name:"postDetails",
   query:{positionId: e.positionId}}).href, "_blank")`（`/schoolOut/assets/index-*.js`），
路由表里 `{path:"post/details", name:"postDetails"}` 挂在 `/schoolOut` 应用下。
⚠️ 用 `positionId`（项目×岗位的那一行），**不是** `projectPositionId`（岗位模板）——
两个字段同时存在且值不同，取错就是坏链；详情接口也只认 positionId。

## 归属
单租户官方门户，一条源一家公司，company 由 sources 行给定 —— 列表里的
`orgUnitList[].localUnitName`（事业部，如「新能源事业部」）只进 summary、**不写 company**，
故不存在「拿检索结果当归属声明」那类张冠李戴面（对比 iguopin 的集团展开）。
"""
import json
import logging
from typing import Dict, List, Optional

import httpx

import normalizer

from .base import BaseAdapter, RawJob, resolve_list_cap

logger = logging.getLogger(__name__)

_HOST = "https://careers.midea.com"
# employementCategory：对方自己的枚举（1=校招 / 4=实习），只转述不自己判三桶。
_CATEGORY_CAMPUS = 1
_CATEGORY_INTERN = 4
# projectType：9=日常实习生通道、7=校企合作实习、1=校园招聘、5=博士校园招聘（live 实测）。
_PROJECT_TYPE_DAILY_INTERN = "9"


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MideaCampusAdapter(BaseAdapter):
    name = "midea_campus"
    company_name = "美的集团"
    official_hosts = ("careers.midea.com",)

    PROJECT_API = f"{_HOST}/backend/school/position/common/project/list"
    LIST_API = f"{_HOST}/backend/school/position/common/position/list"
    DETAIL_API = f"{_HOST}/backend/school/position/common/position/details"
    DETAIL_URL = f"{_HOST}/schoolOut/post/details?positionId={{position_id}}"
    # 服务端硬顶 20，请求更大只是白填（见模块注释）。写 20 是为了让「页数 = ceil(total/20)」对得上。
    PAGE_SIZE = 20
    MAX_PAGES = 200

    def should_skip(self, source_url: str) -> Optional[str]:
        # `/` 会 302 到 `/schoolOut`，HEAD 跟随重定向后 200（2026-09-18 实测），默认实现不会跳过。
        # 仍显式返回 None：这是公开 JSON 后端，对 SPA 壳做 HEAD 预检没有判别力，白花 5s。
        return None

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": f"{_HOST}/schoolOut/post",
        }

    def _projects(self, client: httpx.Client) -> List[dict]:
        resp = client.get(self.PROJECT_API, params={"status": 1})
        resp.raise_for_status()
        payload = resp.json() or {}
        projects = payload.get("data")
        if not isinstance(projects, list):
            # 「HTTP 200 + 结构不对」必须抛错记 failed，不许安静返 0 个项目。
            raise RuntimeError(
                f"midea_campus: project/list 结构异常（code={payload.get('code')!r}）")
        return [p for p in projects if isinstance(p, dict) and p.get("projectRuleId")]

    def _drain_project(self, client: httpx.Client, project: dict, budget: int):
        """翻完一个项目，返回 (rows, reported_total, drained)。

        ⚠️ 末页判据 = 「这一页有没有带来新的 positionId」+「够不够自报 total」。
        绝不用「本页条数 < pageSize」——服务端把 pageSize 顶到 20，正常页恒等于 20，
        这个判据在这里永远为假；而 `pageIndex` 一旦写错成 `pageNum`，每页都回同一批，
        只有「没带来新 id」能当场把它抓出来（这正是 2026-09-18 踩到的坑）。
        """
        prid = project["projectRuleId"]
        seen: Dict[str, dict] = {}
        total: Optional[int] = None
        for page in range(1, self.MAX_PAGES + 1):
            resp = client.post(self.LIST_API, json={
                "projectRuleId": prid,
                "pageIndex": page,
                "pageSize": self.PAGE_SIZE,
            })
            resp.raise_for_status()
            payload = resp.json() or {}
            block = payload.get("data")
            if not isinstance(block, dict):
                raise RuntimeError(
                    f"midea_campus: position/list 结构异常（code={payload.get('code')!r} "
                    f"project={project.get('projectRuleName')!r}）")
            if total is None:
                total = _int_or_none(block.get("total"))
            rows = block.get("data") or []
            if not rows:
                break
            fresh = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                pid = str(row.get("positionId") or "").strip()
                if not pid or pid in seen:
                    continue
                row["_project"] = project
                seen[pid] = row
                fresh += 1
            if fresh == 0:
                # 翻页没前进（参数被忽略 / 对方回了同一页）→ 停，并如实记「没抓全」。
                logger.warning("%s: 项目 %s 第 %d 页零新岗，停止翻页（got=%d total=%s）",
                               self.name, project.get("projectRuleName"), page, len(seen), total)
                break
            if total is not None and len(seen) >= total:
                break
            if len(seen) >= budget:
                logger.warning("%s: 项目 %s 撞单源条数上限 %d，未抓全",
                               self.name, project.get("projectRuleName"), budget)
                break
        drained = total is not None and len(seen) >= total
        return list(seen.values()), total, drained

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        budget = resolve_list_cap(8000)

        rows: List[dict] = []
        totals: List[int] = []
        drained: List[bool] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers=self._headers()) as client:
            projects = self._projects(client)
            if not projects:
                # 项目全部结束是合法空态（对方页面会写「招聘已结束」），不抛错。
                logger.info("%s: project/list 返回 0 个在跑项目", self.name)
                self.reported_total = 0
                self.fetch_complete = True
                return json.dumps({"rows": []}, ensure_ascii=False)
            for project in projects:
                try:
                    got, total, ok = self._drain_project(client, project, budget)
                except Exception:
                    if not rows:
                        raise      # 第一个项目就炸 = 接口坏了，交上层记 failed
                    logger.warning("%s: 项目 %s 抓取失败，保留已抓 %d 条",
                                   self.name, project.get("projectRuleName"), len(rows))
                    drained.append(False)
                    continue
                rows.extend(got)
                if total is not None:
                    totals.append(total)
                drained.append(ok)

        # ⚠️ 完整性**逐项目判**，不拿「去重后条数 >= 各项目 total 之和」
        # （CLAUDE.md「渠道总数之和当分母 = 造假缺口」）。美的这四个项目实测 positionId 互不重叠
        # （535 行 535 个唯一 id），但「今天不重叠」不构成「永远不重叠」的依据 ——
        # 只要哪天重叠一条，和式判据就会永久为 False，list-absence 之类的下游会跟着出事。
        self.reported_total = sum(totals) if len(totals) == len(drained) and totals else None
        self.fetch_complete = bool(drained) and all(drained)
        return json.dumps({"rows": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("rows") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs: List[RawJob] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            position_id = str(row.get("positionId") or "").strip()
            dto = row.get("projectPositionDto") or {}
            title = str(row.get("projectPositionName")
                        or dto.get("positionName") or "").strip()
            if not position_id or not title:
                continue
            location = str(row.get("workPlaceCode") or "").strip()
            if not _in_source_regions(location, getattr(self, "regions", None)):
                continue
            jd_url = self.DETAIL_URL.format(position_id=position_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=_first_city(location) or None,
                job_type=_job_type_of(row),
                summary=_summary_of(row),
                jd_url=jd_url,
                apply_url=jd_url,
            ))
        return jobs


def _in_source_regions(location: str, regions) -> bool:
    """后置地区过滤，判据跟着 `sources.regions` 走（默认 {CN}）。

    **「只丢能确证在范围外的岗」**——同 `avature._in_regions` 的 facet 源分支、
    同 `sf_express_campus._in_source_regions`：单租户的中国区校招门户，host 即地区保证，
    后置过滤是防漏网不是准入门槛；`derive_country_code` 返回 None 是「证据不足」，
    不是「证据相反」。

    📊 2026-09-18 live 实测影响面（美的校招 535 行，逐条看过、不是抽样）：
      严格判据丢 1 个 —— `8a5eeb5c…887351`「生产计划专员」工作地是**昆山市**，
      江苏的县级市，而 `CHINA_CJK_PLACE_MARKERS` 按设计只收到地级市
      （CLAUDE.md「中文地名归属：宁可漏判，不可错杀」——县区级不收是刻意的）。
      放开后 0 个被丢，535 行的地点取值里没有任何一个 `derive_country_code` 落在 CN 之外。
    ⚠️ 台湾红线不受影响（`台北市` 识别得出 TW → 仍走严格分支被丢）。
    """
    if normalizer.location_in_source_regions(location, regions):
        return True
    return normalizer.derive_country_code(location) is None


def _first_city(location: str) -> str:
    """`workPlaceCode` 是「上海市,佛山市」这种逗号串（字段名叫 code，值其实是中文城市名）。
    与 sf_express_campus / lenovo 同口径：筛选取第一个，全部城市写进 summary。"""
    return (location.split(",")[0] or "").strip()


def _job_type_of(row: dict) -> str:
    """只转述对方自己的枚举，三桶分类交给 normalizer。"""
    project = row.get("_project") or {}
    category = _int_or_none(row.get("employementCategory")
                            if row.get("employementCategory") is not None
                            else project.get("employementCategory"))
    if category == _CATEGORY_INTERN:
        # 日常实习生通道单独给「日常实习」——normalizer 认得它，且实习专区分得更细。
        if str(project.get("projectType") or "").strip() == _PROJECT_TYPE_DAILY_INTERN:
            return "日常实习"
        return "实习"
    if category == _CATEGORY_CAMPUS:
        return "校园招聘"
    return "校园招聘"


def _summary_of(row: dict) -> Optional[str]:
    """抬头写**项目名**，因为届别硬信号就在项目名里（「2027届美的星校园招聘」）。

    🚩 **绝不能把 `numberOfSessions` 拼进 summary**。它是项目的「入口届别」，
    对两个实习通道来说是 2026，而项目自报的毕业时间窗是 2026-01-01 ~ 2028-12-31 ——
    写进去会让 `extract_grad_class` 把一批面向 26/27/28 届的实习岗**全部标成 2026 届**。
    CLAUDE.md 的口径是「只认硬信号，抽不出返回 None，绝不猜」：把往届标成当季比留白更伤。
    项目名里没有届别的（日常实习生招聘通道 / 校企合作实习招聘通道）就让届别留白。
    """
    project = row.get("_project") or {}
    dto = row.get("projectPositionDto") or {}
    parts = []
    head = []
    name = str(project.get("projectRuleName") or "").strip()
    if name:
        head.append(f"招聘项目：{name}")
    category = str(row.get("recruitCategoryName") or dto.get("largeTypeName") or "").strip()
    if category:
        head.append(f"岗位类别：{category}")
    units = []
    for unit in (row.get("orgUnitList") or []):
        if isinstance(unit, dict):
            label = str(unit.get("localUnitName") or "").strip()
            if label and label not in units:
                units.append(label)
    if units:
        head.append("用人单位：" + "、".join(units[:4]))
    cities = [c.strip() for c in str(row.get("workPlaceCode") or "").split(",") if c.strip()]
    if len(cities) > 1:
        head.append("工作城市：" + "、".join(cities))
    if head:
        parts.append(" · ".join(head))

    duty = str(dto.get("jobResponsibility") or "").strip()
    requirement = str(dto.get("jobRequirement") or "").strip()
    if duty:
        parts.append(f"【岗位职责】\n{duty}")
    if requirement:
        parts.append(f"【任职要求】\n{requirement}")
    return "\n".join(parts).strip() or None
