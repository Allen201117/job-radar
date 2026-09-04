import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse
import httpx


logger = logging.getLogger(__name__)
_HEAD_SKIP_CACHE = {}
_HEAD_SKIP_CACHE_LOCK = threading.Lock()

# 单源列表抓取条数上限（见 resolve_list_cap）。旧的 600 硬默认让 32 个源每轮只抓到前 600 条、
# 累计漏掉 10.7 万个岗（2026-09-04 crawl_runs 实测），其中 74% 是必投清单公司。
#
# 为什么是 8000：2026-09-04 逐源量过官网自报总数，45 个截断源里 43 个 ≤8000（来伊份 7204、
# 奇瑞 5643、喜茶 5078、新东方 4273、中国交建 2565…），设到 8000 一次性把它们全部抓全；
# 只有星巴克 26,720 和我爱我家 28,827 仍会被截——这两家是「同一个岗 × N 家门店」的批量发布
# （星巴克归一后只有 30 种标题、其中 3 种占 99%；我爱我家 2.8 万条是 1.16 万个不同门店岗），
# 把它们整包拉进来只会把检索冲成一片，与「精准 > 规模」冲突。它们的稀有总部岗另有出路：
# 北森 GetJobAdPageList 的 KeyWords 是**服务端检索**（实测 KeyWords=Manager → 17 条，
# 一次请求就拿到藏在第 475 页的 Procurement Manager），比翻 500 页便宜 25 倍——留作第二阶段。
DEFAULT_LIST_CAP = 8000


def resolve_detail_cap(default: int) -> int:
    """逐岗 detail 富化上限。env CRAWL_DETAIL_CAP 覆盖各 adapter 的 _DETAIL_CAP：
    快档 daily 设 0 = 跳过逐岗富化（只抓列表，墙钟压到 20-30min）；
    重档 enrichment 不设此 env = 用 adapter 默认（逐岗补 summary）。非法值回退默认。"""
    raw = os.environ.get("CRAWL_DETAIL_CAP")
    if raw not in (None, ""):
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw not in (None, ""):
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return default


def resolve_list_cap(default: int) -> int:
    """单源**列表**抓取条数上限。与 resolve_detail_cap（逐岗富化上限）是两码事。

    env CRAWL_MAX_JOBS 整体调档 —— 出事（CI 超时 / 某站被我们翻烦了）不用改代码重新部署，
    改一个 repo variable 下一轮就生效。

    ⚠️ 不要在这里对 default 取 max：adapter 声明的基准档必须能**往下**压（单测把 _MAX_JOBS 设成 2
    来验「撞上限 → 不算抓全」，取 max 会让这类断言静默失效，也堵死以后给个别慢源单独降档的路）。
    ⚠️ 撞上限时调用方**必须**让 fetch_complete=False——beisen/feishu 都开了 list-absence 探活，
    「没抓到的尾巴」被当成「列表缺席」会整批误判撤岗（CLAUDE.md §4 立碑的误杀在招岗）。
    """
    return _env_int("CRAWL_MAX_JOBS", default)


def resolve_page_cap(page_size: int, default_rows: int = None) -> int:
    """把「条数上限」换算成「页数上限」，给那些用 max_pages 而不是 max_rows 记账的 adapter。

    为什么要有它：顺丰/小红书/wt 各自硬编码了一个页数上限（50 页 / 20 页 / 200 页），
    数字背后其实是「当时那家公司大概多少岗」——公司一扩招就悄悄截断，而且 status 还是 success。
    2026-09-04 实测：顺丰自报 2,184 只抓到 498（50 页 × 10 条），小红书 1,578 只抓到 1,268。
    换算成同一个 CRAWL_MAX_JOBS 旋钮之后，页数上限只剩「防死循环」的兜底作用，
    真正的收尾交给接口自报的 totalPage / total（都比这个上限先触发）。
    """
    rows = resolve_list_cap(DEFAULT_LIST_CAP if default_rows is None else default_rows)
    size = max(1, int(page_size or 1))
    return max(1, -(-rows // size))     # ceil(rows / size)


# 重复度刹车（见 RepetitionBrake）：连续这么多条「一个新归一标题都没带来」就停止翻页。
# 400 = 8 页 × 50，取值依据见 RepetitionBrake 文档字符串里的实测分离度。
DEFAULT_REPEAT_STALL_ROWS = 400

_BRACKETS_RE = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]")
_DIGITS_RE = re.compile(r"\d+")
_LEAD_SEG_RE = re.compile(r"^[^-|/／]{1,6}[-|/／]")
_SPACE_RE = re.compile(r"\s+")


def normalize_title_for_repetition(title) -> str:
    """把岗位标题压成「角色核」，用于判重复度。去括号内容（含 `(J726033)` 这类岗位号）、
    去数字、去开头的「姓名-」「城市-」段、去空白。

    这不是给用户看的标题，只用来回答一个问题：**再翻一页还能不能拿到没见过的岗位角色**。"""
    text = str(title or "")
    text = _BRACKETS_RE.sub("", text)
    text = _DIGITS_RE.sub("", text)
    text = _LEAD_SEG_RE.sub("", text)
    return _SPACE_RE.sub("", text).strip("-|/／ ")


def resolve_repeat_stall_rows(default: int = DEFAULT_REPEAT_STALL_ROWS) -> int:
    """env CRAWL_REPEAT_STALL_ROWS 调档；设 0 = 关掉重复度刹车（回到「只受 _MAX_JOBS 约束」）。"""
    return _env_int("CRAWL_REPEAT_STALL_ROWS", default)


class RepetitionBrake:
    """「同一个岗 × N 家门店」批量发布源的刹车。

    为什么需要它：2026-09-04 把单源上限从 600 抬到 8000 之后，一轮就多入库 5.2 万个岗，
    **其中 2.1 万（41%）是三家门店批量发布**——星巴克 9,044 行归一后只有 34 种标题
    （96% 是「星级咖啡师」三种），来伊份 7,301 行只有 90 种，喜茶 5,775 行只有 234 种。
    后果是可测的：杭州 20%、上海 12%、北京 9.7% 的在招岗变成了这三家的门店副本，
    正是「精准 > 规模」要挡的东西。

    判据 = **连续 stall_rows 条都没带来一个新的归一标题**（`normalize_title_for_repetition`）。
    用归一标题而不是岗位 id：批量门店岗每条 id 都不同，只有标题能暴露同质。
    2026-09-04 用库里 41,285 条真实数据量过这条判据的分离度（归一后重复率）：
      批量：星巴克 99.6%（34 种）/ 来伊份 98.8%（90 种）/ 喜茶 95.9%（234 种）
      正常：奇瑞 47.7%（3,445 种）/ 新东方 46.4%（2,451 种）/ 我爱我家 42.7%（4,587 种）
    两组差着一个数量级，中间没有骑墙的源；奇瑞每 50 条能带来 ~26 个新角色，永远刹不住。
    stall_rows 默认 400（8 页）是刻意保守：连续 400 个岗位零个新角色才算实锤，
    避免「某几页恰好同部门」的正常源被误刹。

    ⚠️ 刹停 = **没抓全**，调用方必须让 fetch_complete=False。beisen/feishu 都开了
    list-absence 探活，把「没翻到的尾巴」当成「列表缺席」会整批误判撤岗
    （CLAUDE.md §4 立碑的误杀在招岗）。现有实现按 `len(rows) >= total` 判定，
    刹停时天然为 False —— 改这段务必保住这个不变量。
    """

    def __init__(self, stall_rows: int = None):
        self.stall_rows = resolve_repeat_stall_rows() if stall_rows is None else stall_rows
        self._seen = set()
        self._rows_since_new = 0
        self.tripped = False

    def observe(self, titles) -> bool:
        """喂一页的标题，返回「是否该停止翻页」。stall_rows<=0 表示刹车关闭，恒返回 False。"""
        fresh = 0
        count = 0
        for title in titles or []:
            count += 1
            key = normalize_title_for_repetition(title)
            if key and key not in self._seen:
                self._seen.add(key)
                fresh += 1
        if self.stall_rows <= 0:
            return False
        if fresh:
            self._rows_since_new = 0
        else:
            self._rows_since_new += count
        if self._rows_since_new >= self.stall_rows:
            self.tripped = True
        return self.tripped


@dataclass
class RawJob:
    company: str
    title: str
    location: Optional[str] = None
    job_type: Optional[str] = None
    summary: Optional[str] = None
    jd_url: str = ""
    apply_url: Optional[str] = None
    salary_text: Optional[str] = None
    posted_at: Optional[str] = None
    experience: Optional[str] = None   # 经验要求；adapter 可直填，否则由 normalizer 从全文抽取
    education: Optional[str] = None     # 学历要求；同上
    deadline: Optional[str] = None      # 投递截止；同上


@dataclass
class PageResult:
    """paginate_all 每页 fetch 闭包的返回：本页条目 + 接口本次自报的总数/总页数（都可为 None）。"""
    items: list
    total: Optional[int] = None   # 接口自报「岗位总数」（分母）；None = 本页没给/接口无此字段
    total_pages: Optional[int] = None  # 接口自报「总页数」（如 hotjob 的 totalPage）；有它就按页数翻到底，
    #                                    不受「短页」误判——治接口只报页数、又会回瞬时/限流短页的源。


def paginate_all(
    fetch_page: Callable[[int], PageResult],
    *,
    page_size: int,
    first_page: int = 1,
    max_pages: int = 200,
    delay_seconds: float = 0.0,
    logger: Optional[logging.Logger] = None,
    label: str = "",
) -> Tuple[list, Optional[int], bool]:
    """框架级「翻到底」纪律（治抓不全的病根：各 adapter 硬编码小分页上限）。

    翻页直到抓全，返回 ``(all_items, reported_total, fetch_complete)``——正好对上
    BaseAdapter.reported_total / fetch_complete 契约，adapter 抓完直接赋值即可。

    参数：
      fetch_page(page_index) -> PageResult：单页抓取闭包。闭包自己把 page_index 映射成
        接口翻页参数（page 型直接用；offset 型传 first_page=0，内部算 offset=page_index*page_size）。
      page_size：接口**实际每页返回**的条数（不是随便请求的值）——短页判定末页要靠它，
        请求的 pageSize 必须与之一致，否则 offset 递进会跳漏。
      first_page：起始页号（page 型接口多为 1；offset/0-based 传 0）。
      max_pages：安全上限（防接口异常/死循环）。命中 → 停 + warn + complete=False。
      delay_seconds：每页间隔（礼貌爬取/限速）。

    停止条件（按序）：
      1. 达到 max_pages 安全上限 → 停，complete=False，告警。
      2. 空页 → 停；complete = total 未知（自然收尾）或已收满（collected>=total）。
      3. total 已知且 collected>=total → 停，complete=True。
      4. total_pages 已知且已翻满该页数 → 停，complete=True（按总页数翻到底，不被短页误判；
         治「只报 totalPage、又会回瞬时/限流短页」的源，如 hotjob）。
      5. total 与 total_pages 都未知、且本页 < page_size（末页）→ 停，complete=True，total 记为已抓数。

    异常语义（沿用 tencent/jd 已验证范式）：
      - 首页（尚未抓到任何一页）抛异常 → 原样上抛，交给 run.py 记 failed。
      - 后续页抛异常 → 保留已抓条目、complete=False、停止（尽力而为，不炸穿夜间 cron）。
    """
    log = logger or globals()["logger"]
    items: list = []
    total: Optional[int] = None
    total_pages: Optional[int] = None
    complete = False
    page = first_page
    pages_done = 0

    while True:
        if pages_done >= max_pages:
            log.warning("%s: 命中安全翻页上限 %d，可能未抓全（got=%d total=%s）",
                        label or "paginate", max_pages, len(items), total)
            complete = False
            break
        try:
            result = fetch_page(page)
        except Exception:
            if pages_done == 0:
                raise  # 首页失败 → 交上层记 failed
            log.warning("%s: 第 %d 页抓取失败，保留已抓 %d 条（尽力而为）",
                        label or "paginate", pages_done + 1, len(items))
            complete = False
            break

        page_items = list(result.items or [])
        if result.total is not None and total is None:
            total = result.total
        if result.total_pages is not None and total_pages is None:
            total_pages = result.total_pages
        pages_done += 1

        if not page_items:
            complete = (total is None) or (len(items) >= total)
            break
        items.extend(page_items)
        if total is not None and len(items) >= total:
            complete = True
            break
        if total_pages is not None and pages_done >= total_pages:
            complete = True   # 按接口自报总页数翻到底（不受短页误判）
            break
        # 短页判末页仅在 total 与 total_pages 都未知时兜底（接口既不报总数也不报页数）。
        if total is None and total_pages is None and len(page_items) < page_size:
            complete = True
            break

        page += 1
        if delay_seconds:
            time.sleep(delay_seconds)

    if total is None and complete:
        total = len(items)   # 未知 total 自然收尾：诚实把「看见的全部」记为分母
    return items, total, complete


class BaseAdapter:
    """抓取适配器基类。每个企业源继承此类实现 fetch + parse。"""

    name: str = "base"
    regions = frozenset({"CN"})
    user_agent: str = (
        "JobRadarBot/0.1 (+https://github.com/job-radar; compliance@example.com)"
    )
    timeout: int = 30

    # 抓全率可观测（阶段①）：抓取时由 adapter 填，run.py 收尾写进 crawl_runs 供覆盖率监控。
    #   reported_total = 官网接口本次自报的岗位总数（分母）；None = 接口无此字段/纯 HTML/不可测（诚实盲区）。
    #     每次抓取都当场重新读，天然跟随官网实时变化（不是存死值）。
    #   fetch_complete = 本次是否抓到了 reported_total 的全部（fetched >= total 或按接口翻完）。
    reported_total: Optional[int] = None
    fetch_complete: bool = False

    def fetch(self, source_url: str) -> str:
        """从 source_url 获取页面 HTML 或 JSON 文本。"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,*/*",
            "Accept-Language": "zh-CN,en;q=0.9",
        }
        response = httpx.get(source_url, headers=headers, timeout=self.timeout,
                             follow_redirects=True)
        response.raise_for_status()

        # 检查是否被拦截
        text = response.text
        if self._is_blocked(text, response.status_code):
            raise RuntimeError(f"Source {self.name} blocked: status={response.status_code}")

        return text

    def parse(self, html: str) -> List[RawJob]:
        """从页面内容解析岗位列表。子类必须实现。"""
        raise NotImplementedError

    def should_skip(self, source_url: str) -> Optional[str]:
        """
        检查是否应该跳过该源。
        返回 None 表示不跳过；返回字符串表示跳过原因。
        """
        parsed = urlparse(source_url)
        key = ((parsed.scheme or "").lower(), (parsed.hostname or "").lower())
        # 双检锁（同 robots.py）：锁内只读写缓存，HEAD 请求在锁外做——持锁做 5s 网络 I/O
        # 会把所有 host 的首次预检串行化。同 host 极小概率重复探一次，可接受。
        with _HEAD_SKIP_CACHE_LOCK:
            if key in _HEAD_SKIP_CACHE:
                return _HEAD_SKIP_CACHE[key]
        # 只有真实 HTTP 响应的结论才是 host 级信号；网络异常 fail-open 且不缓存，留给下个源重试。
        try:
            headers = {"User-Agent": self.user_agent}
            resp = httpx.head(source_url, headers=headers, timeout=5, follow_redirects=True)
            if resp.status_code in (403, 429):
                result = f"HTTP {resp.status_code}"
            elif resp.status_code >= 500:
                result = f"HTTP {resp.status_code} (server error)"
            else:
                result = None
        except Exception:
            return None
        with _HEAD_SKIP_CACHE_LOCK:
            if key not in _HEAD_SKIP_CACHE:
                _HEAD_SKIP_CACHE[key] = result
            return _HEAD_SKIP_CACHE[key]

    @staticmethod
    def _is_blocked(text: str, status_code: int) -> bool:
        """检查页面是否是反爬/验证码/登录墙。"""
        lower = text.lower()
        if status_code == 403:
            return True
        if "captcha" in lower or "verify" in lower and "human" in lower:
            return True
        if "login" in lower and "<form" in lower and "password" in lower:
            return True
        if "访问受限" in text or "请求过于频繁" in text or "您的IP" in text:
            return True
        return False
