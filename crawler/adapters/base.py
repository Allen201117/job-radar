import os
from dataclasses import dataclass, field
from typing import Optional, List
import httpx


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


class BaseAdapter:
    """抓取适配器基类。每个企业源继承此类实现 fetch + parse。"""

    name: str = "base"
    user_agent: str = (
        "JobRadarBot/0.1 (+https://github.com/job-radar; compliance@example.com)"
    )
    timeout: int = 30

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
