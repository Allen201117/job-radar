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
from .base import BaseAdapter, RawJob, resolve_detail_cap


class SmartRecruitersAdapter(BaseAdapter):
    name = "smartrecruiters"

    def should_skip(self, source_url: str):
        return None  # 公开 JSON API，跳过 HEAD 预检，由 GET 暴露真实错误

    def fetch(self, source_url: str) -> str:
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        resp = httpx.get(source_url, headers=headers, timeout=self.timeout, follow_redirects=True)
        resp.raise_for_status()
        # 逐岗 detail 抓正文 —— 列表接口（/postings）无正文，外企卡片 JD 因此全空。
        # GET /companies/{slug}/postings/{id} → jobAd.sections.{jobDescription,responsibilities,qualifications}.text
        # （HTML；run.py 的 clean_summary 去标签解实体，summary 有正文后 extract_job_type 也能从中推断类型）。
        # 只补将保留的在华岗，单源封顶防夜间全量被拖垮；失败该岗无摘要、不影响入库。
        try:
            data = json.loads(resp.text)
        except (json.JSONDecodeError, TypeError):
            return resp.text
        rows = data.get("content", []) if isinstance(data, dict) else []
        self._enrich_descriptions(rows, headers)
        return json.dumps(data, ensure_ascii=False)

    _DETAIL_CAP = 300  # 单源逐岗 detail 抓取上限，避免拖垮夜间全量

    def _enrich_descriptions(self, rows: List[dict], headers: dict):
        """对将保留的在华岗逐个调 detail 端点，把 jobAd 各 section 文本拼成正文挂到 row['_jd']。"""
        n = 0
        for j in rows:
            if n >= resolve_detail_cap(self._DETAIL_CAP):
                break
            if not isinstance(j, dict):
                continue
            if not normalizer.keep_for_china_radar(_location_str(j.get("location"))):
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
            if not normalizer.keep_for_china_radar(location):
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


def _location_str(loc) -> Optional[str]:
    if not isinstance(loc, dict):
        return None
    if loc.get("remote") is True:
        # 远程岗位地点串带上国家，便于 keep_for_china_radar 判定是否绑定海外
        country = loc.get("country") or ""
        return f"Remote {country}".strip()
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    joined = ", ".join(p for p in parts if p)
    return joined or None
