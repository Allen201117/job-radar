"""
通用 Eightfold 适配器（eightfold.ai 公开 Talent Intelligence 接口，无需鉴权）。

source_url = https://{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}
（如汇丰：https://hsbc.eightfold.ai/api/apply/v2/jobs?domain=hsbc.com）
大量在华跨国企业（金融/制造/消费…外企100强）用 eightfold，greenhouse/lever/workday 都抓不到。
一套适配覆盖任意 eightfold 租户——新增公司只需加一行 sources（source_url 填该端点）。

服务「在华外企」：用接口的 `location` 参数**服务端**收窄到中国/香港，只抓在华岗位；
jd_url 用接口返回的 `canonicalPositionUrl`（公司自有 careers 域名的真实 per-job 链接，已 live 验证），
缺失时回退 {origin}/careers/job/{id}。接口 `num` 上限 10，必须翻页。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse, parse_qs

import httpx

import normalizer
from .base import BaseAdapter, RawJob


class EightfoldAdapter(BaseAdapter):
    name = "eightfold"
    max_pages = 25          # num=10/页 → 每个地点最多约 250 在华岗（打通通道足够，非全量）
    china_locations = ("China", "Hong Kong")  # 服务端按地点收窄到大中华区

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def fetch(self, source_url: str) -> str:
        p = urlparse(source_url)
        origin = f"{p.scheme}://{p.netloc}"
        path = p.path or "/api/apply/v2/jobs"
        domain = (parse_qs(p.query).get("domain") or [""])[0]
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}

        collected: List[dict] = []
        seen_ids = set()
        for loc in self.china_locations:
            for page in range(self.max_pages):
                params = {"domain": domain, "location": loc,
                          "start": page * 10, "num": 10, "sort_by": "relevance"}
                r = httpx.get(f"{origin}{path}", params=params, headers=headers, timeout=self.timeout)
                r.raise_for_status()
                positions = r.json().get("positions", []) or []
                if not positions:
                    break
                for pos in positions:
                    pid = pos.get("id")
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    collected.append(pos)
                if len(positions) < 10:
                    break
        return json.dumps({"_origin": origin, "positions": collected}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        origin = data.get("_origin", "")
        out: List[RawJob] = []
        seen_urls = set()
        for p in data.get("positions", []):
            if not isinstance(p, dict):
                continue
            title = (p.get("name") or "").strip()
            location = p.get("location") or None
            if not title:
                continue
            # 服务端已按地点收窄，这里再用 is_china_location 兜一层（排除少数串到的非华岗）
            if not normalizer.is_china_location(location):
                continue
            jd_url = (p.get("canonicalPositionUrl") or "").strip()
            if not jd_url:
                pid = p.get("id")
                if not pid:
                    continue
                jd_url = f"{origin}/careers/job/{pid}"
            if jd_url in seen_urls:
                continue
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,
                summary=None,  # job_description 是长 HTML，详情点链接看；此处不灌库
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,
            ))
        return out
