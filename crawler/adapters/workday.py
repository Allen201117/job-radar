"""
通用 Workday 适配器（公开 CXS API，无需鉴权）。

source_url = https://{host}/wday/cxs/{tenant}/{site}/jobs   （host 形如 {tenant}.wd{N}.myworkdayjobs.com）
大量在华跨国企业（外企100强主力：NVIDIA / 制造 / 金融 / 消费…）用 Workday，greenhouse/lever 抓不到。
一套适配覆盖任意 Workday 租户 —— 新增公司只需加一行 sources（source_url 填 CXS jobs 端点）。

服务「在华外企」：用 Workday 的 location facet **服务端**过滤到大中华区（China/Hong Kong/Macau），
只抓在华岗位，避免全球岗位灌入（list 接口 locationsText 常是「N Locations」不可靠，故用 facet）。
jd_url = {host}/{site}{externalPath}（Workday 托管的稳定 per-job 页，已 live 验证渲染对应岗位）。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import BaseAdapter, RawJob

# 大中华区国家级 facet 关键词（China / Mainland China / Greater China / Hong Kong / Macau…）
_GREATER_CHINA = ("china", "中国", "hong kong", "香港", "macau", "macao", "澳门")


def _is_china_country(desc: str) -> bool:
    """是否大中华区**国家级** facet 项：含关键词、排除含逗号的城市级项（China, Beijing）与台湾。"""
    d = str(desc or "").strip().lower()
    if not d or "," in d or "taiwan" in d or "台湾" in d or "台灣" in d:
        return False
    return any(k in d for k in _GREATER_CHINA)


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    max_pages = 8  # 每页 20 → 单源最多约 160 岗

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def _parse_endpoint(self, source_url: str):
        p = urlparse(source_url)
        self._host = f"{p.scheme}://{p.netloc}"
        parts = [x for x in (p.path or "").split("/") if x]
        # 期望 ['wday','cxs',{tenant},{site},'jobs'] → site 是 cxs 后第 2 段
        try:
            i = parts.index("cxs")
            self._site = parts[i + 2]
        except (ValueError, IndexError):
            self._site = parts[-2] if len(parts) >= 2 else ""

    def fetch(self, source_url: str) -> str:
        self._parse_endpoint(source_url)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        # 1) 取 facets，找大中华区 location facet（param + ids）
        r = httpx.post(source_url, json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                       headers=headers, timeout=self.timeout)
        r.raise_for_status()
        applied = self._china_facets(r.json().get("facets", []))

        # 2) 分页抓在华岗位（有 facet 则服务端已过滤；无 facet 则全量、parse 再按 location 兜底过滤）
        collected: List[dict] = []
        for page in range(self.max_pages):
            body = {"appliedFacets": applied, "limit": 20, "offset": page * 20, "searchText": ""}
            rr = httpx.post(source_url, json=body, headers=headers, timeout=self.timeout)
            rr.raise_for_status()
            posts = rr.json().get("jobPostings", []) or []
            if not posts:
                break
            collected.extend(posts)
            if len(posts) < 20:
                break
        return json.dumps({
            "_host": self._host, "_site": self._site,
            "_china_filtered": bool(applied), "posts": collected,
        }, ensure_ascii=False)

    @staticmethod
    def _china_facets(facets) -> dict:
        """深搜 facets，返回 {facetParameter: [大中华区国家项 id...]}（精确匹配国家级描述）。"""
        found: dict = {}

        def walk(node):
            if isinstance(node, dict):
                param = node.get("facetParameter")
                for v in node.get("values", []) or []:
                    if param and v.get("id") and _is_china_country(v.get("descriptor", "")):
                        found.setdefault(param, []).append(v["id"])
                for v in node.get("values", []) or []:
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        for f in facets:
            walk(f)
        return found

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        host = data.get("_host", "")
        site = data.get("_site", "")
        china_filtered = data.get("_china_filtered")

        out: List[RawJob] = []
        for p in data.get("posts", []):
            if not isinstance(p, dict):
                continue
            title = (p.get("title") or "").strip()
            ep = (p.get("externalPath") or "").strip()
            if not title or not ep:
                continue
            location = self._loc_from_path(ep) or (p.get("locationsText") or None)
            # facet 已服务端过滤则全部在华；否则按 location 文本兜底（host 不同租户 facet 名异常时）
            if not china_filtered and not normalizer.keep_for_china_radar(location):
                continue
            jd_url = f"{host}/{site}{ep}"
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,
                summary=None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,  # postedOn 是相对文案（"Posted Yesterday"），不伪造日期
            ))
        return out

    @staticmethod
    def _loc_from_path(ep: str) -> Optional[str]:
        # externalPath: /job/China-Beijing/Title_JRxxxx → 第 2 段 "China-Beijing" → "China, Beijing"
        parts = [x for x in ep.split("/") if x]
        if len(parts) >= 2 and parts[0].lower() == "job":
            seg = parts[1].replace("-", ", ").strip()
            return seg or None
        return None
