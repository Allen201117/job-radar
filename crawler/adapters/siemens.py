"""Siemens 的 Avature 子类；保留其中国关键词收窄和每页 6 条契约。"""
from typing import List

import httpx

import normalizer
from .avature import AvatureAdapter


class SiemensAdapter(AvatureAdapter):
    name = "siemens"
    company_name = "Siemens"
    SEARCH_URL = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs"
    DETAIL_ORIGIN = "https://jobs.siemens.com"
    DROP_UNKNOWN_LOCATION = True
    PAGE_SIZE = 6
    MAX_PAGES = 60
    _REGION_TERMS = {
        "CN": "China", "HK": "Hong Kong", "US": "United States",
        "SG": "Singapore", "Remote": "Remote",
    }

    def _search_terms(self) -> List[str]:
        regions = normalizer.source_regions(getattr(self, "regions", None))
        terms = [self._REGION_TERMS[region] for region in sorted(regions)
                 if region in self._REGION_TERMS]
        return terms or [""]

    def _base_url(self, source_url: str) -> str:
        # 保留历史兼容：旧 sources 若填 careers/search，仍路由到实际 SearchJobs 入口。
        return self.SEARCH_URL if "careers/search" in source_url.lower() else source_url

    def _client(self, **kwargs):
        # 兼容 Siemens 既有单测/调用方对本模块 httpx.Client 的注入点。
        return httpx.Client(**kwargs)
