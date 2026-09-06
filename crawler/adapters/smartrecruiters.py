"""
通用 SmartRecruiters 适配器（公开 Posting API，无需鉴权）。

source_url = https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100
一套适配覆盖任意用 SmartRecruiters 的公司 —— 大量在华跨国企业（外企100强常见）用此 ATS。
新增公司只需加一行 sources 记录（slug = 公司在 SmartRecruiters 的 identifier）。

同 Greenhouse/Lever：服务「在华外企」覆盖，parse 只保留大中华区岗位（keep_for_china_radar）。
jd_url 用 jobs.smartrecruiters.com 托管的稳定 per-job 链接：{identifier}/{postingId}。
"""
import json
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


class SmartRecruitersAdapter(BaseAdapter):
    name = "smartrecruiters"

    _PAGE_SIZE = 100  # Posting API limit 上限
    max_pages = 100   # 安全上限 1 万岗（Bosch 全球 ~4700，留一倍余量）

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检，由 GET 暴露真实错误

    def fetch(self, source_url: str) -> str:
        # offset/limit 翻到底（旧版只吃第一页 100 条：Bosch 全球 4733 岗只留下前 100 里的
        # 15 个在华岗，深页的中国岗全漏）。totalFound 是接口权威总数 → reported_total。
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        base = source_url.split("?")[0]

        def fetch_page(page: int) -> PageResult:
            r = httpx.get(base, params={"limit": self._PAGE_SIZE, "offset": page * self._PAGE_SIZE},
                          headers=headers, timeout=self.timeout, follow_redirects=True)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                return PageResult(items=[], total=None)
            return PageResult(items=data.get("content") or [], total=data.get("totalFound"))

        rows, total, complete = paginate_all(
            fetch_page, page_size=self._PAGE_SIZE, first_page=0,
            max_pages=self.max_pages, label=f"smartrecruiters:{base}")
        self.reported_total = total
        self.fetch_complete = complete
        # 逐岗 detail 抓正文 —— 列表接口（/postings）无正文，外企卡片 JD 因此全空。
        # GET /companies/{slug}/postings/{id} → jobAd.sections.{jobDescription,responsibilities,qualifications}.text
        # （HTML；run.py 的 clean_summary 去标签解实体，summary 有正文后 extract_job_type 也能从中推断类型）。
        # 只补将保留的在华岗，单源封顶防夜间全量被拖垮；失败该岗无摘要、不影响入库。
        self._enrich_descriptions(rows, headers)
        return json.dumps({"content": rows}, ensure_ascii=False)

    _DETAIL_CAP = 300  # 单源逐岗 detail 抓取上限，避免拖垮夜间全量

    def _enrich_descriptions(self, rows: List[dict], headers: dict):
        """对将保留的在华岗逐个调 detail 端点，把 jobAd 各 section 文本拼成正文挂到 row['_jd']。"""
        n = 0
        for j in rows:
            if n >= resolve_detail_cap(self._DETAIL_CAP):
                break
            if not isinstance(j, dict):
                continue
            if not normalizer.location_in_source_regions(
                _location_str(j.get("location")), getattr(self, "regions", None)
            ):
                continue
            pid = str(j.get("id") or j.get("uuid") or "").strip()
            identifier = ((j.get("company") or {}).get("identifier") or "").strip()
            if not pid or not identifier:
                continue
            try:
                d = httpx.get(
                    f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{pid}",
                    headers=headers, timeout=self.timeout)
                if d.status_code < 300:
                    secs = (d.json().get("jobAd") or {}).get("sections") or {}
                    parts = [(secs.get(k) or {}).get("text")
                             for k in ("jobDescription", "responsibilities", "qualifications")]
                    body = " ".join(x for x in parts if x)
                    if body.strip():
                        j["_jd"] = body
                    n += 1
            except Exception:
                continue

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("content", []) if isinstance(data, dict) else []

        out: List[RawJob] = []
        for j in rows:
            if not isinstance(j, dict):
                continue
            title = (j.get("name") or "").strip()
            posting_id = str(j.get("id") or j.get("uuid") or "").strip()
            identifier = ((j.get("company") or {}).get("identifier") or "").strip()
            if not title or not posting_id or not identifier:
                continue
            jd_url = f"https://jobs.smartrecruiters.com/{identifier}/{posting_id}"
            location = _location_str(j.get("location"))
            if not normalizer.location_in_source_regions(location, getattr(self, "regions", None)):
                continue
            out.append(RawJob(
                company="",  # 由 sources.company 兜底填充
                title=title,
                location=location,
                job_type=(j.get("typeOfEmployment") or {}).get("label") if isinstance(j.get("typeOfEmployment"), dict) else None,
                summary=j.get("_jd"),  # detail 端点抓到的 jobAd 正文（HTML）；run.py clean_summary 去标签
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(j.get("releasedDate") or "")[:10] or None,
            ))
        return out


# SmartRecruiters 的 location.country 是 **ISO-3166-1 alpha-2 小写码**（"cn" / "de"），不是国名。
# geo 只认国名/城市名，于是这个字段一直等于没写：
#   · "Remote cn"  → derive_country_code=None → 116 个艾伯维中国远程岗被当成「地点不明的远程岗」，
#                    按源 regions 兜底判成 overseas（源没 CN 时）——中国岗被算成海外岗；
#   · "Remote de"  → 同样 None → 一旦源 regions 补上 CN，兜底又会把德国远程岗判成 domestic，
#                    正是 76ce4ff 刚修掉的「裸远程混进国内岗」那个坑；
#   · "He Fei Shi, An Hui Sheng, cn" → 拼音按音节分写（合肥写成 He Fei Shi），geo 的城市词典
#                    对不上，全靠这个 cn 才能判出国家 —— 认不出就整条丢掉（大陆集团 29 个中国岗漏 8 个）。
# 所以在 adapter 出口把 ISO-2 展开成英文国名：这里**确知**该字段的语义（是结构化国家码，不是自由文本），
# 在 geo 里按自由文本猜两字母码反而危险（"CN Tower, Toronto" / "Remote in the US" 都会误判）。
# 顺带把用户看到的地点从「Remote de」变成「Remote Germany」，可读性也对。
#
# ⚠️ 表里每加一个国家，都必须让 geo 能把它判成 overseas（大中华三地除外）——
# crawler/test_smartrecruiters_country.py 的契约测试会逐条验，漏一个就红。
_ISO2_COUNTRY_NAMES = {
    "cn": "China", "hk": "Hong Kong", "mo": "Macau", "tw": "Taiwan",
    "us": "United States", "sg": "Singapore",
    "ae": "United Arab Emirates", "ar": "Argentina", "at": "Austria", "au": "Australia",
    "ax": "Aland Islands", "be": "Belgium", "bg": "Bulgaria", "br": "Brazil",
    "ca": "Canada", "ch": "Switzerland", "cl": "Chile", "co": "Colombia",
    "cr": "Costa Rica", "cz": "Czechia", "de": "Germany", "dk": "Denmark",
    "do": "Dominican Republic", "dz": "Algeria", "ec": "Ecuador", "ee": "Estonia",
    "eg": "Egypt", "es": "Spain", "fi": "Finland", "fr": "France",
    "gb": "United Kingdom", "gt": "Guatemala", "hr": "Croatia", "hu": "Hungary",
    "id": "Indonesia", "ie": "Ireland", "il": "Israel", "in": "India",
    "it": "Italy", "jp": "Japan", "kh": "Cambodia", "kr": "South Korea",
    "lt": "Lithuania", "lv": "Latvia", "ma": "Morocco", "mx": "Mexico",
    "my": "Malaysia", "nl": "Netherlands", "no": "Norway", "nz": "New Zealand",
    "ph": "Philippines", "pk": "Pakistan", "pl": "Poland", "pr": "Puerto Rico",
    "pt": "Portugal", "ro": "Romania", "rs": "Serbia", "ru": "Russia",
    "sa": "Saudi Arabia", "se": "Sweden", "si": "Slovenia", "sk": "Slovakia",
    "th": "Thailand", "tn": "Tunisia", "tr": "Turkey", "ua": "Ukraine",
    "vn": "Vietnam", "za": "South Africa",
}


def _country_label(raw) -> str:
    """ISO-2 → 英文国名；认不出就原样返回（含 SmartRecruiters 自己的占位码 "xx"）。"""
    code = str(raw or "").strip()
    return _ISO2_COUNTRY_NAMES.get(code.lower(), code)


def _location_str(loc) -> Optional[str]:
    if not isinstance(loc, dict):
        return None
    country = _country_label(loc.get("country"))
    if loc.get("remote") is True:
        # 远程岗位地点串带上国家，便于 keep_for_china_radar / derive_job_scope 判定是否绑定海外
        return f"Remote {country}".strip()
    parts = [loc.get("city"), loc.get("region"), country]
    joined = ", ".join(p for p in parts if p)
    return joined or None
