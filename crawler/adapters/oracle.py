"""
通用 Oracle 招聘云适配器（Oracle Fusion / HCM Recruiting Cloud，公开 CE REST API，无需鉴权）。

source_url = https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber={site}
  host 形如 {tenant}.fa.{region}.oraclecloud.com（公司 careers 页会跳转到该 host）；site 形如 CX_1 / CX_1001。
大量「自建招聘门户」的外企巨头其实跑在 Oracle 招聘云上（霍尼韦尔 / 美国运通 / 诺基亚 / 纽约梅隆 / Emerson / Akamai…），
greenhouse/workday 抓不到。一套适配覆盖任意 Oracle 租户 —— 新增公司只需加一行 sources（填 host+siteNumber）。

服务「在华外企」：用 locationsFacet 的大中华区 facet Id **服务端**过滤到在华岗位（China/Hong Kong/Macau），
避免全球岗灌入。jd_url = {host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}（Oracle 托管的稳定逐岗页，已 live 验证）。
"""
import json
from typing import List, Optional
from urllib.parse import urlparse, parse_qs

import httpx

import normalizer
from .base import BaseAdapter, RawJob

_GREATER_CHINA = ("china", "中国", "hong kong", "香港", "macau", "macao", "澳门")
_TAIWAN = ("taiwan", "台湾", "台灣", "chinese taipei")


def _is_china_facet(name: str) -> bool:
    n = str(name or "").strip().lower()
    if not n or any(t in n for t in _TAIWAN):
        return False
    return any(k in n for k in _GREATER_CHINA)


class OracleAdapter(BaseAdapter):
    name = "oracle"
    max_pages = 25  # 每页 20 → 单源最多约 500 在华岗（够大租户，分页 <20 即停）

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检

    def _parse_endpoint(self, source_url: str):
        p = urlparse(source_url)
        self._host = f"{p.scheme}://{p.netloc}"
        self._api = f"{self._host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        # siteNumber 可能在 query（?siteNumber=CX_1）或 finder=findReqs;siteNumber=CX_1
        site = ""
        qs = parse_qs(p.query or "")
        if qs.get("siteNumber"):
            site = qs["siteNumber"][0]
        else:
            finder = (qs.get("finder", [""])[0]) or (p.query or "")
            for part in finder.split(";"):
                if part.strip().startswith("siteNumber") and "=" in part:
                    site = part.split("=", 1)[1].split(",")[0].strip()
                    break
        self._site = site

    def _get(self, finder_extra: str) -> dict:
        """调一次 CE API；finder_extra 形如 ',limit=20,offset=40,selectedLocationsFacet=...'。"""
        url = (f"{self._api}?onlyData=true&expand=requisitionList"
               f"&finder=findReqs;siteNumber={self._site}{finder_extra}")
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        r = httpx.get(url, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        items = r.json().get("items", []) or []
        return items[0] if items else {}

    def fetch(self, source_url: str) -> str:
        self._parse_endpoint(source_url)
        # 1) 取 locationsFacet，挑大中华区 facet Id（扁平列表，含国家级 'China' 与城市级 'Shanghai, China'）。
        first = self._get(",limit=5")
        facets = first.get("locationsFacet", []) or []
        china_ids = [str(f.get("Id")) for f in facets if f.get("Id") and _is_china_facet(f.get("Name"))]

        trusted: List[dict] = []
        seen = set()
        if china_ids:
            # 2) 服务端 facet 过滤分页（这些是**可信在华**岗，parse 不再过滤）。
            facet_param = f",selectedLocationsFacet={','.join(china_ids)}"
            for page in range(self.max_pages):
                top = self._get(f"{facet_param},limit=20,offset={page * 20}")
                reqs = top.get("requisitionList", []) or []
                if not reqs:
                    break
                for j in reqs:
                    jid = str(j.get("Id") or "").strip()
                    if jid and jid not in seen:
                        seen.add(jid)
                        trusted.append(j)
                if len(reqs) < 20:
                    break

        # 3) 兜底：facet 没找到大中华区（个别租户 facet 名用城市拼写差异）时，用 keyword=China 文本召回，
        # parse 再按 is_china_location 严格过滤。trusted 已有则跳过（facet 可信、零额外开销）。
        text_jobs: List[dict] = []
        if not trusted:
            for kw in ("China", "Hong Kong"):
                for page in range(self.max_pages):
                    top = self._get(f",keyword={kw},limit=20,offset={page * 20}")
                    reqs = top.get("requisitionList", []) or []
                    if not reqs:
                        break
                    for j in reqs:
                        jid = str(j.get("Id") or "").strip()
                        if jid and jid not in seen:
                            seen.add(jid)
                            text_jobs.append(j)
                    if len(reqs) < 20:
                        break

        return json.dumps({
            "_host": self._host, "_site": self._site,
            "trusted_jobs": trusted, "text_jobs": text_jobs,
        }, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        host = data.get("_host", "")
        site = data.get("_site", "")
        out: List[RawJob] = []
        seen_urls = set()

        def emit(j, trusted):
            if not isinstance(j, dict):
                return
            title = (j.get("Title") or "").strip()
            jid = str(j.get("Id") or "").strip()
            if not title or not jid:
                return
            location = (j.get("PrimaryLocation") or "").strip() or None
            # trusted（facet 已服务端过滤）全部在华直接收；text（keyword 召回）按 location 严格判定在华。
            if not trusted and not normalizer.is_china_location(location):
                return
            jd_url = f"{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}"
            if jd_url in seen_urls:
                return
            seen_urls.add(jd_url)
            out.append(RawJob(
                company="",  # 由 sources.company 兜底
                title=title,
                location=location,
                job_type=None,
                summary=None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=None,
            ))

        for j in data.get("trusted_jobs", []):
            emit(j, trusted=True)
        for j in data.get("text_jobs", []):
            emit(j, trusted=False)
        return out
