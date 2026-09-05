"""中国工商银行人才招聘门户（job.icbc.com.cn）适配器（纯 httpx，零浏览器、零登录）。

⚠️ 这家曾被误判成「公告制、没有逐岗详情页」而放弃 —— 那是错的。误判来源是只在浏览器里点了
几下首页（首页确实只挂公告），**没去读列表页 onClick 的路由**。真相：「招聘岗位」这个 tab 下面
就是逐岗列表，每条都有独立的 hash 详情路由，2026-09-05 已在真实浏览器里渲染核实标题+正文都在。

接口（Umi SPA 的后端，公开、零鉴权）：
  列表  POST /icbc/trmo/post/qryPostList   body {"public":{"call_app":"F-TRM"},"private":{...}}
  详情  POST /icbc/trmo/post/qryPostById   同 body 形状，private 只要 postId
`postDepict`（岗位描述）是 **base64 → URL-encode → HTML** 三层包着的，见 `_decode_depict`。

⚠️ 列表**会返回报名已截止的岗**（社招 63 条里 15 条截止日已过），官网自己也照列。
入库前按 `enterEndTime` 剔掉，别把死岗当在招（见 `_is_open`）。
"""
import base64
import html as html_lib
import json
import re
import urllib.parse
from datetime import date
from typing import List, Optional

import httpx
from selectolax.parser import HTMLParser

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap, resolve_page_cap
from .cn_portal_tls import make_transport


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class IcbcAdapter(BaseAdapter):
    name = "icbc"

    LIST_API = "https://job.icbc.com.cn/icbc/trmo/post/qryPostList"
    DETAIL_API = "https://job.icbc.com.cn/icbc/trmo/post/qryPostById"
    REFERER = "https://job.icbc.com.cn/pc/index.html"
    # 详情是 hash 路由，两个招聘类型走不同前缀；jd_url 带 `#` → canonical 归一会原样保留（规则 2）。
    DETAIL_URL = "https://job.icbc.com.cn/pc/index.html#/main/{section}/postDetail/{post_id}"
    PAGE_SIZE = 200
    # 2026-09-05 实测约 51ms/次 → 2,615 个岗全量补约 2.2 分钟（本机口径，CI 跨境会更久）。
    # 沿用 byd 的判断：只补前 N 个 = 其余全是无正文薄卡，不进「有效在招」计数，不如一次补全。
    # ⚠️ 诚实边界：工行**校招**岗的 postDepict 本来就短（实测 52~97 字），补了也多半过不了
    # 「正文 ≥60 字」那道门；补的主要价值在社招岗（数百字的职责+要求）。
    _DETAIL_CAP = 3000

    # recruitType 取值来自站点顶栏：R00301 校园招聘 / R00302 社会招聘。
    # R00303~R00305（专项/实习等）2026-09-05 实测都是 0 条，不去猜别的码。
    _CHANNELS = (
        ("R00301", "校招", "school"),
        ("R00302", "社招", "social"),
    )

    def should_skip(self, source_url: str) -> Optional[str]:
        # ⚠️ job.icbc.com.cn 对 **HEAD 一律返 403**（换成浏览器 UA 也一样，2026-09-05 实测），
        # 而 GET 页面 / POST 接口都是 200 —— 它只是不支持 HEAD，不是在拒绝我们。
        # 不覆写的话 BaseAdapter.should_skip 会把整个源跳过、永远抓不到岗（同 cmbc 那个坑）。
        return None

    @staticmethod
    def _decode_depict(value) -> str:
        """postDepict = base64( urlencode( 富文本 HTML ) )。解不开就当没有正文，不抛。"""
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            decoded = urllib.parse.unquote(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            return ""
        text = HTMLParser(html_lib.unescape(decoded)).text()
        return re.sub(r"[ \t ]+", " ", text).strip()

    @staticmethod
    def _is_open(row: dict, today: str) -> bool:
        """报名截止日已过的岗不入库。缺 enterEndTime 时保守放行（交给下游探活）。"""
        end = str((row or {}).get("enterEndTime") or "").strip()
        return (not end) or end[:10] >= today

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json",
            "Referer": self.REFERER,
        }
        today = date.today().isoformat()
        rows: List[dict] = []
        total_sum = 0
        all_complete = True
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers,
                          transport=make_transport()) as client:
            for recruit_type, job_type, section in self._CHANNELS:
                def fetch_page(page: int, rt=recruit_type) -> PageResult:
                    response = client.post(self.LIST_API, json={
                        "public": {"call_app": "F-TRM"},
                        "private": {"pageSize": self.PAGE_SIZE, "page": page,
                                    "struIds": "", "recruitType": rt},
                    })
                    response.raise_for_status()
                    payload = response.json() or {}
                    if str(payload.get("retCode")) != "0":
                        raise RuntimeError(
                            f"icbc: qryPostList retCode={payload.get('retCode')} "
                            f"msg={payload.get('retMsg')}")
                    data = payload.get("data") or {}
                    items = data.get("dataList")
                    if items is None:
                        items = []       # 该渠道当期为空（total=0）是正常的，不是失败
                    if not isinstance(items, list):
                        raise RuntimeError("icbc: qryPostList data.dataList is not a list")
                    return PageResult(items=items, total=_int_or_none(data.get("total")))

                channel_rows, channel_total, complete = paginate_all(
                    fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                    max_pages=resolve_page_cap(self.PAGE_SIZE), label=f"icbc:{recruit_type}",
                )
                # 分母按渠道各自结算：渠道之间不去重，把总数相加当分母不会像多渠道重叠那样造假缺口，
                # 但「抓全了没有」仍必须逐渠道判（CLAUDE.md「渠道总数之和当分母」立的规矩）。
                total_sum += channel_total or 0
                all_complete = all_complete and complete
                for row in channel_rows:
                    if isinstance(row, dict):
                        row["_job_type"] = job_type
                        row["_section"] = section
                        rows.append(row)

            open_rows = [r for r in rows if self._is_open(r, today)]
            cap = resolve_detail_cap(self._DETAIL_CAP)
            for row in open_rows[:cap] if cap else []:
                post_id = _clean(row.get("postId"))
                if not post_id:
                    continue
                try:
                    response = client.post(self.DETAIL_API, json={
                        "public": {"call_app": "F-TRM"},
                        "private": {"postId": post_id},
                    })
                    response.raise_for_status()
                    payload = response.json() or {}
                    detail = payload.get("data")
                    if str(payload.get("retCode")) == "0" and isinstance(detail, dict):
                        row["_depict"] = self._decode_depict(detail.get("postDepict"))
                except httpx.HTTPError:
                    continue
        if not rows:
            raise RuntimeError("icbc: qryPostList returned no jobs")
        # 分母用 len(open_rows) 而不是接口自报的 total_sum：官网把报名已截止的岗也列在列表里
        # （实测社招 63 条里 15 条已截止），拿它当分母会让 crawl_runs 上永远挂着
        # 「自报 2630、只入库 2615」这个**假缺口**——那 15 条是我们主动丢的，不是漏抓的。
        self.reported_total = len(open_rows)
        self.fetch_complete = all_complete
        return json.dumps({"jobs": open_rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            post_id = _clean(row.get("postId"))
            title = _clean(row.get("publishPostName") or row.get("postName"))
            if not (post_id and title):
                continue
            jd_url = self.DETAIL_URL.format(
                section=_clean(row.get("_section")) or "social", post_id=post_id)
            summary = (row.get("_depict") or "").strip() or None
            jobs.append(RawJob(
                company="", title=title,
                # placeStr 形如「中国-北京市」/「河南省-郑州市」，取后半段更像地点。
                location=_clean(row.get("placeStr")).split("-")[-1] or None,
                job_type=_clean(row.get("_job_type")) or None,
                summary=summary, jd_url=jd_url, apply_url=jd_url,
                posted_at=_clean(row.get("publishTime"))[:10] or None,
                deadline=_clean(row.get("enterEndTime"))[:10] or None,
            ))
        return jobs
