import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple
import httpx


logger = logging.getLogger(__name__)


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
    """paginate_all 每页 fetch 闭包的返回：本页条目 + 接口本次自报的总数（可为 None）。"""
    items: list
    total: Optional[int] = None   # 接口自报总数（分母）；None = 本页没给/接口无此字段


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
      4. total 未知且本页 < page_size（末页）→ 停，complete=True，total 记为已抓数。

    异常语义（沿用 tencent/jd 已验证范式）：
      - 首页（尚未抓到任何一页）抛异常 → 原样上抛，交给 run.py 记 failed。
      - 后续页抛异常 → 保留已抓条目、complete=False、停止（尽力而为，不炸穿夜间 cron）。
    """
    log = logger or globals()["logger"]
    items: list = []
    total: Optional[int] = None
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
        pages_done += 1

        if not page_items:
            complete = (total is None) or (len(items) >= total)
            break
        items.extend(page_items)
        if total is not None and len(items) >= total:
            complete = True
            break
        if total is None and len(page_items) < page_size:
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
        try:
            headers = {"User-Agent": self.user_agent}
            resp = httpx.head(source_url, headers=headers, timeout=10, follow_redirects=True)
            if resp.status_code in (403, 429):
                return f"HTTP {resp.status_code}"
            if resp.status_code >= 500:
                return f"HTTP {resp.status_code} (server error)"
        except Exception as e:
            return f"Connection failed: {e}"
        return None

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
