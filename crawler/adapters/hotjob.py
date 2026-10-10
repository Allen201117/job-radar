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
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import PageResult, RawJob, exc_brief, paginate_all, resolve_detail_cap
from .playwright_base import PlaywrightAdapter

logger = logging.getLogger(__name__)


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_form(payload: dict) -> dict:
    return (payload.get("data") or {}).get("pageForm") or {}


def _post_id(post) -> str:
    return str(post.get("postId") or post.get("id") or "").strip() if isinstance(post, dict) else ""


def _fits_one_page(page_form: dict, row_count: int) -> bool:
    """这一页自报的 dataCount 说「全在这一页里了」。"""
    count = _int_or_none(page_form.get("dataCount"))
    return count is not None and count <= row_count


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
        return self._gate(source_url)[0]

    def _gate(self, source_url: str):
        """两道门的判定本体。返回 (跳过原因或 None, 两道门是否都真探到了答复)。

        should_skip 只用前一个：探测失败一律放行。后一个给「据此改库」的调用方（migrate_wt_rows_to_wecruit）：
        没探到答复时「没说跳过」不等于「渠道发布了」。
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
                ), True

        # 门 2：本渠道发布了吗（渠道级）
        payload = self._probe_json(
            f"{self._origin}{self._CONDITION_API}{self._suite_key}",
            {"recruitType": self._recruit_type}, source_url)
        if isinstance(payload, dict) and "data" not in payload:
            return (
                f"wecruit channel not published (recruitType={self._recruit_type}): "
                "search/condition returned no data — portal pages hang, jd_url unusable"
            ), True
        return None, isinstance(cfg, dict) and isinstance(payload, dict)

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
        # 翻页参数是 currentPage（pageIndex/pageNo 均被忽略，恒回第 1 页）；pageSize 第 2 页起听我们的、封顶 20。
        #
        # ⚠️ 第 1 页不听我们传的 pageSize（2026-10-10 立）：回多少条一页、自报的 totalPage 按哪种页长算，
        #    都由对方定，同一个租户不同时刻还会变（当天实测有 1 / 10 / 12 / 15 / 20 / 50 六种）。所以：
        #    · 第 1 页自报的 totalPage 不采信，从第 2 页的响应起才认（那是按我们要的 20 条一页算的）。
        #      ❌ 中国物流集团社招第 1 页回 50 条一页、totalPage=3，旧逻辑按 20 条一页翻 3 页就停：
        #         115 个岗拿到 60 个还记抓全（同一轮广西柳工 489 → 200、335 → 140）。
        #    · 第 1 页不足 20 条一页时，第 1、2 页之间有断档，由 _fill_first_page_gap 补。
        #    · 「本页不足一页 = 末页」对这个接口不成立（第 1 页 12 条不代表后面没有）→ 传 page_size=1
        #      关掉 paginate_all 的短页收尾，靠第 2 页起的 totalPage / 空页收尾。
        #    📊 全部 147 个启用源改前改后背靠背各跑一遍（只抓列表）：62 个源多拿到 887 个岗、没有一个源少拿；
        #       改前有 61 个源拿到的岗少于自报总数却记抓全。
        collected: List[dict] = []
        seen: set = set()   # 已收下的岗位 id
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def post_page(current_page: int, page_size: int) -> dict:
                resp = client.post(api, data={
                    "recruitType": self._recruit_type,
                    "currentPage": current_page,
                    "pageSize": page_size,
                })
                resp.raise_for_status()
                return resp.json()

            def keep(payload: dict, at: Optional[int] = None) -> list:
                """收下一页：别的页已经给过的岗就地去掉，放进 collected（at = 插在第几个）。
                返回这一页原有的全部行——翻页收尾要看整页，整页都是重复的也不等于翻到头了。"""
                page_form = _page_form(payload)
                rows = page_form.get("pageData") or []
                fresh = []
                for row in rows:
                    post_id = _post_id(row)
                    if post_id and post_id in seen:
                        continue
                    if post_id:
                        seen.add(post_id)
                    fresh.append(row)
                page_form["pageData"] = fresh
                collected.insert(len(collected) if at is None else at, payload)
                return rows

            def fetch_page(current_page: int) -> PageResult:
                payload = post_page(current_page, self.api_page_size)
                page_form = _page_form(payload)
                rows = keep(payload)
                total = _int_or_none(page_form.get("total"))
                if total is None:
                    total = _int_or_none(page_form.get("totalCount"))
                if total is None:
                    total = _int_or_none(page_form.get("count"))
                if current_page > 1:
                    total_pages = _int_or_none(page_form.get("totalPage"))
                else:
                    # 第 1 页自报的 totalPage 不采信；只有它自己的 dataCount 说「这一页就装完了」才就此收尾。
                    total_pages = 1 if _fits_one_page(page_form, len(rows)) else None
                return PageResult(items=rows, total=total, total_pages=total_pages)

            _, total, complete = paginate_all(
                fetch_page,
                page_size=1,
                first_page=1,
                max_pages=self.api_max_pages,
                logger=None,
                label=f"hotjob:{self._suite_key}",
            )
            gap_filled = self._fill_first_page_gap(post_page, keep, collected[0])
            posts = [row for payload in collected for row in _page_form(payload).get("pageData") or []]
            # 分母取各页自报 dataCount 的最大值；抓完按去重后的岗位数对它，不够就不记抓全。
            counts = [c for c in (_int_or_none(_page_form(payload).get("dataCount")) for payload in collected)
                      if c is not None]
            if counts:
                self.reported_total = max(counts)
            else:
                self.reported_total = max(total, len(seen)) if total is not None else None
            self.fetch_complete = (
                complete and gap_filled
                and (self.reported_total is None or len(seen) >= self.reported_total))
            # 列表无 JD 正文（workContent/serviceCondition 全空 → summary 空）；逐岗调 listPositionDetail
            # 补正文（复用同一带 Referer/Origin 的 client）。capped；单岗失败该岗无摘要、不影响入库。
            self._enrich_details(client, [p for p in posts if isinstance(p, dict)])
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _fill_first_page_gap(self, post_page, keep, first_payload) -> bool:
        """补上第 1 页和第 2 页之间的断档：补回来的页经 keep 收在第 1 页后面。返回 False = 没补成。

        ❌ 每页都按 20 要：财通证券校招第 1 页只回 12 条（自报 pageSize=12；新会话连打 4 次、
           传 20 / 15 / 10 / 不传，回的都是 12），第 2 页按 20 条一页算从第 21 条起 → 第 13~20 条
           谁都没取到，64/72 却记抓全。兴业证券校招第 1 页回 15 的那几轮 42 → 37。
        ✅ 第 1 页不足 20 条一页时，按它自报的页长把第 2 页（页长很小时到凑满 20 条为止）再要一遍，
           正好盖住断档，与第 2 页重叠的行去掉。按 20 条一页的各页照旧要、只多这一两个请求，拿到的岗只多不少。
        🚫 别改成「后面各页都跟着第 1 页的页长翻」：页数上限按页数记，页一变小，大租户反而翻不完
           （同一天对拍：TCL / 特变电工社招 1,192 → 720，亿纬锂能 1,108 → 900）。
        ⚠️ 没治的：第 1 页偶尔连口径都不同（迪卡侬校招有一轮第 1 页自报 dataCount=380、15 条一页，
           一小时后同一请求是 712、20 条一页；那 712 行的 externalKey 去重正好 380）。那种时候第 1 页的行
           与后面各页可能不是同一份列表，这里只做到按 dataCount 的最大值如实记「没抓全」。
        """
        first = _page_form(first_payload)
        row_count = len(first.get("pageData") or [])
        served = _int_or_none(first.get("pageSize")) or 0
        if not 0 < served < self.api_page_size or row_count < served or _fits_one_page(first, row_count):
            return True   # 第 1 页不比 20 条一页短 / 没装满（后面没有了）/ 一页就装完了：没有断档
        fill_pages = -(-self.api_page_size // served)   # 向上取整：按第 1 页的页长，前 20 条占几页
        try:
            for page in range(2, fill_pages + 1):
                keep(post_page(page, served), at=page - 1)
        except Exception as exc:
            logger.warning("hotjob:%s: 第 1 页断档没补成（%s）", self._suite_key, exc_brief(exc))
            return False
        return True

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

    # ⛔ endDate 只有 longTermRelease == 1 时才是截止日，判不出的一律不写（2026-10-10 立）。
    # ❌ 现象：直接把 endDate 写成 deadline → 库里 622 行在招岗「截止日已过」，当天却都还在官网列表里，
    #    日期最早到 2019 年。
    # ✅ 根因：平台自己的前端是 `0 === longTermRelease ? "长期发布" : format(endDate)`（「下线时间」一栏）。
    #    =0 的岗 endDate 只是系统填的数：3000-01-01 / 发布日+12 个月 / 远未来占位 / 早已过去的日期，
    #    以及每晚 02:10 前后被续成「当时 + 7 天」的滚动值（库里更早存下、今天仍在列的 78 行逐行变了）。
    #    真渲染 3 个详情页逐个对上：=0 且 endDate 为 2027-09-10 / 3000-01-01 的写「长期发布」，
    #    =1 的写「2026-10-22 23:59:59下线」；另一个 =0 且 endDate 在 2023 年的详情页照样有「立即投递」。
    #    当天全量 20,626 个岗：=0 的 17,655 个里 749 个 endDate 已过去仍在列；=1 的 2,971 个没有一个是过去的，
    #    库里更早存下、今天仍在列的 =1 行 109 行里 108 行日期没变。
    # ⚠️ 没写不等于库里清掉：deadline 在 jobs_db._PRESERVE_IF_EMPTY 里，新值为空时保留旧值。
    #    所以 =0（官网明写「长期发布」）另外带 deadline_absent=True，由 run.py 5d 清掉库里的旧日期
    #    ——岗位从「指定下线时间」改回「长期发布」就靠它撤回。标记缺失 / 不认识 = 判不出，不写也不清。
    @staticmethod
    def _deadline(post: dict) -> Optional[str]:
        if str(post.get("longTermRelease")).strip() != "1":
            return None
        return normalizer.coerce_iso_date(post.get("endDate"))

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
            deadline=self._deadline(post),
            deadline_absent=str(post.get("longTermRelease")).strip() == "0",
        )
