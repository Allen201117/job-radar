"""HotJob / wecruit 招聘站通用适配器（直连公开 listPosition 接口，零浏览器）。

典型入口（sources.source_url，{host} 为任意 hotjob.cn 子域）：
  https://{host}/{suiteKey}/pb/social.html    # 社招 society  recruitType=2
  https://{host}/{suiteKey}/pb/school.html    # 校招 campus   recruitType=1
  https://{host}/{suiteKey}/pb/interns.html   # 实习 intern   recruitType=12

页面 JS 公开调用 POST {origin}/wecruit/positionInfo/listPosition/{suiteKey}
（form: recruitType + pageIndex + pageSize），返回 data.pageForm.pageData 岗位列表。
本适配器**直接分页调用该接口**（httpx，无需无头浏览器），岗位详情页为
/{suiteKey}/pb/posDetail.html?postId={postId}&postType={society|campus|intern}。

recruitType 数值映射经各页 JS bundle（social.js / school.js / interns.js）逐一核实，
为 wecruit 平台常量（非每公司配置）：society=2 / campus=1 / intern=12。三渠道是独立入口，
逐家三条 source 分别入库，jd_url 的 postType 决定前端三桶归类（lib/china-keyword-expansion）。

注：bare 域名（如 crrc.hotjob.cn/）是 iframe 落地页，path 里无 suiteKey；真实 suiteKey 需先
POST /wecruit/common/getSLD（sld={host}）解析出 linkData.link 再取，sources 直接登记带 suiteKey 的 pb 页。
"""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import PageResult, RawJob, paginate_all, resolve_detail_cap
from .playwright_base import PlaywrightAdapter


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class HotJobAdapter(PlaywrightAdapter):
    name = "hotjob"
    company_name = ""  # 由 sources.company 兜底
    intercept_match = "/wecruit/positionInfo/listPosition/"  # 仅文档用途；fetch 直连不再拦截
    posts_keys = ("data.pageForm.pageData",)

    # 页面文件名 → (详情页 postType, 列表接口 recruitType)。recruitType 由各页 JS bundle 核实。
    _CHANNEL_BY_PAGE = {
        "social.html": ("society", 2),
        "school.html": ("campus", 1),
        "interns.html": ("intern", 12),
    }
    _LIST_API = "/wecruit/positionInfo/listPosition/"
    # 逐岗详情接口：列表 listPosition 不含 JD 正文，详情 listPositionDetail 才有 workContent/serviceCondition。
    # 接口路径 + 字段经 posDetail.js bundle 核实，POST body = postId + recruitType。
    _DETAIL_API = "/wecruit/positionInfo/listPositionDetail/"
    # 渠道发布门：前端各页 bootstrap 时读它的 data.searchDisplayItem 渲染筛选器与列表。
    _CONDITION_API = "/wecruit/suite/post/search/condition/"
    # 门户存在门：租户整站被下掉时此接口仍返 data（含 companyName 等基础信息），
    # 但缺少「后台配过站点」才会有的这几个键 —— 见 should_skip 的门 1。
    _CONFIG_API = "/wecruit/suite/config/"
    _SITE_CFG_KEYS = ("websiteTitlePicUrl", "keywords", "description")
    _DETAIL_CAP = 150    # 单源逐岗 detail 补摘要上限（覆盖绝大多数源；超大源部分覆盖，避免拖垮夜间全量）
    # 逐岗 detail 并发数：wecruit 单 host 对并发敏感（enrich_backlog 实测 8 worker 被限流、PER_HOST=3 才恢复）
    # → 保守 4（≈ 已验证安全上限，串行 150 岗 ~20s → ~5s）。若 CI 见限流(miss) 降回 3。
    _DETAIL_WORKERS = 4
    api_page_size = 20   # 接口服务端硬上限 = 20/页（pageSize 调更大也只回 20）
    api_max_pages = 60   # 每渠道安全上限（60×20=1200 岗）；靠真实 total/短页自然收尾

    def __init__(self):
        self.official_hosts = ()
        self.detail_template = ""
        self.list_urls = []
        self._suite_key = ""
        self._origin = ""
        self._recruit_type = 2

    def _bind_source(self, source_url: str):
        parsed = urlparse(source_url)
        parts = [p for p in (parsed.path or "").split("/") if p]
        suite_key = parts[0] if parts else ""
        if not suite_key:
            raise RuntimeError(f"hotjob: missing suite key in source_url={source_url}")
        self._suite_key = suite_key
        self.official_hosts = (parsed.netloc,)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self._origin = origin
        page_name = parts[2] if len(parts) > 2 else "social.html"
        post_type, recruit_type = self._CHANNEL_BY_PAGE.get(page_name, ("society", 2))
        self._recruit_type = recruit_type
        self.detail_template = f"{origin}/{suite_key}/pb/posDetail.html?postId={{id}}&postType={post_type}"
        entry = f"{origin}/{suite_key}/pb/{page_name}"
        self.list_urls = [entry]
        return suite_key

    def _probe_json(self, api: str, params: Optional[dict], referer: str):
        """探一个只读 JSON 接口。任何失败一律返回 None = 放行（宁可漏判不可错杀）。"""
        try:
            resp = httpx.get(
                api,
                params=params,
                headers={"User-Agent": self.user_agent, "Referer": referer},
                timeout=self.timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def should_skip(self, source_url: str) -> Optional[str]:
        """两道门，任一不过就整源跳过、一个岗都不入库。

        共同的坑：listPosition / listPositionDetail 这两个**数据**接口在两种情况下都照常
        返回岗位，所以纯看抓取侧一切正常，抓下来的 jd_url 却是用户永远打不开的页面
        —— 违反项目「jd_url 准确性高于一切」红线。故抓取前先探这两道门。

        门 1 · 门户是否存在（2026-09-05 加）：租户整站被下掉后，`suite/config` **仍返 data**
        （companyName / suitOrgInfoPOs / recruitTypeNameMap 等基础信息都在），但缺少
        「后台真配过站点」才会写入的 websiteTitlePicUrl / keywords / description。
        此时所有页面（列表页与逐岗 posDetail）都直接显示「官网不存在，无法继续访问!」。
        ⚠️ 这种租户**门 2 是过的**（search/condition 正常返 data），所以门 2 拦不住它 ——
        2026-09-05 live 实测 7 个这类租户、993 个 active 岗全是死链。

        门 2 · 渠道是否发布（2026-08-26 加）：wecruit 租户可**逐渠道**决定发不发布门户页面。
        前端各页 bootstrap 时要读 search/condition 的 data.searchDisplayItem，租户未发布该渠道时
        此接口只回 {"state":"200","type":"success"}（**无 data 键**），前端读 undefined 崩掉：
        列表页停在「内部处理中，请稍后再试」，逐岗 posDetail 永远转「正在加载中...」。

        两道门的判据都经 live 双向验证（命中侧逐个浏览器复核 + 判为健康的取样复核），
        方法见 [[job-radar-wecruit-channel-publication-gate]]：数据接口健康 ≠ 页面能打开。

        自愈：租户日后重开站点 / 发布该渠道，探测自然放行，无需人工改库。
        探测本身失败（网络/限流）一律放行 —— 宁可漏判不可错杀。
        """
        self._bind_source(source_url)

        # 门 1：门户存在吗（租户级）
        cfg = self._probe_json(
            f"{self._origin}{self._CONFIG_API}{self._suite_key}", None, source_url)
        if isinstance(cfg, dict):
            data = cfg.get("data")
            if not isinstance(data, dict) or not any(k in data for k in self._SITE_CFG_KEYS):
                return (
                    "wecruit portal does not exist (suite/config has no site settings): "
                    "pages show 官网不存在 — jd_url unusable"
                )

        # 门 2：本渠道发布了吗（渠道级）
        payload = self._probe_json(
            f"{self._origin}{self._CONDITION_API}{self._suite_key}",
            {"recruitType": self._recruit_type}, source_url)
        if isinstance(payload, dict) and "data" not in payload:
            return (
                f"wecruit channel not published (recruitType={self._recruit_type}): "
                "search/condition returned no data — portal pages hang, jd_url unusable"
            )
        return None

    def fetch(self, source_url: str) -> str:
        """直连公开 listPosition 接口逐页拉取（无浏览器），返回 parse() 可消费的 _intercepted 信封。"""
        self.reported_total = None
        self.fetch_complete = False
        self._bind_source(source_url)
        api = f"{self._origin}{self._LIST_API}{self._suite_key}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.list_urls[0],
            "Origin": self._origin,
        }
        # 翻页参数是 currentPage（pageIndex/pageNo 均被忽略，恒回第 1 页）；pageSize 服务端封顶 20。
        collected: List[dict] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def fetch_page(current_page: int) -> PageResult:
                resp = client.post(api, data={
                    "recruitType": self._recruit_type,
                    "currentPage": current_page,
                    "pageSize": self.api_page_size,
                })
                resp.raise_for_status()
                payload = resp.json()
                collected.append(payload)
                page_form = (payload.get("data") or {}).get("pageForm") or {}
                rows = page_form.get("pageData") or []
                total = _int_or_none(page_form.get("total"))
                if total is None:
                    total = _int_or_none(page_form.get("totalCount"))
                if total is None:
                    total = _int_or_none(page_form.get("count"))
                return PageResult(
                    items=rows,
                    total=total,
                    total_pages=_int_or_none(page_form.get("totalPage")),
                )

            posts, total, complete = paginate_all(
                fetch_page,
                page_size=self.api_page_size,
                first_page=1,
                max_pages=self.api_max_pages,
                logger=None,
                label=f"hotjob:{self._suite_key}",
            )
            self.reported_total = total
            self.fetch_complete = complete
            # 列表无 JD 正文（workContent/serviceCondition 全空 → summary 空）；逐岗调 listPositionDetail
            # 补正文（复用同一带 Referer/Origin 的 client）。capped；单岗失败该岗无摘要、不影响入库。
            self._enrich_details(client, [p for p in posts if isinstance(p, dict)])
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _enrich_details(self, client, posts):
        """逐岗 POST listPositionDetail 补 workContent/serviceCondition（列表接口没有，详情才有），
        就地写回 post（parse→_map 直接读这两字段拼 summary）。前 cap 个带 postId 的岗**并发**补全
        （_DETAIL_WORKERS 线程，单 host 限并发防限流）；单岗失败即跳过（不抛、不污染）。"""
        api = f"{self._origin}{self._DETAIL_API}{self._suite_key}"
        cap = resolve_detail_cap(self._DETAIL_CAP)
        targets = []
        for p in posts:
            if len(targets) >= cap:
                break
            if isinstance(p, dict) and str(p.get("postId") or p.get("id") or "").strip():
                targets.append(p)
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=self._DETAIL_WORKERS) as ex:
            list(ex.map(lambda p: self._enrich_one(client, api, p), targets))

    def _enrich_one(self, client, api, p):
        """单岗 detail 补 workContent/serviceCondition；网络/解析错误静默跳过（不阻断整批）。"""
        pid = str(p.get("postId") or p.get("id") or "").strip()
        try:
            resp = client.post(api, data={"postId": pid, "recruitType": self._recruit_type})
            resp.raise_for_status()
            data = resp.json().get("data") or {}
        except Exception:
            return
        if isinstance(data, dict):
            if data.get("workContent"):
                p["workContent"] = data["workContent"]
            if data.get("serviceCondition"):
                p["serviceCondition"] = data["serviceCondition"]

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        post_id = str(post.get("postId") or post.get("id") or "").strip()
        title = str(post.get("postName") or post.get("title") or "").strip()
        if not (post_id and title):
            return None
        desc = str(post.get("workContent") or post.get("description") or "").strip()
        req = str(post.get("serviceCondition") or post.get("requirement") or "").strip()
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        jd_url = self.detail_template.format(id=post_id)
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=post.get("workPlaceStr") or post.get("workPlace") or None,
            job_type=post.get("postTypeName") or post.get("recruitTypeName") or None,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post) or normalizer.coerce_iso_date(post.get("publishDate")),
            education=post.get("educationName") or post.get("educationStr") or post.get("education") or None,
            experience=post.get("workYearName") or post.get("workExperience") or None,
            deadline=normalizer.coerce_iso_date(post.get("endDate")),
        )
