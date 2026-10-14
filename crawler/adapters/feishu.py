"""
飞书/Lark 招聘平台通用层（{company}.jobs.feishu.cn）。

与字节同平台：拦截 /api/v1/search/job/posts，岗位在 data.job_post_list，
详情页 https://{host}/index/position/{id}/detail。一套适配覆盖蔚来/小鹏/地平线/小米。

取数：httpx 直拉 posts API，按 data.count 翻全（limit=50），每个门户都带 `website-path` 头（见类注释）。
接口没打通就让这一轮记失败；原先的浏览器抓包 + 重放链已删（重放不带门户头，见 fetch 的注释）。
"""
import json
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx

import normalizer
from .base import (DEFAULT_LIST_CAP, RawJob, RepetitionBrake, exc_brief,
                   resolve_list_cap)
from .playwright_base import PlaywrightAdapter, _UA

logger = logging.getLogger(__name__)


def _titles_of(rows):
    """喂给 RepetitionBrake 的标题序列；飞书 job_post 的标题恒在 `title`（见 _map）。"""
    return [str((r or {}).get("title") or "") for r in (rows or []) if isinstance(r, dict)]


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# 职能类别名自己读起来像招聘类型时，不和招聘类型标签拼在一起（见 compose_job_type）。读 job_type 的地方都是对整串
# 做子串匹配、各有各的先后：sourceDeclaredCategory 是 实习 > 社招 > 校招，lib/insight-derive.ts 的 classifyRecruitment
# 和 discovery.recruitment_category 是 实习 > 校招 > 社招 —— 类别名叫「实习生」「全职」「校园大使」时会压过后面的标签。
# intern 另用整词（normalizer.INTERN_WORD_RE）：裸子串会把 International / Internal / Internet 一起丢掉。
_RECRUIT_WORD_RE = re.compile(
    r"实习|社招|社会招聘|全职|experienced|professional|full.?time"
    r"|校招|校园|应届|管培|管理培训生|留学生|毕业生|campus|graduate|new\s?grad|entry.?level", re.I)


def declared_recruit_label(recruit_type) -> str:
    """列表每行自带的 `recruit_type`（对方自报的招聘类型）→ 交给分类器的标签；没有可用的返回空串。

    ❌ 2026-10-12 前 `_map` 没用这个字段，job_type 只取 job_category（职能类别），招聘类型全靠分类器读标题 / 正文猜：
       自报社招的被正文里的「优秀应届生亦可」「24-25 届毕业生」「负责校园招聘」判成校招；自报校招的门户
       （智元 `campusrecruitment`、小米新零售）标题正文链接里都没有校招字样，判成社招。
       两个方向的行数、逐源清单、改前改后对拍 → docs/crawler-adapter-notes.md 的 feishu.py 条目。
    ✅ 字段两层：上一层 社招 / 校招，下一层 全职·外包·劳务·顾问·实习 / 正式·实习。只取能定桶的：
         社招 > 全职·外包·劳务·顾问 → 「社招」      社招 > 实习 → 「实习」
         校招 > 正式              → 「校招」      校招 > 实习 → 不带（见下）
    🚫 下一层的「全职 / 正式」不许原样带：读侧 sourceDeclaredCategory("全职") 直接返回社招（北森绝不带 Kind 同一个理由），
       「正式」它不认。下一层只用来认实习。
    🚫 「校招 > 实习」不带：一个类型下混着两种东西——蔚来把「先带薪实习、表现好发校招正式 Offer」的岗归在这里
       （标题写「校招-…」、面向应届），小米实习门户归在这里的是给在校生的实习。带成实习会把前一种挪出校招，
       带成校招会把后一种写成校招；标题写着实习的本来就由标题判实习。
    ⚠️ 社招也带（wt.py 的社招渠道刻意不带）：那边是「岗位挂在哪个渠道」，这里是对方给每个岗单独填的类型。
    ⚠️ 这里只负责如实把对方的归类搬过来，裁决仍在 lib/china-keyword-expansion.js：标题写「实习」的照旧判实习（层1），
       自报校招但写明 ≥2 年经验的照旧判社招（层2）。
    ⚠️ 名字按「包含」认，不按全等：同平台的字节租户下一层叫「暑期实习 / 日常实习」。认不出的上一层 → 空串，
       照旧按标题 / 正文判（有些租户整个不返回这个字段，也走这条路）。
    """
    if not isinstance(recruit_type, dict):
        return ""
    name = str(recruit_type.get("name") or "")
    parent = recruit_type.get("parent")
    parent_name = str(parent.get("name") or "") if isinstance(parent, dict) else ""
    intern = "实习" in name
    if "社招" in parent_name or "社会招聘" in parent_name:
        return "实习" if intern else "社招"
    if "校招" in parent_name or "校园招聘" in parent_name:
        return "" if intern else "校招"
    return ""


def compose_job_type(category: str, label: str) -> str:
    """职能类别 + 招聘类型标签（与 wt.py 同一种拼法：类别继续进检索文本，标签喂给 recruitmentCategory）。
    类别名自己读起来像招聘类型的只留标签，否则它会压过标签（见 _RECRUIT_WORD_RE）。"""
    if not label:
        return category
    if category and not (_RECRUIT_WORD_RE.search(category) or normalizer.INTERN_WORD_RE.search(category)):
        return f"{category} {label}"
    return label


# ── 共享租户：同一个岗挂在两家公司的门户上，只归一家 ─────────────────────────────────────────
# host → {让出的门户: 归属门户}。「让出的门户」那条源抓的时候剔掉也挂在「归属门户」上的岗，库里已有的由
# run.py 按 retire_jd_urls 下架成 removed（可逆）。不剔 = 同一个岗两张卡、两个公司名（同北森孪生门户）。
#   · global-intco（租户名只写「英科」，集团共用；2026-10-12 三个门户翻全、逐岗带头读状态）：
#       index  = 英科再生社会招聘官网 87 岗      757263 = 英科医疗社会招聘官网 326 岗（英科医疗官网「社会招聘」链到这里）
#     两边都挂、两边都在线的 17 个：14 个淮北「-凯泽」（安徽凯泽新材料，英科医疗持股 65%，公告 2026-051）、
#     九江安环主管（江西英科医疗厂址）、国毅 / 公益基金会运营各 1 → 归英科医疗。index ∩ 840753（英科医疗校招）= 0。
# ⚠️ 登记在代码里、源的启停在库里：停用归属门户那条源之前先撤掉这里的登记，否则让出的岗两边都没人接。
_SHARED_TENANT_PORTAL_OWNER = {
    "global-intco.jobs.feishu.cn": {"index": "757263"},
}


def source_portal(source_url: str) -> str:
    """source_url 指向哪个子门户（路径首段）；主门户（根路径 / index / position）返回空串。
    抓取（_bind_website_path）与核名（discover_domestic.feishu_portal_home）共用这一条规则。"""
    segments = [seg for seg in (urlparse(source_url or "").path or "").split("/") if seg]
    first = segments[0] if segments else ""
    return "" if first in ("", "index", "position") else first


def _should_continue(before, after, chunk, total, page_size):
    """还该不该翻下一页。

    ⚠️ 末页判据**不能**用「本页条数 < pageSize」：站点限流/抖动时会回短页，一个瞬时短页就把
    整源停在半路（同一条在 beisen 上实测把中国交建从 2565 掐到 800）。改用「这一页有没有带来
    新岗位」（before/after 是去重后的行数）；只有在没有分母可判时才退回短页当自然末页。"""
    if after <= before:
        return False
    if total:
        return True
    return len(chunk) >= page_size


class FeishuRecruitAdapter(PlaywrightAdapter):
    """飞书招聘门户通用层。

    ## 子门户（website_path）—— 校招/实习岗藏在这里，2026-09-04 才挖出来
    同一个租户可以挂多个门户，**用哪个门户由请求头 `website-path` 决定**，与 URL 路径同名：
      · 不带该头（主门户）= 社招全集      · `campus` = 校园招聘
      · `internship` = 实习              · `newretailing` 等 = 租户自定义专项
    小米实测：不带 1894 / campus 764 / internship 554 / newretailing 121，四个池子互不相同。

    ⚠️ 此前判「飞书私有部署没有校招板块」是**错的**，错在试错了维度：当时对比的是
    `storefront_id` 两个取值（返回完全相同的 1887 条），而真正的开关是这个请求头。
    ⚠️ `portal_type` 也不是开关：带 `website-path: campus` 时传 2 或 6 都返回同一批 764 条。

    ## 主门户（source_url 是 /index/position）：抓「公开门户」，不抓「不带头的全集」（2026-09-23 更正）
    ❌ 旧结论（2026-09-04）：「`website-path: index` 是更小的子集（蔚来 2055 → 1801），所以主门户不带头」。
       错在只比了**条数**，没问多出来那批在公开页上是不是活的。
    ✅ 实测（133 个飞书系源逐岗全量核，见 crawler/test_feishu_httpx.MainPortalTest 的碑文）：不带头多出来的
       岗在公开门户详情页上显示「该职位已下线」——详情接口带 `website-path: <门户>` 时
       `channel_online_status=0`；而带门户头取到的列表，逐岗在该门户上都是 1。
       ⚠️ `channel_online_status` 是**按门户**算的：同一个岗不带头读 1、带 index 头读 0（浏览器实开=已下线）。
    所以主门户 = 租户首页自报的门户（`website_info.path`，多数是 index）∪ index 门户，都**带头**取，
    每个岗的 jd_url 用它实际挂着的那个门户前缀（`post["_portal"]`）。

    新增一个租户的校招源**不需要写代码**：插一条 source_url 指向 `https://{host}/campus/position`
    的 sources 行即可，本类按路径自动切门户、切详情模板。
    """

    host = ""  # 子类设置，如 nio.jobs.feishu.cn
    website_path = ""  # 由 source_url 派生；""=主门户（社招）
    intercept_match = "/api/v1/search/job/posts"
    posts_keys = ("data.job_post_list", "job_post_list")
    _PAGE_SIZE = 50    # 单页拉取数（接口实测 limit=50 稳定返回，远超站点默认 10）
    # 单租户抓取条数上限（env CRAWL_MAX_JOBS 可整体调档）。旧的 600 硬顶让蔚来(2055)/小鹏(1552)/
    # 哪吒(1127)/智元(904)/安克(848)/物美(785)/理想(754) 每轮都只抓到前 600 条
    # （2026-09-04 crawl_runs 实测），且这七家全部 ≤8000，抬档一次就能抓全。
    _MAX_JOBS = DEFAULT_LIST_CAP
    _HTTPX_TIMEOUT = 20

    # list-absence 探活：feishu posts API 返**全量在招岗**（非夹带已关闭岗），且本类按 count 翻全；
    # 故抓全时「上次在、这次没了」可判下架。仅 fetch_complete=True 时生效（见 run.py 兜底）。
    supports_absence_liveness = True
    fetch_complete = False  # 每次 fetch 末尾置位：是否抓到完整列表（翻到 count、未撞 _MAX_JOBS 上限）
    _yielded: tuple = ()    # 这一轮让给同租户另一个门户的行（见 _SHARED_TENANT_PORTAL_OWNER）

    def __init__(self):
        self.official_hosts = (self.host,)
        self.website_path = ""
        self._detail_prefix_override = ""
        self._main_portal = False   # source_url 指向主门户（/index/position 或根路径）→ 走 _httpx_fetch_main
        self._apply_website_path("")
        self.fetch_complete = False
        self.reported_total = None
        self.coverage_stop_reason = None
        self._prefetched = None

    def _apply_website_path(self, path: str) -> None:
        """按子门户重算详情模板与入口页。path="" = 主门户（社招），走 /index/…（历史行为不变）。

        ⚠️ host 必须从 **official_hosts 优先** 取：`FeishuGenericAdapter` 的 host 是空串、
        真实 host 由 `_bind_host` 放进 official_hosts。早先这里直接用 self.host，结果把它
        `_bind_host` 刚算好的 detail_template 覆写成 `https:///index/position/{id}/detail`
        → jd_url 全废 → 68 个通用飞书源**解析出 0 岗却仍标 fetch_complete=True**
        （2026-09-04 实测拓竹 reported=165/parsed=0）。这正是 CLAUDE.md 立碑的
        「0 岗 + 自称抓全」组合，回归测试见 test_feishu_httpx.WebsitePathTest。
        """
        self.website_path = path or ""
        host = (self.official_hosts[0] if getattr(self, "official_hosts", None) else "") or self.host
        if not host:
            return   # host 还没绑定（通用类的 __init__ 阶段）→ 什么都别改，等 _bind_host 之后再来
        # ⚠️ 修好的前缀必须扛得住这里的重算：`fetch()` 会再调一次 `_bind_website_path`，
        # 没有 override 时它会把 `_repair_detail_template` 刚修好的模板覆写回 `index`
        # —— should_skip 不跳了、jd_url 却仍然 404（2026-09-04 端到端实测抓到这个回归）。
        prefix = getattr(self, "_detail_prefix_override", "") or path or "index"
        self.detail_template = f"https://{host}/{prefix}/position/{{id}}/detail"
        self.list_urls = [
            f"https://{host}/{prefix}/position",
            f"https://{host}/",
        ]

    def _bind_website_path(self, source_url: str) -> None:
        """从 source_url 的首个路径段派生子门户（见 website_path 的类注释）。

        `index` / 根路径 = 主门户：website_path 留空、标 `_main_portal`，由 `_httpx_fetch_main`
        按租户自报门户 ∪ index **带头**去取（见类注释「主门户」一节；旧的「不带头 = 全集」已推翻）。
        """
        portal = source_portal(source_url)
        self._main_portal = not portal
        self._apply_website_path(portal)

    def _resolve_host(self, source_url: str) -> str:
        """httpx 直拉用的 host：子类有 self.host；通用类 fetch 前已 _bind_host → official_hosts[0]。"""
        if self.official_hosts and self.official_hosts[0]:
            return self.official_hosts[0]
        return urlparse(source_url).netloc

    def _httpx_fetch(self, host: str) -> Tuple[List[dict], Optional[int], bool]:
        """纯 httpx 直拉 posts API（feishu_probe 已实证冷启动可达：真实 Chrome UA、无签名、无 cookie）。
        翻页到 data.count，返回 (rows, total, reached)。reached=至少一次拿到合法 data dict（用于区分
        '真 0 岗' 与 'httpx 没打通'——前者照常返回空、后者 fetch 抛错记失败）。daily-crawl 无 Playwright 也能跑。
        主门户源（`_main_portal`）走 `_httpx_fetch_main`：自报门户 ∪ index，都带 website-path 头。"""
        self._yielded = ()
        if getattr(self, "_main_portal", False) and not self.website_path:
            rows, total, reached = self._httpx_fetch_main(host)
        else:
            rows, total, reached = self._httpx_fetch_portal(host, self.website_path)
        if reached and host in _SHARED_TENANT_PORTAL_OWNER:
            rows, total = self._yield_to_owner_portal(host, rows, total)
        return rows, total, reached

    def _row_portal(self, post: dict) -> str:
        """这一行是从哪个门户的列表里取到的（查的是哪个池子；链接前缀另见 _jd_url）。"""
        return (post or {}).get("_portal") or self.website_path or "index"

    def _jd_url(self, post: dict) -> str:
        """这一行的详情链接：主门户的行用它实际挂着的门户前缀（`_portal`），其余用详情模板。"""
        pid = str((post or {}).get("id") or (post or {}).get("code") or "").strip()
        portal = (post or {}).get("_portal")
        if portal:
            host = (self.official_hosts[0] if getattr(self, "official_hosts", None) else "") or self.host
            return f"https://{host}/{portal}/position/{pid}/detail"
        return self.detail_template.format(id=pid)

    @property
    def retire_jd_urls(self) -> tuple:
        """让给归属门户的岗的链接：run.py 把库里已有的下架成 removed。
        读的时候才拼、与 _map 同一个拼法——详情模板可能在 should_skip 里被修过，早拼会对不上库里的链接。"""
        return tuple(self._jd_url(p) for p in self._yielded)

    def _yield_to_owner_portal(self, host: str, rows: List[dict],
                               total: Optional[int]) -> Tuple[List[dict], Optional[int]]:
        """见 _SHARED_TENANT_PORTAL_OWNER：剔掉也挂在归属门户上的岗，把它们的链接记进 retire_jd_urls。

        归属门户的列表没取全 → 抛错、本轮不写。静默全收就是一岗两行；按半截列表剔，漏掉的那些同样是一岗两行。
        不在登记表里的门户（含归属门户自己那条源）零额外请求、原样返回。"""
        owners = _SHARED_TENANT_PORTAL_OWNER.get(host) or {}
        if getattr(self, "_main_portal", False):
            # 主门户源取的是「租户首页自报的门户 ∪ index」。登记时自报的就是让出的那个门户；对方哪天把首页换成
            # 别的门户（最坏是归属门户本身），这条源会把别家的岗整批收进来 → 认不出的门户一律不写，等人重新核。
            stray = sorted({self._row_portal(p) for p in rows} - set(owners))
            if stray:
                raise RuntimeError(
                    f"feishu shared tenant {host}: main source now lists portal(s) {stray} that are not "
                    "registered as yielding; re-verify the tenant's portal layout before writing")
        needed = sorted({owners[self._row_portal(p)] for p in rows if self._row_portal(p) in owners})
        if not needed:
            return rows, total
        owned = {}
        for owner in needed:
            for _attempt in range(2):   # 归属门户列表要翻好几页，抖一下就整源失败不值当：重取一次再判
                o_rows, o_total, o_reached = self._httpx_fetch_portal(host, owner)
                if o_reached and o_rows and o_total is not None and len(o_rows) >= o_total:
                    break
            else:
                # 空列表同样按没取全算：归属门户瞬时回 0 岗时照单全收，让出的岗会被写回来。
                raise RuntimeError(
                    f"feishu shared tenant {host}: owner portal {owner} list incomplete "
                    f"({len(o_rows)}/{o_total}); skip this run to avoid one job under two companies")
            owned[owner] = {str((r or {}).get("id") or "") for r in o_rows}
        kept, dropped = [], []
        for post in rows:
            owner = owners.get(self._row_portal(post))
            pid = str((post or {}).get("id") or "")
            (dropped if owner and pid and pid in owned[owner] else kept).append(post)
        self._yielded = tuple(dropped)
        if dropped:
            logger.info("%s: %s 让出 %d 个也挂在门户 %s 上的岗，留 %d 个",
                        self.name, host, len(dropped), "/".join(needed), len(kept))
        return kept, (total - len(dropped) if total is not None else None)

    def _httpx_fetch_main(self, host: str) -> Tuple[List[dict], Optional[int], bool]:
        """主门户：取租户首页自报的门户（`website_info.path`）与 index 两个公开门户，合并去重。

        每行打上 `_portal`（它挂在哪个门户上），`_map` 用它拼 jd_url——同一个租户两个门户
        都开着时（莉莉丝 career 119 / index 57），岗必须用它真在线的那个门户前缀，否则详情页「已下线」。
        返回的 total：两个门户都翻全且首页自报了门户 → 合并后的条数（= 抓全）；否则 None（不许
        list-absence 据此判撤岗——拿不到自报门户时我们不能确定手里的是不是这个租户的全部公开岗）。"""
        declared = self._discover_detail_prefix(host)
        # 自报门户就是这个租户唯一有效的 URL 前缀（见 _discover_detail_prefix）；详情模板跟着它走。
        # 每次都重设（拿不到就清空）：probe.probe_one 共用单例，上一家的前缀不许漏到下一家。
        self._detail_prefix_override = declared or ""
        self._apply_website_path("")
        portals = [p for p in dict.fromkeys([declared, "index"]) if p]
        merged: List[dict] = []
        seen: set = set()
        reached_any = False
        complete = bool(declared)
        for portal in portals:
            # 自报门户之外的 index 门户**可以不存在**（小马智行 / 商汤 / 海底捞：接口回 -9000003 site not exist）
            # → 当空门户算，不当「没打通」，否则这些租户永远标不了抓全。自报门户本身不许这样放过。
            rows, total, reached = self._httpx_fetch_portal(host, portal, missing_ok=(portal != declared))
            if not reached:
                complete = False
                continue
            reached_any = True
            if total is None or len(rows) < (total or 0):
                complete = False
            for post in rows:
                pid = str((post or {}).get("id") or "")
                if pid and pid not in seen:
                    seen.add(pid)
                    merged.append({**post, "_portal": portal})
        return merged, (len(merged) if complete else None), reached_any

    _SITE_NOT_EXIST = -9000003   # 带了一个租户没有的 website-path：200 + code=-9000003 "site not exist"，data=None

    def _httpx_fetch_portal(self, host: str, website_path: str,
                            missing_ok: bool = False) -> Tuple[List[dict], Optional[int], bool]:
        """取一个门户的列表（website_path="" = 不带头，仅用于 `_main_portal` 之外的历史调用方）。
        missing_ok：门户不存在（-9000003）时按「空门户」返回 ([], 0, True)，而不是「没打通」。"""
        rows: List[dict] = []
        seen: set = set()
        total: Optional[int] = None
        reached = False
        offset = 0
        prefix = website_path or "index"
        headers = {"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9",
                   "Content-Type": "application/json",
                   "portal-channel": "saas-career", "portal-platform": "pc",
                   "Referer": f"https://{host}/{prefix}/position"}
        if website_path:
            headers["website-path"] = website_path
        try:
            with httpx.Client(timeout=self._HTTPX_TIMEOUT, follow_redirects=True, headers=headers) as cli:
                cap = resolve_list_cap(self._MAX_JOBS)
                brake = RepetitionBrake()
                while len(rows) < cap:
                    body = {"keyword": "", "limit": self._PAGE_SIZE, "offset": offset,
                            "job_category_id_list": [], "tag_id_list": [], "location_code_list": [],
                            "subject_id_list": [], "recruitment_id_list": [], "portal_type": 2,
                            "job_function_id_list": [], "storefront_id": ""}
                    try:
                        r = cli.post(f"https://{host}/api/v1/search/job/posts", json=body)
                        jj = r.json()
                    except Exception as exc:
                        logger.warning("%s: %s 门户 %s offset=%d 抓取失败，保留已抓 %d 条：%s",
                                       self.name, host, prefix, offset, len(rows), exc_brief(exc))
                        break
                    data = (jj or {}).get("data") if isinstance(jj, dict) else None
                    if not isinstance(data, dict):
                        if missing_ok and isinstance(jj, dict) and jj.get("code") == self._SITE_NOT_EXIST:
                            return [], 0, True
                        break
                    reached = True
                    if total is None:
                        total = data.get("count") or 0
                    chunk = data.get("job_post_list") or []
                    if not isinstance(chunk, list) or not chunk:
                        break
                    before = len(rows)
                    for post in chunk:
                        pid = str((post or {}).get("id") or "")
                        if pid and pid not in seen:
                            seen.add(pid)
                            rows.append(post)
                    if total and len(rows) >= total:
                        break
                    # 重复度刹车：批量发布源（同一个岗 × N 家门店）翻再多页也只是同质副本。
                    # 放在「抓全」判定之后 → 能抓全的源一律抓全。刹停 → fetch_complete 天然为 False。
                    if brake.observe(_titles_of(rows[before:])):
                        self.coverage_stop_reason = "repetition_brake"
                        logger.info("%s: 重复度刹车 —— 连续 %d 条没有新角色，停在 %d/%s 条 host=%s",
                                    self.name, brake.stall_rows, len(rows), total, host)
                        break
                    if not _should_continue(before, len(rows), chunk, total, self._PAGE_SIZE):
                        break
                    offset += self._PAGE_SIZE
        except Exception as exc:
            logger.warning("%s: %s 门户 %s 抓取中断，保留已抓 %d 条：%s",
                           self.name, host, prefix, len(rows), exc_brief(exc))
            return rows, total, reached
        return rows, total, reached

    def _detail_portal_closed(self, host: str, post: dict) -> bool:
        """只抽一岗确认租户详情门户；请求异常一律放行，避免误杀。"""
        pid = str((post or {}).get("id") or (post or {}).get("code") or "").strip()
        if not pid:
            return False
        portal = (post or {}).get("_portal")
        url = (f"https://{host}/{portal}/position/{pid}/detail" if portal
               else self.detail_template.format(id=pid))
        try:
            response = httpx.get(
                url,
                timeout=self._HTTPX_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _UA,
                         "Referer": f"https://{host}/{portal or self.website_path or 'index'}/position"},
            )
            return response.status_code in (404, 410)
        except Exception:
            return False

    def _discover_detail_prefix(self, host: str) -> str:
        """从租户首页自报的 `website_info.path` 取真实门户路径（拿不到返回空串）。

        飞书租户首页内嵌 `"website_info":{…,"path":"exp"}`，那是这个租户**唯一有效的
        URL 前缀**；`index` 只是我们的历史默认值，并非所有租户都认。
        """
        try:
            html = httpx.get(
                f"https://{host}/",
                timeout=self._HTTPX_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _UA},
            ).text
        except Exception:
            return ""
        m = re.search(r'"website_info":\{.*?"path":"([^"]{1,32})"', html, re.S)
        return m.group(1) if m else ""

    def _repair_detail_template(self, host: str, post: dict) -> bool:
        """`index` 前缀的详情页 404 时，改用租户自报的门户前缀再试一次；成功则重绑模板。

        为什么需要（2026-09-04 live 实测，两家实锤）：
          · 商汤 sensetime —— `/index/position` 连列表页都 404，整源被 should_skip 跳掉，
            84 个社招岗一个都进不来；真实前缀是 `exp`，换上后详情 5/5 返 200。
          · 海底捞 haidilao —— 列表正常（119 岗），但 `/index/position/{id}/detail` 全 404，
            于是 36 个在招岗带着**必然打不开的 jd_url** 躺在库里（数据质量红线：
            jd_url 准确性高于一切）；真实前缀是 `072846`，换上后返 200。

        ⚠️ **只改详情模板，不动 `website_path`**：这两件事必须解耦。海底捞的 `072846`
        门户列表返回 0 岗（那批岗没挂在该 storefront 上），而不带 `website-path` 头的默认
        列表有 119 岗——把发现到的前缀顺手当成子门户塞进请求头，列表会当场从 119 掉到 0。
        前缀只是 URL 路由，与「查哪个池子」是两回事。

        ⚠️ 修不好才跳过：能修就别跳。跳过 = 整源 0 岗，代价远大于多发两个请求。
        ⚠️ 2026-09-23 起主门户源已经「一律先查自报 path」（`_httpx_fetch_main`），本函数对主门户只剩兜底意义；
           子门户源（campus/internship…）仍靠它。旧注释说「别改成一律先查自报 path」，依据是
           「/index/ 详情本来就通」——但「详情页 200」不等于「岗在线」（SPA 壳恒 200，内容是「已下线」）。
        """
        prefix = self._discover_detail_prefix(host)
        if not prefix or prefix == (self.website_path or "index"):
            return False
        pid = str((post or {}).get("id") or (post or {}).get("code") or "").strip()
        if not pid:
            return False
        candidate = f"https://{host}/{prefix}/position/{{id}}/detail"
        try:
            response = httpx.get(
                candidate.format(id=pid),
                timeout=self._HTTPX_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": _UA, "Referer": f"https://{host}/{prefix}/position"},
            )
        except Exception:
            return False
        if response.status_code != 200:
            return False
        self._detail_prefix_override = prefix
        self.detail_template = candidate
        return True

    def should_skip(self, source_url: str) -> Optional[str]:
        """租户详情门户关闭时整源跳过；列表 API 仍吐岗不足以证明可投。"""
        if not getattr(self, "host", "") and hasattr(self, "_bind_host"):
            self._bind_host(source_url)
        self._bind_website_path(source_url)
        host = self._resolve_host(source_url)
        if not host:
            return None
        rows, total, reached = self._httpx_fetch(host)
        if not reached:
            return None
        self._prefetched = (rows, total, reached)
        if rows and self._detail_portal_closed(host, rows[0]):
            # 先别急着判「门户关了」——多半只是我们用错了前缀（见 _repair_detail_template）。
            if self._repair_detail_template(host, rows[0]):
                return None
            return "feishu tenant detail portal closed (404/Not Found); skip source to avoid unusable jd_url"
        return None

    def fetch(self, source_url: str) -> str:
        """直拉 posts API（无浏览器，daily-crawl 4×/天可跑）。接口没打通 → 抛错，这一轮记失败、不写库。

        🚫 不回退浏览器（2026-10-14 删掉了浏览器抓包 + 重放链，别加回来）：重放列表请求**不带** `website-path` 头，
        取回的是「不带头的全集」——子门户源拿到另一个池子（与本门户列表重合 0 行却标抓全），主门户源拿到夹着
        已下线岗的全集。小米三条子门户源因此堆过 5,716 行死链；也没有哪条源靠它才抓得到。
        实测数字见 CLAUDE.md「飞书招聘的校招岗藏在 website-path 请求头后面」。"""
        self.fetch_complete = False
        self.reported_total = None
        self.coverage_stop_reason = None
        prefetched = self._prefetched
        self._prefetched = None
        self._bind_website_path(source_url)
        host = self._resolve_host(source_url)
        if host:
            rows, total, reached = prefetched or self._httpx_fetch(host)
            if reached:
                # httpx 打通（含真 0 岗）→ 直接用。complete=翻全（含 0 岗）。
                self.reported_total = _int_or_none(total)
                self.fetch_complete = (total is not None and len(rows) >= (total or 0))
                return json.dumps(
                    {"_intercepted": [{"data": {"job_post_list": rows, "count": total if total is not None else len(rows)}}]},
                    ensure_ascii=False)
        # 接口没打通 → 这一轮记失败（上层 run.py 记 failed、不写库、不跑缺席撤岗）。为什么不回退浏览器见 docstring。
        raise RuntimeError(f"{self.name}: {host or source_url} list API unreachable")

    def _map(self, post: dict) -> Optional[RawJob]:
        pid = str(post.get("id") or post.get("code") or "").strip()
        title = (post.get("title") or "").strip()
        if not pid or not title:
            return None

        # city_info 在前、city_list 其余城市在后，全部交出去（2026-10-11 前有 city_info 就只用它、否则只取
        # city_list 第一个：live 6 个租户 6,140 岗里 1,056 个列了不止一个城市）。
        names = []
        ci = post.get("city_info")
        if isinstance(ci, dict):
            names.append(ci.get("name"))
        cl = post.get("city_list")
        if isinstance(cl, list):
            names.extend(c.get("name") for c in cl if isinstance(c, dict))
        city = normalizer.join_places(names)

        category = ""
        jc = post.get("job_category")
        if isinstance(jc, dict):
            category = str(jc.get("name") or "")
        job_type = compose_job_type(category, declared_recruit_label(post.get("recruit_type")))

        desc = (post.get("description") or "").strip()
        req = (post.get("requirement") or "").strip()
        summary = (desc + ("　【职位要求】" + req if req else "")).strip() or None
        jd_url = self._jd_url(post)
        return RawJob(
            company=self.company_name, title=title, location=city or None,
            job_type=job_type or None, jd_url=jd_url, apply_url=jd_url,
            summary=summary, posted_at=normalizer.pick_publish_date(post),
        )


class FeishuGenericAdapter(FeishuRecruitAdapter):
    """飞书招聘**数据驱动**通用适配器（国内版 Workday）：host 从 source_url 动态解析，不再每家硬编码子类。
    一套覆盖所有用飞书招聘的公司（造车新势力 / 大量互联网与科技中企）。
    onboard = 加一行 sources，source_url 填该公司飞书招聘页（如 https://{tenant}.jobs.feishu.cn/index/position）。
    company 由 sources.company 兜底；岗位接口/字段/详情页格式复用 FeishuRecruitAdapter。"""
    name = "feishu"
    company_name = ""  # 由 sources.company 兜底

    def __init__(self):
        # 不在 init 固定 host —— 留到 fetch 时按 source_url 解析（见 _bind_host）。
        self.official_hosts = ()
        self.detail_template = ""
        self.list_urls = []
        self._prefetched = None

    def _bind_host(self, source_url: str):
        parsed = urlparse(source_url)
        host = parsed.netloc
        path = (parsed.path or "").strip("/")
        if path and path != "index/position":
            portal_base = "/" + path.split("/")[0]
        else:
            portal_base = "/index"
        self.official_hosts = (host,)
        self.detail_template = f"https://{host}{portal_base}/position/{{id}}/detail"
        standard_url = f"https://{host}/index/position"
        # 自定义 portal slug（如 /ponyai、/talent、/social）优先打开传入入口；标准入口保持原行为。
        if path and path != "index/position":
            self.list_urls = [f"https://{host}{portal_base}", standard_url]
        else:
            self.list_urls = [standard_url, source_url]
        return host

    def fetch(self, source_url: str) -> str:
        self._bind_host(source_url)
        return super().fetch(source_url)


class NioAdapter(FeishuRecruitAdapter):
    name = "nio_feishu"; company_name = "蔚来"; host = "nio.jobs.feishu.cn"


class XpengAdapter(FeishuRecruitAdapter):
    name = "xpeng_feishu"; company_name = "小鹏汽车"; host = "xiaopeng.jobs.feishu.cn"


class HorizonAdapter(FeishuRecruitAdapter):
    name = "horizon_feishu"; company_name = "地平线"; host = "horizon.jobs.feishu.cn"


class XiaomiAdapter(FeishuRecruitAdapter):
    name = "xiaomi_feishu"; company_name = "小米"; host = "xiaomi.jobs.f.mioffice.cn"
    # 原来这里单独覆写 _MAX_JOBS=3000「抓全小米的 ~2030 岗」。那是给一家公司打的补丁，
    # 别的租户照样卡在 600 —— 直到 2026-09-04 才量出来还有 32 个源在漏 9 万个岗。
    # 现在基类基准档就是 3000、必投公司自动抬到 8000，这条补丁不再需要（留碑不留码）。
