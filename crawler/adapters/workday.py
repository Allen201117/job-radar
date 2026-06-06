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

# 大中华区 facet 关键词（China / Mainland China / Greater China / Hong Kong / Macau…）
_GREATER_CHINA = ("china", "中国", "hong kong", "香港", "macau", "macao", "澳门")
# 台湾不属本雷达「在华」口径，排除
_TAIWAN = ("taiwan", "台湾", "台灣", "chinese taipei")


def _is_china_facet(desc: str) -> bool:
    """是否大中华区 facet 项：含 China/HK/Macau 关键词、排除台湾。
    允许城市级（'China, Beijing'）—— 不同租户把可选叶子放在国家级或城市级 param，按 param 分组后逐组试探。"""
    d = str(desc or "").strip().lower()
    if not d or any(t in d for t in _TAIWAN):
        return False
    return any(k in d for k in _GREATER_CHINA)


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    max_pages = 25  # 每页 20 → 单源最多约 500 在华岗（容纳 AstraZeneca 等大租户，避免静默截断；分页 <20 即停）

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
        # 1) 取 facets，按 param 分组收集大中华区候选 id
        r = httpx.post(source_url, json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                       headers=headers, timeout=self.timeout)
        r.raise_for_status()
        candidates = self._china_facet_candidates(r.json().get("facets", []))
        # 2) 逐 param-group 试探命中数，取最多的**单组**应用（不跨 param 混用，否则 AND 坍缩成交集）
        applied = self._pick_best_facet(source_url, headers, candidates)

        # 3) 分页抓在华岗位（有 facet 则服务端已过滤；无 facet 则全量、parse 再按 location 兜底过滤）
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
    def _china_facet_candidates(facets) -> dict:
        """深搜 facets，按 facetParameter 分组收集大中华区相关叶子 id（含 'China, City' 城市级）。
        返回 {param: [id...]}。**不跨 param 合并** —— 不同租户的可选叶子放在 locationHierarchy1 /
        locationCountry / locations 等不同 param，且 locationCountry 的国家聚合项常不可直接选（应用返回 0）。
        因此分组后由 _pick_best_facet 逐组试探、取命中最多的单组，自适应各租户 facet 结构。"""
        groups: dict = {}

        def walk(node):
            if isinstance(node, dict):
                param = node.get("facetParameter")
                for v in node.get("values", []) or []:
                    if param and v.get("id") and _is_china_facet(v.get("descriptor", "")):
                        ids = groups.setdefault(param, [])
                        if v["id"] not in ids:
                            ids.append(v["id"])
                for v in node.get("values", []) or []:
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        for f in facets:
            walk(f)
        return groups

    def _pick_best_facet(self, source_url: str, headers: dict, candidates: dict) -> dict:
        """逐 param-group 试探 total，返回命中最多的**单组** {param:[ids]}；全 0 则 {} 兜底（parse 再按 location 过滤）。"""
        best: dict = {}
        best_total = 0
        for param, ids in candidates.items():
            if not ids:
                continue
            try:
                resp = httpx.post(
                    source_url, json={"appliedFacets": {param: ids}, "limit": 1, "offset": 0, "searchText": ""},
                    headers=headers, timeout=self.timeout)
                total = resp.json().get("total") or 0
            except (httpx.HTTPError, ValueError, TypeError):
                total = 0
            if total > best_total:
                best, best_total = {param: ids}, total
        return best

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
            # facet 已服务端过滤则全部在华；否则按 location 严格判定在华（大陆/港/澳）。
            # 外企 Workday 的 "Remote" 多指母国远程而非中国，故用 is_china_location 而非 keep_for_china_radar，
            # 避免无 facet 时泄漏非华岗（如 "Remote - Delhi"）。
            if not china_filtered and not normalizer.is_china_location(location):
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
