"""
Amazon.jobs 公开搜索 API 适配器（无需鉴权）。

source_url = https://www.amazon.jobs/en/search.json?normalized_country_code[]=CHN&result_limit=100
Amazon 完全自建招聘系统（非 greenhouse/workday/oracle，外企100强里的「硬骨头」），公开 search.json
按国家码 normalized_country_code 服务端筛 + offset 分页。一套适配即可稳定抓在华岗。
服务「在华外企」：source_url 用 CHN 限定中国大陆（如需港澳可加 HKG/MAC）；
地点 "City, CHN" 归一为 "City, China" 以过 is_china_location 兜底。
jd_url = https://www.amazon.jobs{job_path}（Amazon 托管的稳定逐岗页，已 live 验证）。
"""
import json
import re
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, urlencode

import httpx

import normalizer
from .base import BaseAdapter, RawJob

# Amazon.jobs 由 Akamai 前置，需常见浏览器 UA 才稳定返回 JSON（JobRadarBot UA 会被静默拦）。
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _norm_loc(loc: Optional[str]) -> Optional[str]:
    """Amazon 地点 'Shenzhen, CHN' → 'Shenzhen, China'（CHN 国家码归一，便于 is_china_location 识别）。"""
    if not loc:
        return None
    s = re.sub(r"(?i),?\s*\bCHN\b", ", China", str(loc)).strip().strip(",").strip()
    return s or None


def _job_summary(j: dict) -> Optional[str]:
    """从 search.json 列表项直接组装 JD 正文（已 live 验证含完整 description ~3k 字 + 任职要求）。
    无需逐岗 detail（amazon.jobs 逐岗 .json 被 Akamai 拦 406），列表自带正文即够 ≥60 字门。
    HTML 标签/实体由 run.py 的 normalizer.clean_summary 统一清洗+截断。"""
    parts = [j.get("description"), j.get("basic_qualifications"), j.get("preferred_qualifications")]
    text = "\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return text or None


class AmazonAdapter(BaseAdapter):
    name = "amazon"
    max_pages = 30  # result_limit=100/页 → 最多 3000 岗（覆盖在华全量，<100 即停）

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        p = urlparse(source_url)
        base = f"{p.scheme}://{p.netloc}{p.path}"
        params = {k: list(v) for k, v in parse_qs(p.query, keep_blank_values=True).items()}
        headers = {"User-Agent": _BROWSER_UA, "Accept": "application/json",
                   "Accept-Language": "en-US,en;q=0.9"}
        limit = 100
        collected: List[dict] = []
        seen = set()
        for page in range(self.max_pages):
            q = dict(params)
            q["result_limit"] = [str(limit)]
            q["offset"] = [str(page * limit)]
            url = f"{base}?{urlencode(q, doseq=True)}"
            r = httpx.get(url, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            jobs = r.json().get("jobs", []) or []
            if not jobs:
                break
            for j in jobs:
                key = j.get("job_path") or j.get("id_icims")
                if key and key not in seen:
                    seen.add(key)
                    collected.append(j)
            if len(jobs) < limit:
                break
        return json.dumps({"jobs": collected}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        out: List[RawJob] = []
        seen_urls = set()
        for j in (data.get("jobs", []) if isinstance(data, dict) else []):
            if not isinstance(j, dict):
                continue
            title = (j.get("title") or "").strip()
            path = (j.get("job_path") or "").strip()
            if not title or not path:
                continue
            jd_url = f"https://www.amazon.jobs{path}" if path.startswith("/") else path
            if jd_url in seen_urls:
                continue
            location = _norm_loc(j.get("normalized_location") or j.get("location"))
            # source_url 已按 CHN 服务端筛；这里再用 is_china_location 兜底（排除偶发非华/母国远程岗）
            if not normalizer.is_china_location(location):
                continue
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,  # 由 normalizer 从标题抽取社招/校招/实习
                summary=_job_summary(j),  # 列表自带完整 JD 正文 → 直接入库，治 0% 覆盖薄卡
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(j.get("posted_date") or None),
            ))
        return out
