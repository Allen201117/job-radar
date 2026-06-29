"""
中国本土 ATS / 企业官网招聘站通用浏览器适配器（Tier-2，SPA 拦截）。

覆盖三大类「各行各业公司」来源，一套代码 + 一行 sources 记录即可扩源：
  - moka     : Moka（{tenant}.mokahr.com / app.mokahr.com）—— 大量消费/互联网/制造公司在用
  - beisen   : 北森（*.zhiye.com / *.italent.cn / careers.*）—— 大型国企/集团在用
  - company_spa : 通用企业官网 SPA —— 仅放行站点自有接口里**带真实 per-job URL** 的岗位

合规与质量（遵守 CLAUDE.md 数据质量优先级）：
  - 只加载官方公开招聘页，拦截站点**自己**发起的岗位列表接口响应；不破签名、不调私有接口、低频。
  - jd_url 优先用接口返回的**真实 per-job 链接**；仅 moka/beisen 这类已知 URL 形态才用模板兜底拼。
  - company_spa 不猜 URL：post 里没有可用 per-job 链接的行直接丢，由 normalizer 质量门再兜一层。

host / tenant 从每个 source 的 source_url 动态解析，因此**同一 adapter 覆盖任意租户公司**。
playwright 仅在 fetch() 内惰性导入。
"""
import json
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _first_str(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _city_of(post: dict) -> str:
    for k in ("cityName", "city", "workCity", "location", "workPlace", "address",
              "city_name", "work_city", "locationName", "LocNames", "LocName", "Location"):
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            name = v.get("name") or v.get("cityName") or v.get("text")
            if isinstance(name, str) and name.strip():
                return name.strip()
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                name = first.get("name") or first.get("cityName")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return ""


class ChinaSpaAdapter(PlaywrightAdapter):
    """中国本土 SPA 招聘站通用基类：从 source_url 动态解析 host，启发式抽取岗位字段。"""

    # 子类可设详情链接模板（含 {host} {id}）；为空表示「只接受接口里的真实 URL，不拼模板」。
    detail_template: str = ""
    company_name = ""  # 由 sources.company 兜底填充

    def fetch(self, source_url: str) -> str:
        # 记录本次源的 origin / host / 门户前缀，供 _map 拼接相对链接与详情路由。
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        # 门户前缀 = 列表页路径去掉最后一段（section）。北森详情路由 = {origin}{prefix}/zwxq?jobAdId=
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        # 必须每次绑定到当前 source_url：本类实例在 run.py/probe.py 是**共享单例**，
        # 用 `if not self.list_urls` 会让首个源的 URL 粘住，后续源全去抓首个源 → 张冠李戴（B 公司入了 A 的岗位）。
        self.list_urls = [source_url]
        return super().fetch(source_url)

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口里直接给的 per-job 链接（最可靠）
        raw = _first_str(post, ("detailUrl", "jobUrl", "positionUrl", "url",
                                "link", "href", "applyUrl", "detail_url", "job_url"))
        if raw:
            if raw.startswith("http"):
                return raw
            return urljoin(getattr(self, "_origin", "") + "/", raw.lstrip("/"))
        # 2) 已知 ATS 形态才用模板兜底（company_spa 不设模板 → 返回空 → 丢弃）
        if self.detail_template and job_id:
            return self.detail_template.format(host=getattr(self, "_host", ""), id=job_id)
        return ""

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        job_id = _first_str(post, ("id", "jobId", "positionId", "code", "postId",
                                   "job_id", "position_id", "uuid", "Id", "JobAdId"))
        title = _first_str(post, ("title", "name", "jobTitle", "positionName",
                                  "job_title", "position_name", "jobName", "JobAdName"))
        if not title:
            return None
        jd_url = self._resolve_url(post, job_id)
        if not jd_url:
            return None

        summary = _first_str(post, ("description", "jobDescription", "responsibility",
                                    "requirement", "duty", "jobDesc", "content",
                                    "job_description")) or None
        if not summary:
            # 北森 GetJobAdPageList 用大写 Duty(职责)/Require(要求)（live 实测 2026-06-10），
            # 此前因大小写不匹配整体丢弃 → beisen 万级岗位 summary 全空。两段拼接（同 feishu/hotjob 口径）。
            duty = _first_str(post, ("Duty",))
            require = _first_str(post, ("Require", "Requirement"))
            summary = (duty + ("\n【任职要求】\n" + require if require else "")).strip() or None
        job_type = _first_str(post, ("jobType", "recruitType", "categoryName",
                                     "positionType", "type")) or None
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=_city_of(post) or None,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            salary_text=_first_str(post, ("Salary", "salary", "salaryText", "salaryName")) or None,
            posted_at=normalizer.pick_publish_date(post),
        )


_MOKA_FLAGS = ("火热招聘", "急", "热", "新", "HOT", "NEW", "hot", "new")
_MOKA_NOISE = ("全职", "兼职", "实习", "|", "立即投递", "在招职位", "分享")
_MOKA_CITY_RE = re.compile(r"[一-龥]{2,}(?:省|市|区)")


def _parse_moka_card(text: str):
    """从 Moka 岗位卡 innerText（含换行）解析 (location, title)。

    各租户卡片排版不一，但统一规律：标题在首行（首行若是「急/火热招聘」等角标则取次行，
    或角标粘连在标题前时剥掉）；城市是后续带 省/市/区 的短行（'上海市'/'广东·珠海市'/'上海市·黄浦区'）。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None, ""
    # 标题：首行；首行是纯角标时取次行
    if lines[0] in _MOKA_FLAGS:
        title = lines[1] if len(lines) > 1 else ""
        rest = lines[2:]
    else:
        title = lines[0]
        rest = lines[1:]
    # 剥掉粘连在标题前的角标（如 '急客户端c++研发' / '火热招聘中学…'）
    for f in ("火热招聘", "急", "热", "新"):
        if title.startswith(f) and len(title) > len(f):
            title = title[len(f):].strip()
            break
    # 城市：后续行里首个「带 省/市/区 的短行」（跳过日期/类型/噪声）
    location = None
    for ln in rest:
        if ln.startswith("发布") or ln in _MOKA_NOISE:
            continue
        if len(ln) <= 12 and _MOKA_CITY_RE.search(ln):
            location = ln
            break
    return location, title


class MokaAdapter(PlaywrightAdapter):
    """Moka 招聘（{tenant}.mokahr.com / app.mokahr.com）—— 大量消费/互联网/游戏私企在用。

    Moka 列表接口的数据是**加密的**（响应体 data 为密文 + necromancer，反爬），拦截 JSON 拿不到岗位明文；
    故改为**渲染后解析 DOM**：页面 JS 解密后岗位卡渲染为 `a[href*='#/job/{uuid}']`，
    per-job 详情链接 = `{base}#/job/{uuid}`（hash 路由，可直达岗位）。
    source_url 填某公司 Moka 公开招聘页（如 https://app.mokahr.com/apply/shein/2933）。
    """

    name = "moka"
    company_name = ""  # 由 sources.company 兜底
    wait_ms = 5500
    # 不同 Moka 页岗位列表挂在不同 hash 子路由，逐个试取岗位最多的
    _routes = ("#/jobs", "", "#/campus/jobs", "#/positions")
    # Moka 列表每页仅渲染 ~30 个岗位卡，其余在「sd-Pagination」分页组件后面（非 ant，非滚动加载）。
    # 不翻页只能拿首页，岗位多的租户被截断（如李宁 32/176、SHEIN 34/747）。逐页点「下一页」累加全量。
    _page_cap = 60  # 30/页 → 封顶约 1800 岗，足够覆盖最大租户（SHEIN ~25 页）且防失控
    # Moka 自有分页「下一页」按钮：class 前缀稳定（带 build hash 后缀），末页加 disabled 属性。
    _next_sel = "button[class*='sd-Pagination-forward']"
    _cards_js = ("els => els.map(e => ({href: e.getAttribute('href'),"
                 " text: (e.innerText || '').trim()}))")

    def _collect_all_pages(self, page) -> List[dict]:
        """从当前已渲染的列表路由翻页累加全量岗位卡，按 href 去重。

        逐次点「sd-Pagination 下一页」直到：无该按钮（单页租户不渲染分页器）/
        按钮 disabled（末页）/ 连续无新卡 / 触达页数封顶。
        """
        union: dict = {}
        no_growth = 0
        for _ in range(self._page_cap):
            cards = page.eval_on_selector_all("a[href*='#/job/']", self._cards_js)
            before = len(union)
            for c in cards:
                href = c.get("href") or ""
                if href and href not in union:
                    union[href] = c
            no_growth = no_growth + 1 if len(union) == before else 0
            if no_growth >= 2:  # 连续两页零新增 → 停（防呆）
                break
            nxt = page.query_selector(self._next_sel)
            if nxt is None:
                break  # 单页租户：Moka 不渲染分页器
            cls = (nxt.get_attribute("class") or "").lower()
            if "disabled" in cls or nxt.get_attribute("disabled") is not None:
                break  # 末页：下一页按钮 disabled
            try:
                nxt.scroll_into_view_if_needed(timeout=2000)
                nxt.click(timeout=2500)
                page.wait_for_timeout(1800)  # 等下一页岗位卡渲染
            except Exception:
                break
        return list(union.values())

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        base = source_url.split("#")[0]
        best: List[dict] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(user_agent=self.user_agent, locale="zh-CN").new_page()
            try:
                # 先按首页岗位数挑出正确的列表路由（不同 Moka 页挂不同 hash 子路由），
                # 再在该路由上翻页累加全量（多数租户岗位都在 #/jobs，空路由很快返回单页）。
                best_route = None
                best_first = -1
                for route in self._routes:
                    try:
                        page.goto(base + route, wait_until="networkidle", timeout=35000)
                        page.wait_for_timeout(self.wait_ms)
                        first = page.eval_on_selector_all("a[href*='#/job/']", self._cards_js)
                        if len(first) > best_first:
                            best_first, best_route = len(first), route
                        if best_first >= 3:
                            break  # 命中有岗位的路由即可，无需续试空路由
                    except Exception:
                        continue
                if best_route is not None:
                    try:
                        page.goto(base + best_route, wait_until="networkidle", timeout=35000)
                        page.wait_for_timeout(self.wait_ms)
                        best = self._collect_all_pages(page)
                    except Exception:
                        best = []
            finally:
                browser.close()
        return json.dumps({"_base": base, "cards": best}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (ValueError, TypeError):
            return []
        base = data.get("_base", "")
        out: List[RawJob] = []
        seen = set()
        for c in data.get("cards", []):
            m = re.search(r"#/job/([\w-]+)", c.get("href") or "")
            if not m:
                continue
            location, title = _parse_moka_card(c.get("text", ""))
            if not title:
                continue
            jd_url = f"{base}#/job/{m.group(1)}"
            if jd_url in seen:
                continue
            seen.add(jd_url)
            out.append(RawJob(
                company=self.company_name or "",
                title=title,
                location=location,
                job_type=None,
                summary=None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,
            ))
        return out


# 北森详情路由按租户缓存（host → 详情页 base，如 https://chinalife.zhiye.com/custom/zwxq）。
# 启动时从 crawler/beisen_routes.json 预载（onboarding/probe 探测后落盘提交）→ 每日爬取直接读，不再现场探测。
# 未命中缓存的 host 才现场 render-verify 探测一次（慢，仅新源），结果写回内存缓存。
import json as _json
import os as _os

_BEISEN_ROUTES_FILE = _os.path.join(_os.path.dirname(__file__), "..", "beisen_routes.json")


def _load_beisen_routes() -> dict:
    try:
        with open(_BEISEN_ROUTES_FILE, encoding="utf-8") as f:
            return {k: v for k, v in _json.load(f).items()}
    except (OSError, ValueError):
        return {}


_BEISEN_ROUTE_CACHE: dict = _load_beisen_routes()


def beisen_httpx_ready(source_url: str) -> bool:
    """该 beisen 源能否走纯 httpx（= 详情路由已缓存，能拼 jd_url 不开浏览器）。
    未缓存（含老版 SSR / 异构租户，无 GetJobAdPageList JSON）→ False → 必须留浏览器档。
    run.py `_partition_by_tier` 用它做 **per-source** 分档：缓存了的 beisen 进 httpx 快车道，没缓存的留浏览器。"""
    try:
        host = urlparse(source_url or "").netloc
    except Exception:
        return False
    return bool(host) and bool(_BEISEN_ROUTE_CACHE.get(host))
# 北森详情页常见路由名（zwxq=职位详情拼音；不同租户配置不同：chinalife=zwxq、横店/杰瑞=detail…）
_BEISEN_DETAIL_NAMES = ("zwxq", "detail", "jobdetail", "positiondetail", "jobDetail")

# —— 老版 SSR（C 型）专用：列表页 HTML 直出 per-job 锚点，无 JSON 接口可拦 ——
# 详情页路径因租户而异（中核=szxq、BOE 校招=details2021…），param 多为 jobId(数字)/adId。
_BEISEN_SSR_DETAIL_PATHS = ("szxq", "szzwxq", "xzxq", "campusxq", "zwxq", "details2021",
                            "overseadetail", "detail", "jobdetail", "szzp", "xq", "positiondetail")
_BEISEN_SSR_PARAMS = ("jobId", "adId", "jobAdId")
# 从 SSR 列表页抽取 per-job 锚点（jobId/adId/jobAdId=数字或 GUID + 标题文本），去重。
_BEISEN_SSR_ANCHOR_JS = r"""
() => {
  const out=[], seen=new Set();
  for (const a of document.querySelectorAll(
        "a[href*='jobId='],a[href*='adId='],a[href*='jobAdId=']")) {
    const href=a.getAttribute('href')||'';
    const m=href.match(/(?:jobId|jobAdId|adId)=([^&#]+)/i);
    if(!m) continue;
    const id=decodeURIComponent(m[1]);
    const name=(a.innerText||a.textContent||'').trim();
    if(!name || name.length<3 || name.length>60) continue;  // 跳过登录/注册等短文本
    if(seen.has(id)) continue; seen.add(id);
    out.push({id, name});
  }
  return out.slice(0,120);
}
"""


class BeisenAdapter(ChinaSpaAdapter):
    """北森招聘（*.zhiye.com / *.italent.cn / 自有 careers 域名，由北森承载）。

    source_url 填某公司北森招聘页（如 https://chinalife.zhiye.com/custom/intern）。
    北森列表接口 GetJobAdPageList 不含 per-job URL；详情页 query 恒为 `?jobAdId={Id}`，但 **path 因租户而异**
    （chinalife=/custom/zwxq、横店=/campus/detail…）。因此 fetch 时**逐租户自动探测**详情路由：
    用首个岗位 render-verify 候选 path（替换末段 / 追加 × 常见详情页名），命中「渲染该岗且 job-specific」
    者即为真路由，按 host 缓存。探不到则不拼 URL（丢弃，杜绝坏链）。
    """

    name = "beisen"
    intercept_matches = ("GetJobAdPageList", "JobAd", "Position", "position", "Recruit", "recruit", "/api/")
    detail_template = ""

    _ID_FIELDS = ("Id", "id", "jobAdId", "JobAdId", "code")
    # GetJobAdPageList 分页：北森列表页只发**一次** count-probe 请求拿总数（多数租户 PageSize=1，
    # 个别 PageSize=10），渲染时不会自己翻页到底。我们捕获该 POST、用站点自己的 PortalId+session
    # **服务端重放**并翻页到收齐 Count 条（接口实测支持 PageSize=50）。
    _PAGE_SIZE = 50      # 单页拉取数（接口实测 50 稳定返回）
    _MAX_JOBS = 600      # 单租户上限（防超大央企一次拉爆；600=12 页足够覆盖绝大多数）

    # list-absence 探活：beisen GetJobAdPageList 返全量在招岗 + 本类翻全 → 抓全时列表缺席=下架（同 feishu）。
    supports_absence_liveness = True
    fetch_complete = False

    def fetch(self, source_url: str) -> str:
        """httpx-first（2026-06-28 实测 6/6 租户冷 httpx 可达）：HTML 抽 PortalId → GetJobAdPageList 翻页，
        **零浏览器**。但 jd_url 需本租户详情路由（点击捕获，按 host 缓存到 beisen_routes.json）——故仅当
        **route 已缓存**时走 httpx（能拼 jd_url）；route 未缓存的租户回退浏览器（顺带探+缓存 route，由
        harvest_beisen_routes.py 持久化）。daily-crawl 无 Playwright → httpx 路径自给，回退浏览器会抛由上层记 failed。"""
        self.fetch_complete = False
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        self.list_urls = [source_url]

        route = _BEISEN_ROUTE_CACHE.get(self._host)
        if route:  # route 已缓存 → 尝试纯 httpx（拿到列表即能拼 jd_url，不开浏览器）
            try:
                j = self._httpx_fetch(source_url)
            except Exception:
                j = None
            if j:
                self._detail_route = route
                return j

        # route 未缓存 / httpx 没打通 → 回退浏览器（探+缓存 route），再不行落 SSR
        try:
            list_json = self._fetch_paginated(source_url)
        except RuntimeError:
            return self._fetch_ssr(source_url)
        self._detail_route = _BEISEN_ROUTE_CACHE.get(self._host)
        if self._detail_route is None and self._host not in _BEISEN_ROUTE_CACHE:
            self._detail_route = self._discover_detail_route(source_url, list_json)
            _BEISEN_ROUTE_CACHE[self._host] = self._detail_route  # 命中或 None 都缓存，避免重复探测
        return list_json

    def _httpx_fetch(self, source_url: str) -> Optional[str]:
        """纯 httpx 抓 beisen 列表（无浏览器）：GET 列表页 HTML 抽 PortalId → POST GetJobAdPageList 翻全。
        Category 由 url 路径判（campus/intern→校招"2"，否则社招"1"）；端点大小写两试（/api/Jobad/ 与 /api/JobAd/）。
        返回 {"_intercepted":[{"Data":[...],"Count":N}]}（与浏览器路径同 shape，parse/_map 不变）或 None（没打通）。"""
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        # Category=[] = 不按招聘类别过滤 = 返该租户**全部**岗（社招+校招+实习+内部）。2026-06-29 实测：单类别
        # （由 url 路径猜社招/校招）会漏抓另一类别 → 那些 live 岗在 list-absence 里被误判「缺席」=误杀活岗
        # （changan 社招[1]=185 但全部[]=204、leapmotor [1]=829 vs []=921）。取全部 → live 是 DB 的超集 →
        # absence 只判真正撤掉的岗，绝不误杀；freshness 也更全。dedup 靠 canonical_jd_url（同岗一行）。
        ua = PlaywrightAdapter.user_agent
        rows: List[dict] = []
        total: Optional[int] = None
        endpoints = (f"{origin}/api/Jobad/GetJobAdPageList", f"{origin}/api/JobAd/GetJobAdPageList")
        ep_ok = None
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": ua}) as cli:
            try:
                html = cli.get(source_url).text
            except Exception:
                return None
            m = re.search(r'PortalId"\s*:\s*"([0-9a-fA-F-]+)"', html or "")
            portal_id = m.group(1) if m else ""
            index = 0
            while len(rows) < self._MAX_JOBS:
                body = {"PageIndex": index, "PageSize": self._PAGE_SIZE, "Category": [],
                        "KeyWords": "", "SpecialType": 0, "PortalId": portal_id,
                        "DisplayFields": ["Category", "Kind", "LocId", "PostDate", "WorkWeChatQrCode"]}
                jj = None
                for ep in ((ep_ok,) if ep_ok else endpoints):
                    try:
                        resp = cli.post(ep, json=body, headers={"Content-Type": "application/json"})
                        cand = resp.json()
                    except Exception:
                        continue
                    if isinstance(cand, dict) and isinstance(cand.get("Data"), list):
                        jj, ep_ok = cand, ep
                        break
                if not isinstance(jj, dict):
                    break
                if total is None:
                    total = jj.get("Count") or jj.get("Total") or 0
                chunk = jj.get("Data") or []
                if not isinstance(chunk, list) or not chunk:
                    break
                rows.extend(chunk)
                if total and len(rows) >= total:
                    break
                if len(chunk) < self._PAGE_SIZE:
                    break
                index += 1
        if not rows:
            return None
        self.fetch_complete = (total is not None and len(rows) >= (total or 0))
        return json.dumps({"_intercepted": [{"Data": rows, "Count": total or len(rows)}]}, ensure_ascii=False)

    def _fetch_paginated(self, source_url: str) -> str:
        """渲染列表页，捕获其 GetJobAdPageList POST 请求，然后用站点自身 session 服务端翻页重放，
        把全部岗位收齐成单个合成响应 {"_intercepted":[{"Data":[...all...],"Count":N}]}（下游 shape 不变）。

        为何不复用 super().fetch()：列表页**只发一次** count-probe（PageSize 常为 1），被动拦截只能拿到 1 条。
        这里主动重放才是收全岗位的正解；捕获到 POST 即翻页，捕获不到（GET 式/异构租户）则回退被动拦截 (super)。

        命中规则：仅当真捕获到 GetJobAdPageList 的 POST 且至少重放出 1 条岗位才返回合成响应；
        否则回退 super().fetch()（保留原拦截链），再不行由 fetch() 落到 SSR。"""
        # ChinaSpaAdapter.fetch 会绑定 _origin/_host/_portal_prefix/list_urls，这里手动复刻同样绑定。
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        self.list_urls = [source_url]

        from playwright.sync_api import sync_playwright

        captured: dict = {}
        passive: List[dict] = []
        matchers = self.intercept_matches

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=PlaywrightAdapter.user_agent,
                viewport={"width": 1366, "height": 900}, locale="zh-CN")
            page = ctx.new_page()

            def on_request(req):
                # 捕获列表页自己发的 GetJobAdPageList POST（含 PortalId/Category/DisplayFields），供重放。
                if "GetJobAdPageList" in req.url and req.method == "POST" and not captured:
                    try:
                        captured["url"] = req.url
                        captured["body"] = json.loads(req.post_data or "{}")
                        captured["ct"] = (req.headers or {}).get("content-type", "application/json")
                    except Exception:
                        pass

            def on_response(resp):
                # 被动拦截兜底（与 PlaywrightAdapter.fetch 同口径）：捕获不到 POST 时仍有数据可用。
                try:
                    if matchers and not any(m in resp.url for m in matchers):
                        return
                    if "json" in (resp.headers or {}).get("content-type", "").lower():
                        passive.append(resp.json())
                except Exception:
                    pass

            page.on("request", on_request)
            page.on("response", on_response)
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=self.pw_timeout)
                page.wait_for_timeout(self.wait_ms)
            except Exception:
                pass

            rows: List[dict] = []
            total = None
            if captured.get("url") and isinstance(captured.get("body"), dict):
                body = dict(captured["body"])
                hdrs = {"content-type": captured.get("ct") or "application/json"}
                index = 0
                while len(rows) < self._MAX_JOBS:
                    body["PageSize"] = self._PAGE_SIZE
                    body["PageIndex"] = index
                    try:
                        r = page.request.post(captured["url"], data=json.dumps(body), headers=hdrs)
                        jj = r.json()
                    except Exception:
                        break
                    if not isinstance(jj, dict):
                        break
                    if total is None:
                        total = jj.get("Count") or jj.get("Total") or 0
                    chunk = jj.get("Data") or []
                    if not isinstance(chunk, list) or not chunk:
                        break
                    rows.extend(chunk)
                    if total and len(rows) >= total:
                        break
                    if len(chunk) < self._PAGE_SIZE:  # 末页不足一页 → 收完了
                        break
                    index += 1
            browser.close()

        if rows:
            return json.dumps({"_intercepted": [{"Data": rows, "Count": total or len(rows)}]},
                              ensure_ascii=False)
        if passive:  # 没捕获到 POST/重放为空 → 回退被动拦截链（异构租户兼容）
            return json.dumps({"_intercepted": passive}, ensure_ascii=False)
        # 啥都没有 → 交给 fetch() 落到 SSR 分支
        raise RuntimeError(
            f"{self.name}: anti_bot_blocked — 未捕获 GetJobAdPageList POST 也无被动拦截 host={self._host}")

    def _fetch_ssr(self, source_url: str) -> str:
        """老版 SSR（C 型）：列表页 HTML 直出 per-job 锚点（无 JSON 接口）。
        渲染列表页 → 抽 jobId 锚点 → 探测本租户详情路径（render-verify，按 host 缓存）→ 拼 jd_url。
        探不到详情路径则 raise（记 partial_success，不入坏链）。"""
        from playwright.sync_api import sync_playwright

        origin = getattr(self, "_origin", "")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(user_agent=PlaywrightAdapter.user_agent, locale="zh-CN").new_page()
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4500)
                anchors = [a for a in (page.evaluate(_BEISEN_SSR_ANCHOR_JS) or [])
                           if a.get("id") and a.get("name")]
                if not anchors:
                    raise RuntimeError(
                        f"beisen: SSR 列表页无 jobId/adId 锚点（非老版 SSR 或被反爬）host={self._host}")
                route = _BEISEN_ROUTE_CACHE.get(self._host)
                if not (isinstance(route, dict) and route.get("ssr_path")):
                    route = self._discover_ssr_route(page, origin, anchors)
                    if route:
                        _BEISEN_ROUTE_CACHE[self._host] = route
                if not (isinstance(route, dict) and route.get("ssr_path")):
                    raise RuntimeError(f"beisen: SSR 详情路径探测失败 host={self._host}")
                path, param = route["ssr_path"], route["ssr_param"]
                jobs, seen = [], set()
                for a in anchors:
                    jd = f"{origin}/{path}?{param}={a['id']}"
                    if jd in seen:
                        continue
                    seen.add(jd)
                    jobs.append({"title": a["name"], "jd_url": jd, "location": a.get("location")})
                return json.dumps({"_ssr_jobs": jobs}, ensure_ascii=False)
            finally:
                browser.close()

    def _discover_ssr_route(self, page, origin: str, anchors: list):
        """老版 SSR 详情路径探测：用首个锚点 id × 候选 path/param render-verify，命中即 {ssr_path,ssr_param}。"""
        a_id = str(anchors[0]["id"])
        a_name = anchors[0]["name"]
        b_name = next((x["name"] for x in anchors[1:] if x["name"] != a_name), None)
        for path in _BEISEN_SSR_DETAIL_PATHS:
            for param in _BEISEN_SSR_PARAMS:
                url = f"{origin}/{path}?{param}={a_id}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=12000)
                    t = (page.title() or "")
                    if "not found" in t.lower() or t.strip() in ("404", "404 Not Found"):
                        continue  # 路径不存在 → 跳过昂贵的渲染等待
                    page.wait_for_timeout(3000)
                    if self._is_job_detail(page, a_name, b_name):
                        return {"ssr_path": path, "ssr_param": param}
                except Exception:
                    continue
        return None

    def parse(self, html: str):
        try:
            data = json.loads(html)
        except (ValueError, TypeError):
            return []
        if isinstance(data, dict) and "_ssr_jobs" in data:  # 老版 SSR 产物
            out, seen = [], set()
            for j in data["_ssr_jobs"]:
                jd, title = j.get("jd_url"), j.get("title")
                if not (jd and title) or jd in seen:
                    continue
                seen.add(jd)
                out.append(RawJob(company=self.company_name or "", title=title,
                                  location=j.get("location"), job_type=None, summary=None,
                                  jd_url=jd, apply_url=jd, posted_at=None))
            return out
        return super().parse(html)  # 新版 JSON 拦截路径

    def _list_posts(self, list_json: str):
        try:
            data = __import__("json").loads(list_json)
        except (ValueError, TypeError):
            return []
        posts = []
        for resp in data.get("_intercepted", []) or []:
            posts.extend(pp for pp in self._extract_posts(resp) if isinstance(pp, dict))
        return posts

    def _discover_detail_route(self, source_url: str, list_json: str):
        """探测本租户的详情路由（**单浏览器会话**，避免多会话连打同一 host 触发反爬）。
        策略①（主，最可靠）：渲染列表页 → 点击首个岗位卡 → 捕获跳转 URL → 把 id 值替换为 {id} 得到模板
          （适配 jobAdId/jobId × Id/JobAdId 各种约定，且对无 href 的 React 卡片也有效）。
        策略②（兜底）：在同一会话内猜常见详情 path × render-verify（返回 base 字符串，按 ?jobAdId={Id} 兜底）。
        返回 dict{template,idfield} / str(base) / None。"""
        posts = self._list_posts(list_json)
        if not posts:
            return None
        # `/api/` 宽匹配会把搜索条件 / 地区树 / 推荐岗等非岗位列表也拦进来，posts[0] 可能不是真岗位
        # （无 JobAdName/Id），甚至地区树节点也带 name+id 会被误判。北森真岗位恒有 JobAdName，
        # 故优先按 JobAdName 取真岗位；仅当无任何 JobAdName 时才退回通用 title/name（兼容异构租户）。
        def _collect(name_keys):
            out = []  # [(name, [(idfield, idval), ...])]
            for p in posts:
                nm = _first_str(p, name_keys)
                if not nm:
                    continue
                ids = [(f, v) for f, v in ((f, _first_str(p, (f,))) for f in self._ID_FIELDS) if v]
                if ids:
                    out.append((nm, ids))
            return out

        real = _collect(("JobAdName",)) or _collect(("title", "name", "jobTitle"))
        if not real:
            return None
        a_name, id_vals = real[0]
        b_name = next((nm for nm, _ in real[1:] if nm != a_name), None)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=PlaywrightAdapter.user_agent, locale="zh-CN")
            page = ctx.new_page()
            try:
                # 北森 SPA 持续轮询（tara-frontend 日志 / AI 机器人），networkidle 永不静默 → 30s 超时
                # → 整个探测被外层 except 吞成 None（NO-DETAIL-ROUTE）。改 domcontentloaded（与主 fetch 一致）。
                page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
                # ① 猜测式（proven，对 chinalife/popmart/横店等直达详情 URL 可渲染的租户最稳，不回退）
                guessed = self._guess_route(page, source_url, id_vals[0][1], a_name, b_name)
                if guessed:
                    return guessed
                # ② 点击捕获兜底（救 React 详情页直达不渲染、需从列表点入的租户，如迈瑞）
                page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
                el = self._first_job_element(page, a_name)
                if el is None:
                    return None
                before = page.url
                captured = None
                try:  # 多数北森详情在新标签打开
                    with ctx.expect_page(timeout=7000) as np:
                        el.click()
                    newp = np.value
                    newp.wait_for_load_state("domcontentloaded", timeout=7000)
                    captured = newp.url
                except Exception:  # 同标签内路由跳转
                    try:
                        page.wait_for_timeout(2500)
                        captured = page.url
                    except Exception:
                        captured = None
                if captured and captured != before:
                    for field, val in id_vals:
                        if val and val in captured:
                            return {"template": captured.replace(val, "{id}"), "idfield": field}
                return None
            except Exception:
                return None
            finally:
                browser.close()

    @staticmethod
    def _first_job_element(page, a_name: str):
        """定位首个岗位卡可点击元素：优先按岗位名文本匹配，兜底按北森常见 class。"""
        try:
            loc = page.get_by_text(a_name[:12], exact=False).first
            if loc and loc.count() > 0:
                return loc
        except Exception:
            pass
        for sel in ("div[class*=JobTitle]", "div[class*=TitleSection]", "div[class*=jobName]",
                    "a[class*=job]", ".job-name", ".position-name", "li[class*=job] a"):
            try:
                el = page.query_selector(sel)
                if el:
                    return el
            except Exception:
                continue
        return None

    def _guess_route(self, page, source_url: str, a_id: str, a_name: str, b_name):
        """同会话内猜常见详情 path × render-verify，返回命中的 detail base（origin+path，无 query）或 None。"""
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        segs = [s for s in (parsed.path or "").split("/") if s]
        bases = []
        if segs:
            bases.append("/" + "/".join(segs[:-1]))
        bases.append("/" + "/".join(segs))
        seen, cand_paths = set(), []
        for base in bases:
            for nm in _BEISEN_DETAIL_NAMES:
                path = (base.rstrip("/") + "/" + nm) if base.strip("/") else "/" + nm
                if path not in seen:
                    seen.add(path)
                    cand_paths.append(path)
        for path in cand_paths:
            url = f"{origin}{path}?jobAdId={a_id}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(3500)
                if self._is_job_detail(page, a_name, b_name):
                    return f"{origin}{path}"
            except Exception:
                continue
        return None

    @staticmethod
    def _is_job_detail(page, a_name: str, b_name) -> bool:
        """判断当前页是否为「岗位 a_name 的详情页」（而非列表页/无关页）。
        强信号：页面主标题（h1/jobName 类）含本岗位名 → 即使侧栏有「推荐职位」露出 b_name 也算命中。
        弱信号兜底：本岗位名在正文 且 列表里另一岗位名 b_name 不在正文（无并列岗位=非列表页）。"""
        content = page.content()
        if not a_name or a_name not in content:
            return False
        heading = page.evaluate(
            "()=>{const sels=['h1','[class*=jobName]','[class*=JobName]','[class*=positionName]',"
            "'[class*=PositionName]','[class*=job-title]','[class*=jobTitle]','[class*=JobTitle]'];"
            "for(const s of sels){const e=document.querySelector(s);"
            "const t=e&&(e.innerText||'').trim();if(t)return t;}return '';}") or ""
        core = a_name.split("（")[0].split("(")[0].strip()[:10]
        if core and core in heading:        # 主标题就是本岗位 → 详情页
            return True
        return not (b_name and b_name in content)  # 无并列岗位 → 非列表页

    def _resolve_url(self, post: dict, job_id: str) -> str:
        # 1) 接口若直接给了 per-job 链接，优先用（最可靠）。
        raw = super()._resolve_url(post, job_id)
        if raw:
            return raw
        # 2) 用本租户探测到的详情路由。探不到则不拼（丢弃，杜绝坏链）。
        route = getattr(self, "_detail_route", None)
        if isinstance(route, dict):  # 点击捕获：{template, idfield}
            idval = _first_str(post, (route.get("idfield", "Id"),))
            return route["template"].format(id=idval) if idval and "{id}" in route.get("template", "") else ""
        if isinstance(route, str):  # 旧缓存：detail base 字符串，按 ?jobAdId={Id} 兜底
            uuid = _first_str(post, ("Id", "id", "jobAdId", "JobAdId"))
            return f"{route}?jobAdId={uuid}" if uuid else ""
        return ""


class CompanySpaAdapter(ChinaSpaAdapter):
    """通用企业官网 SPA 招聘站（各公司自建站）。

    拦截站点自身**所有 JSON** 接口，启发式抽取岗位；仅放行接口里带**真实 per-job 链接**的行，
    绝不拼/猜 URL。覆盖「各公司站」长尾，加源零代码（填公司名 + 招聘页地址 + adapter=company_spa）。
    """

    name = "company_spa"
    intercept_matches = ()  # 拦截所有 JSON
    detail_template = ""    # 不拼链接，只用接口里的真实 URL
