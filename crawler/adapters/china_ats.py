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
import html as _html
import json
import logging
import re
import time
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

import normalizer
from .base import (DEFAULT_LIST_CAP, PageResult, RawJob, paginate_all, resolve_detail_cap,
                   resolve_list_cap)
from .playwright_base import PlaywrightAdapter

_log = logging.getLogger(__name__)

# 翻页时单页失败的重试次数与退避基数（见 _post_page_with_retry）。3 次 × 0.6s 退避足够穿过
# 北森的秒级限流窗口，又不会让一个真坏掉的源把整轮抓取拖住。
_PAGE_RETRIES = 3
_PAGE_BACKOFF_SECONDS = 0.6


def _first_str(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        self._source_url = source_url
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
            return urljoin(
                getattr(self, "_source_url", None)
                or (getattr(self, "_origin", "") + "/"),
                raw,
            )
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
# socialxq / overseasxq 是 theme2 老版 CMS 的社招 / 海外板块详情路由（2026-08-27 中芯国际 live 实测）；
# 原来只有 campusxq，导致这类租户的社招 / 海外板块猜不出路由 → jd_url 全空 → 整源判「0 岗」丢弃。
_BEISEN_SSR_DETAIL_PATHS = ("szxq", "szzwxq", "xzxq", "campusxq", "socialxq", "overseasxq",
                            "zwxq", "details2021",
                            "overseadetail", "detail", "jobdetail", "szzp", "xq", "positiondetail")
_BEISEN_SSR_PARAMS = ("jobId", "adId", "jobAdId")
# 从 SSR 列表页抽取 per-job 锚点（jobId/adId/jobAdId=数字或 GUID + 标题文本），去重。
_BEISEN_SSR_ANCHOR_JS = r"""
() => {
  const out=[], seen=new Set();
  const push=(id,name,href)=>{
    if(!name || name.length<3 || name.length>60) return;   // 跳过登录/注册等短文本
    if(seen.has(id)) return; seen.add(id);
    out.push({id, name, href});
  };
  // ① 查询串式：?jobId= / ?jobAdId= / ?adId=（详情 path 因租户而异，需 _discover_ssr_route 探）
  for (const a of document.querySelectorAll(
        "a[href*='jobId='],a[href*='adId='],a[href*='jobAdId=']")) {
    const href=a.getAttribute('href')||'';
    const m=href.match(/(?:jobId|jobAdId|adId)=([^&#]+)/i);
    if(!m) continue;
    push(decodeURIComponent(m[1]), (a.innerText||a.textContent||'').trim(), a.href);
  }
  // ② 路径式：/job_show/230910610、/zpdetail/230300168 …（老版 CMS Portal 租户用这种，
  //    2026-07-27 实测科伦 kelun=/job_show/{id}、启德 eic=/zpdetail/{id}）。
  //    这类 href 本身就是**完整可用的详情链接**，直接带出去用，不需要再猜路由。
  for (const a of document.querySelectorAll("a[href]")) {
    const href=a.getAttribute('href')||'';
    const m=href.match(/\/(?:job[_-]?show|zpdetail|jobdetail|job[_-]?detail|positiondetail)\/(\d{4,})/i);
    if(!m) continue;
    push(m[1], (a.innerText||a.textContent||'').trim(), a.href);
  }
  return out.slice(0,120);
}
"""


_BEISEN_SSR_JD_RE = re.compile(
    r"(工作职责|岗位职责|职位描述|工作内容|岗位描述|职责描述)[：:]\s*(.+)$", re.S)
_BEISEN_SSR_SUMMARY_CAP = 60


def _beisen_ssr_fill_summaries(jobs: List[dict]) -> None:
    """老版 CMS Portal 租户：详情页是 SSR 直出正文，纯 httpx 取回来即可（无需浏览器）。

    为何要做：不补正文的话这些岗只是「薄卡」——`count_valid_active_jobs()` 与北极星
    「必投清单健康覆盖」都要求 summary≥60 字，薄卡不计数，等于白抓
    （2026-07-27 实测科伦/启德首抓 17 岗全无正文）。
    只取「工作职责/岗位职责/职位描述」之后的正文，去掉导航与页眉页脚噪声；失败静默跳过（留薄卡）。
    """
    cap = resolve_detail_cap(_BEISEN_SSR_SUMMARY_CAP)
    with httpx.Client(timeout=15, follow_redirects=True,
                      headers={"User-Agent": PlaywrightAdapter.user_agent}) as cli:
        for job in jobs[:cap]:
            try:
                resp = cli.get(job["jd_url"])
                if resp.status_code != 200:
                    continue
                text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", resp.text, flags=re.S | re.I)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", _html.unescape(_html.unescape(text))).strip()
                m = _BEISEN_SSR_JD_RE.search(text)
                body = (m.group(2) if m else "").strip()
                if len(body) >= 60:
                    job["summary"] = body[:4000]
            except Exception:
                continue


# ============================================================================
# 老版 CMS Portal 门户（北森 theme2 SSR）——纯 httpx，零浏览器
# ============================================================================
# 与新版 SPA 租户的区别（2026-08-27 live 实测 smics.zhiye.com=中芯国际 563 岗）：
#   新版：列表页是 React，HTML 里抽得到 PortalId，岗位走 POST GetJobAdPageList（→ _httpx_fetch）。
#   老版：列表页 SSR 直出 <li><a href="/{板块}xq?jobId={id}&jc=N">，**没有 PortalId、没有那个接口**
#         → _httpx_fetch 返回 None → 旧代码只能掉进浏览器慢车道（慢，且 _fetch_ssr 不翻页、只取首屏）。
# 识别一律按**响应特征**（抽不到 PortalId + 列表页直出 jobId 锚点），不按域名/租户名写白名单。
#
# 已 live 确认的坑：
#   ① 服务端**无条件 gzip**：httpx 自动解压（curl 要 --compressed），否则拿到乱码会误判空页。
#   ② 列表锚点尾部带**筛选态回传参数** `&c=&p=1^-1,3^-1&ky=`，随用户当前筛选变化 →
#      必须只留 jobId(+jc) 两个身份参数，否则同一岗算出多个 canonical_jd_url = 库里同岗多行。
#   ③ 翻页越界仍返 **HTTP 200 + 完整页面骨架**（约 19KB）→ 只能靠「页内锚点数 == 0」判终止，
#      绝不能靠状态码。末页页数各板块不同（实测社招 30 / 校招 25 / 海外 3）且随在招量变，不写死。
#   ④ 模板占位岗藏在 HTML 注释里（href="" 的假行，如「光罩OPC工程师/大专/北京市海淀区」重复多条）
#      → 解析前必须先剥掉 <!-- --> ，否则整页混进假岗。
#   ⑤ 列表里**长标题被服务端截断**（25 字 + "..."，实测约 10% 的行），详情页 <h2> 才是全名 →
#      截断行必须优先补详情，否则「日更快车道写截断名 / 夜间富化写全名」来回抖。
_CMS_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# 岗位行：<li><a href="…?jobId=…">…</a></li>。**必须锚在 <li> 上**——科伦(kelun) 这类老版 CMS
# 的「热招职位」侧栏也有裸 <a href="/social_show?jobId=…">，而它的主列表是 <table><tr><td>，
# 不加 <li> 约束会只捞到侧栏 10 条却自称抓全（fetch_complete=True → list-absence 误杀在招岗）。
# ⚠️ 详情链接不一定在 href 上：建发(chinacdc) 这类租户写成
#     <li><a href="javascript:void(0)" data-url="/zwxq?jobId=561284174">…</a></li>
#   —— href 是 javascript:void(0)，真链接在 **data-url**。只认 href 会一条都抓不到、
#   整源判「0 岗」丢弃（2026-08-27 live 实测建发 10 条/页全被漏掉）。故两个属性都认。
_CMS_ROW_RE = re.compile(
    r"<li[^>]*>\s*<a\s[^>]*(?:href|data-url)=\"(?P<href>[^\"]*[?&](?:jobId|jobAdId|adId)=[^\"]+)\"[^>]*>(?P<body>.*?)</a>",
    re.S | re.I)
_CMS_SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S | re.I)
_CMS_TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.S | re.I)
_CMS_PAGE_LINK_RE = re.compile(r"PageIndex=(\d{1,4})", re.I)
_CMS_ID_RE = re.compile(r"[?&](jobId|jobAdId|adId)=([^&#]+)", re.I)
_CMS_JC_RE = re.compile(r"[?&]jc=([^&#]+)", re.I)
_CMS_PORTAL_ID_RE = re.compile(r'PortalId"\s*:\s*"([0-9a-fA-F-]+)"')
# 详情页（同一套 theme2 模板，中英文两版只有 label 不同）：
#   标题 <div class="xqtitle …"><h2>岗位名</h2>
#   字段 <li><span>职位学历：</span><b>硕士</b></li> / <li><span>Education:</span><b>Bachelor</b></li>
#   正文 <h3>职位描述</h3><div class="xqm">…</div><h3>职位要求</h3><div class="xqm">…</div>
_CMS_DETAIL_TITLE_RE = re.compile(
    r"<div[^>]*class=\"[^\"]*xqtitle[^\"]*\"[^>]*>.*?<h2[^>]*>(.*?)</h2>", re.S | re.I)
_CMS_DETAIL_FIELD_RE = re.compile(
    r"<li[^>]*>\s*<span[^>]*>(.*?)</span>\s*<b[^>]*>(.*?)</b>", re.S | re.I)
_CMS_DETAIL_SECTION_RE = re.compile(
    r"<h3[^>]*>(.*?)</h3>\s*<div[^>]*class=\"xqm\"[^>]*>(.*?)</div>", re.S | re.I)
_CMS_CITY_RE = re.compile(r"[一-龥]{2,}[省市区县]")
_CMS_ACTION_RE = re.compile(r"查看职位|查看详情|立即申请|投递|view detail|apply", re.I)
_CMS_TRUNCATED_RE = re.compile(r"(\.{3}|…)\s*$")

_CMS_PAGE_SIZE = 10       # theme2 列表固定每页 10 条（短页 = 末页的判据）
_CMS_MAX_PAGES = 200      # 安全上限（防接口异常翻不停）；命中即 fetch_complete=False
_CMS_DETAIL_CAP = 800     # 逐岗补正文默认上限（详情 ~0.13s/个，中芯最大板块 293 岗 ≈ 38s）
_CMS_TITLE_REPAIR_CAP = 120   # 即使 CRAWL_DETAIL_CAP=0（日更快车道跳过富化），仍补这么多条截断标题
# 正文入库下限。刻意低于 count_valid_active_jobs() 的 60 字「有效在招」线：这里是从
# <h3>+<div class="xqm"> **结构块**里取的，短 ≠ 噪声（中芯校招 6 个环保安全岗 JD 本来就只有 50 来字），
# 存下来用户至少看得见、匹配器也读得到；「够不够 60 字算有效在招」由计数口径在读时把关，不在这一层砍。
_CMS_SUMMARY_MIN = 20

# 表头文本 → 列语义。**从最具体到最泛**匹配：「职位分类」必须在「职位」之前命中，
# 否则含「职位」二字的表头会被一律当成标题列。
_CMS_COL_KEYWORDS = (
    ("职位名称", "title"), ("岗位名称", "title"), ("job title", "title"), ("job name", "title"),
    ("position name", "title"),
    ("职位分类", "category"), ("职位类别", "category"), ("岗位类别", "category"), ("职能", "category"),
    ("job category", "category"), ("category", "category"),
    ("职位学历", "education"), ("学历", "education"), ("education", "education"), ("degree", "education"),
    ("工作地点", "location"), ("工作城市", "location"), ("work place", "location"),
    ("location", "location"), ("城市", "location"), ("地点", "location"),
    ("操作", "action"), ("view", "action"),
    ("职位", "title"), ("岗位", "title"), ("position", "title"),
)
# 学历档次从低到高。列表常写「硕士、博士」（= 硕士及以上），并列时取**最低**档——
# 招聘方给的是门槛下限，取高档会把本来符合条件的人筛掉。
_CMS_EDU_ORDER = ("不限", "大专", "本科", "硕士", "博士")


def _cms_text(fragment: Optional[str]) -> str:
    """HTML 片段 → 纯文本（去标签 + 反转义 + 折叠空白）。"""
    if not fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(_html.unescape(text))
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _cms_education(value: Optional[str]) -> Optional[str]:
    """列表/详情的『职位学历』归一到 normalizer 口径（博士/硕士/本科/大专/不限）。
    并列多档取最低档（见 _CMS_EDU_ORDER）；非学历值（如误填的「社招」）返回 None。"""
    raw = (value or "").strip()
    if not raw:
        return None
    hits = []
    for piece in re.split(r"[、,，/|]+", raw):
        level = normalizer.extract_education(piece)
        if level in _CMS_EDU_ORDER:
            hits.append(level)
    if hits:
        return min(hits, key=_CMS_EDU_ORDER.index)
    return normalizer.extract_education(raw)


def _cms_normalize_job_url(origin: str, href: str) -> str:
    """列表锚点 → 稳定的逐岗 jd_url：只保留 jobId(+jc) 两个身份参数。

    原始锚点形如 `/socialxq?jobId=390609112&jc=1&c=&p=1^-1,3^-1&ky=`——尾部 c/p/ky 是**筛选态回传**，
    随用户当前筛选条件变化；不剥掉的话同一个岗在不同筛选态下会算出不同 canonical_jd_url
    （canonicalize_jd_url 只去 utm_ 类 tracking 参数，c/p/ky 会被原样保留）→ 库里出现重复行。"""
    if not href:
        return ""
    href = _html.unescape(href).strip()
    m = _CMS_ID_RE.search(href)
    if not m:
        return ""
    path = href.split("?", 1)[0].split("#", 1)[0]
    query = f"{m.group(1)}={m.group(2)}"
    jc = _CMS_JC_RE.search(href)
    if jc and jc.group(1).strip():
        query += f"&jc={jc.group(1).strip()}"
    base = path if path.startswith(("http://", "https://")) else urljoin((origin or "") + "/", path)
    return f"{base}?{query}"


def _cms_column_map(html_text: str):
    """表头 <th> → {列下标: 列语义}。老版 CMS 各租户列序/列数不同，按表头对齐比按下标硬编码稳。"""
    headers = [_cms_text(h) for h in _CMS_TH_RE.findall(html_text)]
    col_map = {}
    for idx, head in enumerate(headers):
        low = head.lower()
        for keyword, field in _CMS_COL_KEYWORDS:
            if keyword in low:
                col_map[idx] = field
                break
    return col_map, len(headers)


def _cms_row_fields(cells: List[str], col_map: dict, header_count: int) -> dict:
    """一行的若干 <span> 文本 → {title, location, education, category}。
    表头对得上就按表头映射；对不上（表头缺失/列数不符的租户）退回按**取值特征**认字段。"""
    out = {"title": "", "location": None, "education": None, "category": None}
    if col_map and header_count == len(cells):
        for idx, cell in enumerate(cells):
            field = col_map.get(idx)
            if field and field != "action" and cell:
                out[field] = cell
    if out["title"]:
        return out
    rest = []
    for cell in cells:
        if not cell or _CMS_ACTION_RE.search(cell):
            continue
        if out["education"] is None and _cms_education(cell):
            out["education"] = cell
            continue
        if out["location"] is None and _CMS_CITY_RE.search(cell) and len(cell) <= 20:
            out["location"] = cell
            continue
        rest.append(cell)
    out["title"] = max(rest, key=len) if rest else ""
    return out


def _cms_parse_list(html_text: str, origin: str):
    """老版 CMS 列表页 HTML → (rows, last_page)。

    rows = [{title, jd_url, location, education, category, title_truncated}]，按 jd_url 去重。
    last_page = 分页条里出现过的最大 PageIndex（站点自报的总页数，实测每页都带真末页号）；
    抽不到返回 None（交给 paginate_all 用「空页/短页」兜底判末页）。"""
    body = _CMS_COMMENT_RE.sub(" ", html_text or "")   # 先剥注释：模板占位假岗藏在里面
    col_map, header_count = _cms_column_map(body)
    rows, seen = [], set()
    for m in _CMS_ROW_RE.finditer(body):
        jd_url = _cms_normalize_job_url(origin, m.group("href"))
        if not jd_url or jd_url in seen:
            continue
        cells = [_cms_text(s) for s in _CMS_SPAN_RE.findall(m.group("body"))]
        fields = _cms_row_fields(cells, col_map, header_count) if cells else {
            "title": _cms_text(m.group("body")), "location": None, "education": None, "category": None}
        title = (fields.get("title") or "").strip()
        if not (3 <= len(title) <= 120):   # 太短/太长的不是岗位名（登录、导航等）
            continue
        seen.add(jd_url)
        rows.append({
            "title": title,
            "jd_url": jd_url,
            "location": fields.get("location") or None,
            "education": _cms_education(fields.get("education")),
            # 学历列被租户误填成招聘类型（中芯社招板块实测有「社招」）→ 当 job_type 用，别丢
            "job_type": (fields.get("education")
                         if normalizer.is_recruitment_type(fields.get("education")) else None),
            "title_truncated": bool(_CMS_TRUNCATED_RE.search(title)),
        })
    pages = [int(p) for p in _CMS_PAGE_LINK_RE.findall(body)]
    return rows, (max(pages) if pages else None)


def _cms_parse_detail(html_text: str) -> dict:
    """老版 CMS 详情页 HTML → {title, summary, education, job_type, location}。

    正文只取 <h3>小标题</h3> + <div class="xqm">正文</div> 这些块，**不做「某关键词之后全要」的整页切片**——
    该模板正文后面紧跟着几千字《职位申请知情同意书》，整页切片会把隐私条款当岗位正文写进库。
    中英双版同模板（社招/校招是「职位描述/职位要求」，海外板块是「job description/Job requirements」），
    故按结构取而不是按中文关键词找。"""
    out = {"title": "", "summary": None, "education": None, "job_type": None, "location": None}
    if not html_text:
        return out
    cleaned = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_text, flags=re.S | re.I)
    cleaned = _CMS_COMMENT_RE.sub(" ", cleaned)

    m = _CMS_DETAIL_TITLE_RE.search(cleaned)
    if m:
        out["title"] = _cms_text(m.group(1))

    for label_raw, value_raw in _CMS_DETAIL_FIELD_RE.findall(cleaned):
        label = _cms_text(label_raw).rstrip("：:").strip().lower()
        value = _cms_text(value_raw)
        if not value:
            continue
        if any(k in label for k in ("学历", "education", "degree")):
            out["education"] = _cms_education(value)
        elif any(k in label for k in ("工作地点", "工作城市", "location", "work place")):
            out["location"] = value
        elif any(k in label for k in ("工作类型", "job type", "employment")):
            out["job_type"] = value

    parts = []
    for head_raw, body_raw in _CMS_DETAIL_SECTION_RE.findall(cleaned):
        head, body = _cms_text(head_raw), _cms_text(body_raw)
        if not body:
            continue
        parts.append(f"【{head}】\n{body}" if head else body)
    summary = "\n".join(parts).strip()
    if len(summary) >= _CMS_SUMMARY_MIN:
        out["summary"] = summary[:4000]
    return out


def _post_page_with_retry(cli, endpoints, ep_ok, body, attempts=_PAGE_RETRIES):
    """POST 一页 GetJobAdPageList，失败退避重试。返回 (payload|None, 命中的端点)。

    ⚠️ 为什么必须重试：北森按 **IP** 限流（响应头 `X-RateLimit-Limit-<host><ip>-second: 50`）。
    2026-09-04 把单源上限从 600 抬到 8000 之后，我们对 *.zhiye.com 这一个 CDN 的请求量翻了十几倍，
    偶发被掐成了常态；而旧代码一页拿不到就 `break`，一次抖动就把整源截断——当天线上实测
    上海医药 230→50、三一 135→50、新奥 220→118（同一轮里另有 26 个源多抓了 3.1 万个岗，
    方向是对的，但这 461 个岗的回归是自己造的，得补上）。

    端点大小写两试（/api/Jobad/ 与 /api/JobAd/）只在**首次**发生，命中后固定，不重复试错。
    """
    for attempt in range(max(1, attempts)):
        for ep in ((ep_ok,) if ep_ok else endpoints):
            try:
                cand = cli.post(ep, json=body, headers={"Content-Type": "application/json"}).json()
            except Exception:
                continue
            if isinstance(cand, dict) and isinstance(cand.get("Data"), list):
                return cand, ep
        if attempt + 1 < max(1, attempts):
            time.sleep(_PAGE_BACKOFF_SECONDS * (attempt + 1))
    return None, ep_ok


def _dedup_new(chunk, seen_ids, id_fields):
    """本页里没见过的行（按岗位 id 去重）。翻页途中接口重复回同一批是常态，
    不去重会让「收满 total 就停」提前满足，尾巴永远抓不到。"""
    fresh = []
    for row in chunk:
        if not isinstance(row, dict):
            continue
        key = next((str(row[f]) for f in id_fields if row.get(f) not in (None, "")), None)
        if key is None:
            fresh.append(row)          # 认不出 id 的行照收，宁可重也不漏
            continue
        if key in seen_ids:
            continue
        seen_ids.add(key)
        fresh.append(row)
    return fresh


def _should_continue(fresh, chunk, total, page_size):
    """还该不该翻下一页。

    ⚠️ 末页判据**不能**用「本页条数 < pageSize」：北森在限流/抖动时会回短页（2026-09-04 本机
    连续请求就被它掐成 ConnectError），一个瞬时短页就会让整源停在半路 —— 中国交建自报 2565、
    深页明明有数据，却只抓到 800 就收工，正是这么来的。项目里 hotjob/海康那两次也栽在同一条。

    改用「这一页有没有带来新岗位」：接口在原地打转或真到末页 → fresh 为空 → 停；否则继续。
    只有在**没有分母可判**（total 未知）时，才退回短页当自然末页。"""
    if not fresh:
        return False
    if total:
        return True
    return len(chunk) >= page_size


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
    # 单租户抓取条数上限（env CRAWL_MAX_JOBS 可整体调档，见 base.resolve_list_cap 的取数依据）。
    # ⚠️ 别再把这个数字当成「越大越好」往上堆：2026-09-04 实测 26 个北森源因旧的 600 硬顶累计漏
    # 8.7 万岗（该修），但星巴克那 26,720 条归一后只有 30 种标题、3 种占 99%（不该整包拉）——
    # 「抓全」和「抓多」不是一回事。
    _MAX_JOBS = DEFAULT_LIST_CAP

    # list-absence 探活：beisen GetJobAdPageList 返全量在招岗 + 本类翻全 → 抓全时列表缺席=下架（同 feishu）。
    supports_absence_liveness = True
    fetch_complete = False

    def fetch(self, source_url: str) -> str:
        """httpx-first（2026-06-28 实测 6/6 租户冷 httpx 可达）：HTML 抽 PortalId → GetJobAdPageList 翻页，
        **零浏览器**。但 jd_url 需本租户详情路由（点击捕获，按 host 缓存到 beisen_routes.json）——故仅当
        **route 已缓存**时走 httpx（能拼 jd_url）；route 未缓存的租户回退浏览器（顺带探+缓存 route，由
        harvest_beisen_routes.py 持久化）。daily-crawl 无 Playwright → httpx 路径自给，回退浏览器会抛由上层记 failed。"""
        self.reported_total = None
        self.fetch_complete = False
        parsed = urlparse(source_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._host = parsed.netloc
        segs = [s for s in (parsed.path or "").split("/") if s]
        self._portal_prefix = ("/" + "/".join(segs[:-1])) if len(segs) > 1 else ""
        self.list_urls = [source_url]

        route = _BEISEN_ROUTE_CACHE.get(self._host)
        # beisen_routes.json 里登记 {"cms": true} = 已知老版 CMS Portal 租户。作用有二：
        #   ① 让 beisen_httpx_ready() 认它为「零浏览器可抓」→ run.py 把它排进 httpx 并发快车道
        #      （否则未登记的 host 一律落串行浏览器档，白占慢车道名额）；
        #   ② 直接走老版 CMS 分支，省掉一次注定拿不到 PortalId 的新版探测请求。
        cms_hint = isinstance(route, dict) and route.get("cms") is True
        cms_tried = False
        if cms_hint:
            cms_tried = True
            try:
                cms = self._httpx_fetch_cms(source_url)
            except Exception:
                cms = None
            if cms:
                return cms
            # 登记信息过时（租户升级到新版 SPA）→ **必须把这条假登记从缓存里清掉**，否则下面
            # 「首见租户」分支会因为 host 还在缓存里被跳过 → 详情路由永远探不出来 → _resolve_url
            # 全返空 → 整源解析成 0 岗，偏偏浏览器路径又把 fetch_complete 置成 True
            # ＝「0 岗 + 自称抓全」，正是 CLAUDE.md §4 立碑警告的误杀在招岗组合。
            _BEISEN_ROUTE_CACHE.pop(self._host, None)
            route = None

        if route:  # route 已缓存 → 尝试纯 httpx（拿到列表即能拼 jd_url，不开浏览器）
            try:
                j = self._httpx_fetch(source_url)
            except Exception:
                j = None
            if j:
                self._detail_route = route
                return j
            # httpx 失败且路由已缓存 → 不要穿透到浏览器（CI 环境未装 Playwright 会直接崩溃）。
            # 正确处理：记 partial_success，等下次 auto-discover 重跑刷新路由缓存。
            raise RuntimeError(
                f"beisen: httpx fetch failed for cached route "
                f"({self._host} → {route!r}); retry after auto-discover refreshes the route"
            )

        # route 未缓存的**首见租户**：先用 httpx 抓**完整列表**（可靠），浏览器只用来探一次路由。
        # 为何：旧实现直接走下面的 _fetch_paginated 抓列表，但浏览器拦截重放对多数租户只捞到 count-probe
        # 的 1-2 条 → 列表近空 → 路由探测拿不到候选、jd_url 全空 → auto-discover 逐家确认把长江存储 479 /
        # 追觅 2248 岗这类真源全判「0 岗」丢弃。实测：把 httpx 完整列表喂给 _discover_detail_route，
        # 路由探测正常命中、几百上千岗全拼出 jd_url。故此处 httpx 抓列表 + 浏览器仅探路由。
        if self._host not in _BEISEN_ROUTE_CACHE:
            try:
                j = self._httpx_fetch(source_url)
            except Exception:
                j = None
            if j:
                try:
                    route = self._discover_detail_route(source_url, j)  # 浏览器仅探路由，不抓列表
                except Exception:
                    route = None
                _BEISEN_ROUTE_CACHE[self._host] = route   # 命中或 None 都缓存，避免重复探测
                self._detail_route = route
                return j

        # 新版 GetJobAdPageList 没打通 → 先试**老版 CMS Portal 门户**（theme2 SSR，同样零浏览器）。
        # 放在开浏览器之前：老版 CMS 抽不到 PortalId，走浏览器只会白跑几分钟且 _fetch_ssr 不翻页。
        # 与上面两处 httpx 尝试同样的容错口径：这条新分支出任何意外都只退回原有浏览器路径，不改变既有源的命运。
        if not cms_tried:
            try:
                cms = self._httpx_fetch_cms(source_url)
            except Exception:
                cms = None
            if cms:
                return cms

        # 都没打通 → 回退浏览器全流程（探+缓存 route），再不行落 SSR
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
            seen_ids: set = set()
            cap = resolve_list_cap(self._MAX_JOBS)
            while len(rows) < cap:
                body = {"PageIndex": index, "PageSize": self._PAGE_SIZE, "Category": [],
                        "KeyWords": "", "SpecialType": 0, "PortalId": portal_id,
                        "DisplayFields": ["Category", "Kind", "LocId", "PostDate", "WorkWeChatQrCode"]}
                jj, ep_ok = _post_page_with_retry(cli, endpoints, ep_ok, body)
                if not isinstance(jj, dict):
                    break
                if total is None:
                    total = jj.get("Count") or jj.get("Total") or 0
                    reported = _int_or_none(jj.get("Count"))
                    if reported is None:
                        reported = _int_or_none(jj.get("Total"))
                    if reported is not None:
                        self.reported_total = reported
                chunk = jj.get("Data") or []
                if not isinstance(chunk, list) or not chunk:
                    break
                fresh = _dedup_new(chunk, seen_ids, self._ID_FIELDS)
                rows.extend(fresh)
                if total and len(rows) >= total:
                    break
                if not _should_continue(fresh, chunk, total, self._PAGE_SIZE):
                    break
                index += 1
        if not rows:
            return None
        self.fetch_complete = (total is not None and len(rows) >= (total or 0))
        return json.dumps({"_intercepted": [{"Data": rows, "Count": total or len(rows)}]}, ensure_ascii=False)

    # ---- 老版 CMS Portal 门户（theme2 SSR）：纯 httpx 抓全 ----

    @staticmethod
    def _cms_page_url(parsed, page: int) -> str:
        """把 PageIndex 换成目标页（保留 source_url 自带的其它 query，替换而非追加）。"""
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if k.lower() != "pageindex"]
        query.append(("PageIndex", str(page)))
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _httpx_fetch_cms(self, source_url: str) -> Optional[str]:
        """老版 CMS Portal 门户（北森 theme2 SSR）：纯 httpx 翻全列表 + SSR 详情直出正文。

        返回值与 _fetch_ssr 同 shape（``{"_ssr_jobs":[…]}``），parse() 不必新增分支。
        **不是**老版 CMS（列表页抽得到 PortalId → 新版 SPA；或首页没有 <li> jobId 锚点）→ 返回 None，
        原封不动交回原有流程（浏览器重放 / _fetch_ssr），故对现有 234 个新版租户零影响。
        """
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        pages_seen = [0]        # 闭包记账：真正抓了几页（用于校正 fetch_complete，见下）
        repeated = [False]      # 翻页参数不认账（每页都回同一批岗）时置位，见 fetch_page
        cache = {}              # 首页 HTML 复用，别为了探测多打一次
        all_urls = set()

        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": PlaywrightAdapter.user_agent}) as cli:
            try:
                first = cli.get(self._cms_page_url(parsed, 1))
                first.raise_for_status()
            except Exception:
                return None
            # 识别按响应特征，不按域名/租户名：有 PortalId = 新版 SPA，不归本分支管。
            if _CMS_PORTAL_ID_RE.search(first.text or ""):
                return None
            cache[1] = first.text
            first_rows, last_page = _cms_parse_list(first.text, origin)
            if not first_rows:
                return None

            def fetch_page(page: int) -> PageResult:
                text = cache.pop(page, None)
                if text is None:
                    resp = cli.get(self._cms_page_url(parsed, page))
                    resp.raise_for_status()   # 首页失败上抛记 failed；后续页由 paginate_all 尽力而为
                    text = resp.text
                rows, _ = _cms_parse_list(text, origin)
                pages_seen[0] = page
                # 该租户的翻页参数不是 PageIndex（页页回同一批岗）→ 立刻停，别空转 200 页；
                # 且此时**只看见了第一页**，绝不能自称抓全（下面把 complete 置 False）。
                fresh = [r for r in rows if r["jd_url"] not in all_urls]
                if rows and not fresh:
                    repeated[0] = True
                    return PageResult(items=[], total=None, total_pages=None)
                all_urls.update(r["jd_url"] for r in rows)
                # 翻页越界仍是 200 + 完整骨架 → 只能靠「本页锚点数 0」判终止（paginate_all 的空页规则）。
                # total_pages 只认首页分页条自报的末页号（实测每页都带真末页，社招 30 / 校招 25 / 海外 3）。
                return PageResult(items=rows, total=None,
                                  total_pages=last_page if page == 1 else None)

            jobs, _total, complete = paginate_all(
                fetch_page, page_size=_CMS_PAGE_SIZE, first_page=1,
                max_pages=_CMS_MAX_PAGES, logger=None,
                label=f"beisen-cms {parsed.netloc}")

            # 分页条自报 N 页却没翻到 N 页（中途空页/限流），或翻页参数根本不认账 → 不许自称抓全。
            # fetch_complete=True 会开启 list-absence 撤岗，抓漏 + 自称抓全 = 误杀在招岗（CLAUDE.md §4 立碑）。
            if repeated[0] or (last_page and pages_seen[0] < last_page):
                complete = False

            uniq, seen = [], set()
            for row in jobs:
                if row["jd_url"] in seen:
                    continue
                seen.add(row["jd_url"])
                uniq.append(row)
            self._cms_fill_details(uniq, cli)

        if not uniq:
            return None
        # 站点只报页数不报岗位总数 → 抓全时诚实把「看见的全部」记为分母（paginate_all 同口径）。
        self.reported_total = len(uniq) if complete else None
        self.fetch_complete = complete
        return json.dumps({"_ssr_jobs": uniq}, ensure_ascii=False)

    def _cms_fill_details(self, rows: List[dict], cli) -> None:
        """逐岗 GET SSR 详情页补 summary / 全名标题 / 学历（同一个 GET 全拿到，无需单独 enrich 通道）。

        两个 cap：
          - 正文富化走 resolve_detail_cap(_CMS_DETAIL_CAP)，日更快车道 CRAWL_DETAIL_CAP=0 时跳过（框架约定）。
          - **截断标题**（列表 25 字截断，实测约 10% 的行）另有独立小额度：即使富化关掉也要修，
            否则快车道写「…(J133...」、夜间富化写全名，同一岗标题天天来回抖（title 不在 _PRESERVE_IF_EMPTY 里）。
        单条失败静默跳过（保留列表信息，最差是薄卡），绝不因为一个详情页炸掉整源。"""
        cap = resolve_detail_cap(_CMS_DETAIL_CAP)
        truncated = [r for r in rows if r.get("title_truncated")]
        rest = [r for r in rows if not r.get("title_truncated")]
        queue = truncated + rest
        budget = max(cap, min(len(truncated), _CMS_TITLE_REPAIR_CAP))
        for row in queue[:budget]:
            try:
                resp = cli.get(row["jd_url"])
                if resp.status_code != 200:
                    continue
                detail = _cms_parse_detail(resp.text)
            except Exception:
                continue
            # 详情页 <h2> 才是全名；伪 id 页只有导航骨架（无 h2、无 xqm）→ detail 全空，保留列表值。
            if detail["title"] and not _CMS_TRUNCATED_RE.search(detail["title"]):
                row["title"] = detail["title"]
                row["title_truncated"] = False
            for field in ("summary", "education", "job_type", "location"):
                if detail.get(field) and not row.get(field):
                    row[field] = detail[field]

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
                seen_ids = set()
                cap = resolve_list_cap(self._MAX_JOBS)
                while len(rows) < cap:
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
                        reported = _int_or_none(jj.get("Count"))
                        if reported is None:
                            reported = _int_or_none(jj.get("Total"))
                        if reported is not None:
                            self.reported_total = reported
                    chunk = jj.get("Data") or []
                    if not isinstance(chunk, list) or not chunk:
                        break
                    fresh = _dedup_new(chunk, seen_ids, self._ID_FIELDS)
                    rows.extend(fresh)
                    if total and len(rows) >= total:
                        break
                    if not _should_continue(fresh, chunk, total, self._PAGE_SIZE):
                        break
                    index += 1
            browser.close()

        if rows:
            # 与 httpx 路径同口径：抓到 reported_total 全部才算完整（抓全率观测 honesty 契约）
            self.fetch_complete = (total is not None and len(rows) >= (total or 0))
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
                # 锚点自带完整详情 href（路径式租户，如 /job_show/{id}、/zpdetail/{id}）→ 直接用，
                # 不必再 render-verify 猜路由：页面给的就是真链接，猜反而可能猜错。
                direct = [a for a in anchors
                          if str(a.get("href") or "").startswith(("http://", "https://"))
                          and re.search(r"/(?:job[_-]?show|zpdetail|jobdetail|job[_-]?detail|positiondetail)/\d{4,}",
                                        str(a.get("href")), re.I)]
                if direct:
                    jobs, seen = [], set()
                    for a in direct:
                        jd = str(a["href"])
                        if jd in seen:
                            continue
                        seen.add(jd)
                        jobs.append({"title": a["name"], "jd_url": jd, "location": a.get("location")})
                    _beisen_ssr_fill_summaries(jobs)
                    return json.dumps({"_ssr_jobs": jobs}, ensure_ascii=False)
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
                # job_type/education 老版 CMS 才有（列表列 + 详情页字段）；老调用方不传 → None，行为不变。
                out.append(RawJob(company=self.company_name or "", title=title,
                                  location=j.get("location"), job_type=j.get("job_type"),
                                  summary=j.get("summary"), education=j.get("education"),
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
