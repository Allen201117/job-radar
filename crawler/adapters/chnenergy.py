"""国家能源投资集团自建招聘门户（zhaopin.chnenergy.com.cn），纯 httpx 零鉴权。

2026-09-05 live 核实：这家**有稳定的逐岗详情页**，不是「只发公告」——
详情 ``/annc/showgw?id={uuid}`` 匿名可开，返回岗位名 / 招聘单位 / 工作地点 / 岗位职责 /
岗位要求 / 报名截止日期（~1750 字正文），与列表标题逐字一致。
（此前一度被当成公告制收进 apply_programs，迁移 232 已撤下。）

公开链路：
1. 列表 ``POST /recTypeSerch``（form）：``pagenum`` **0-based**、固定 10 条/页；
   ``kinds`` = 招聘大类，``schType`` = 校招子渠道。翻页函数 ``gopage(n)`` 就是改 pagenum 提交。
2. 详情 ``GET /annc/showgw?id={uuid}``。

⚠️ ``showgw`` 是**岗位**，``showgg`` 是**公告**，一字之差别写错。
⚠️ 岗位 id 是 Oracle 式 GUID，**前 8 位是共享前缀**（5a798bfe-…）。去重、日志比对、单测断言
   一律用全串——按前 8 位截断会得出「每页首个岗位都一样」的假结论（2026-09-05 实测踩过）。
⚠️ ``kinds=2``（内部招聘）刻意不抓：那是在职员工内部竞聘，不对外。
⚠️ 完整性**逐渠道**判，不能拿「去重后条数」比「各渠道 total 之和」——渠道间可能重叠，
   那样算 fetch_complete 会恒 False（CLAUDE.md 为华为/小红书立过碑）。
⚠️ ``RawJob.company`` 刻意留空以继承 sources.company（「国家能源集团」）：列表里的招聘单位是
   「中国神华煤制油化工有限公司…」这类子公司，名字里没有「国家能源」，写进 company 会让这些岗
   掉出必投清单 ``%国家能源%`` 的统计口径。子公司名改放进 summary 抬头，信息不丢。
"""
import json
import re
from typing import List, Optional

import httpx
from selectolax.parser import HTMLParser

from .base import (BaseAdapter, PageResult, RawJob, paginate_all,
                   resolve_detail_cap, resolve_list_cap)

_BASE = "https://zhaopin.chnenergy.com.cn"
_LIST = f"{_BASE}/recTypeSerch"
_DETAIL = f"{_BASE}/annc/showgw?id={{id}}"
_PAGE_SIZE = 10          # 站点固定 10 条/页，表单里没有 pageSize 字段
_MAX_JOBS = 8000

# (kinds, schType, 渠道名, job_type)；kinds=1 校招、kinds=3 社招，kinds=2 内部招聘不抓。
_CHANNELS = (
    ("1", "18", "campus_elite", "校招"),
    ("1", "1", "campus_direct", "校招"),
    ("1", "2", "campus_unified", "校招"),
    ("1", "19", "campus_tibet_qinghai_xinjiang", "校招"),
    ("1", "7", "campus_rural", "校招"),
    ("3", "", "social", "社招"),
)

_JOB_ID_RE = re.compile(r"/annc/showgw\?id=([0-9a-fA-F\-]{36})")
_TOTAL_RE = re.compile(r"共\s*<b[^>]*>\s*(\d+)\s*</b>\s*条记录")
_TOTAL_PAGES_RE = re.compile(r"共\s*<b[^>]*>\s*(\d+)\s*</b>\s*页")
# 详情页判死：不存在/撤岗的 id 返回 200 + 738 字节错误壳（live 标定，见 enrich._detail_chnenergy）
_GONE_TEXT = "查看岗位信息发生错误"


def _text(node) -> str:
    return re.sub(r"\s+", " ", (node.text() if node is not None else "")).strip()


class ChnenergyAdapter(BaseAdapter):
    name = "chnenergy"
    _DETAIL_CAP = 200      # 逐岗补正文上限；快档 CRAWL_DETAIL_CAP=0 时只抓列表

    def should_skip(self, source_url: str):
        return None        # 列表是 POST，HEAD 预检没有意义

    # ── fetch ────────────────────────────────────────────────────────────────
    def _fetch_channel(self, client: httpx.Client, kinds: str, sch: str, max_rows: int):
        """翻完一个渠道，返回 (rows, reported_total, drained)。"""
        def fetch_page(page_index: int) -> PageResult:
            form = {
                "pagenum": str(page_index), "kinds": kinds, "schType": sch,
                "unitCode": "", "ebDownAll": "", "transAreaCode": "", "workPlaceCode": "",
                "searchtype": "job", "workUnit": "", "station": "",
                "publishDate": "", "enddate": "", "stationkind": "", "ebDown": "",
            }
            response = client.post(_LIST, data=form)
            response.raise_for_status()
            html = response.text
            total = _TOTAL_RE.search(html)
            pages = _TOTAL_PAGES_RE.search(html)
            return PageResult(
                items=_parse_list_items(html),
                total=int(total.group(1)) if total else None,
                total_pages=int(pages.group(1)) if pages else None,
            )

        max_pages = max(1, -(-max_rows // _PAGE_SIZE))
        rows, total, complete = paginate_all(
            fetch_page, page_size=_PAGE_SIZE, first_page=0, max_pages=max_pages,
            delay_seconds=0.15, label=f"chnenergy:kinds={kinds},schType={sch or '-'}")
        if len(rows) >= max_rows:
            complete = False   # 撞本地上限 = 没抓全（绝不能让 list-absence 据此撤岗）
        return rows, total, complete

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        max_rows = resolve_list_cap(_MAX_JOBS)
        headers = {"User-Agent": self.user_agent,
                   "Accept": "text/html,application/xhtml+xml,*/*",
                   "Origin": _BASE, "Referer": f"{_BASE}/index1"}

        seen, out, totals, drained = set(), [], [], []
        with httpx.Client(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
            for kinds, sch, channel, job_type in _CHANNELS:
                remaining = max_rows - len(out)
                if remaining <= 0:
                    drained.append(False)
                    continue
                try:
                    rows, total, complete = self._fetch_channel(client, kinds, sch, remaining)
                except Exception as exc:                      # noqa: BLE001
                    print(f"[chnenergy] 渠道 {channel} 抓取失败：{exc}")
                    drained.append(False)                     # 渠道没抓成 → 整源不算抓全
                    continue
                if total is None:
                    drained.append(False)                     # 连总数都没拿到 → 本渠道不算抓全
                else:
                    totals.append(total)
                    drained.append(complete and len(rows) >= total)
                for row in rows:
                    if row["id"] in seen:
                        continue                              # 渠道间可能重叠，按全串 uuid 去重
                    seen.add(row["id"])
                    row["_channel"], row["_job_type"] = channel, job_type
                    out.append(row)

            if len(totals) == len(_CHANNELS):
                self.reported_total = sum(totals)
            # ⚠️ 逐渠道判，不拿去重后条数比 total 之和（渠道重叠会让它恒 False）。
            self.fetch_complete = len(drained) == len(_CHANNELS) and all(drained)
            self._enrich_details(client, out)

        print(f"[chnenergy] channels={len(_CHANNELS)} jobs={len(out)} "
              f"reported_total={self.reported_total} complete={self.fetch_complete}")
        return json.dumps({"jobs": out}, ensure_ascii=False)

    def _enrich_details(self, client: httpx.Client, rows: List[dict]) -> int:
        """逐岗补正文，受 CRAWL_DETAIL_CAP 控制（快档设 0 = 只抓列表，正文交 enrich-backlog）。"""
        cap = resolve_detail_cap(self._DETAIL_CAP)
        if cap <= 0:
            return 0
        done = 0
        for row in rows:
            if done >= cap:
                break
            try:
                response = client.get(_DETAIL.format(id=row["id"]))
                response.raise_for_status()
            except Exception:                                  # noqa: BLE001
                continue
            body = _parse_detail(response.text)
            if body:
                row["summary"] = body
                done += 1
        return done

    # ── parse ────────────────────────────────────────────────────────────────
    def parse(self, payload: str) -> List[RawJob]:
        try:
            data = json.loads(payload) or {}
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("jobs")
        if rows is None:
            rows = _parse_list_items(payload)   # 允许单测直接喂列表页 HTML
        out = []
        for row in rows or []:
            job_id = str((row or {}).get("id") or "").strip()
            title = str((row or {}).get("title") or "").strip()
            if not (job_id and title):
                continue
            unit = str(row.get("unit") or "").strip()
            summary = str(row.get("summary") or "").strip()
            if unit and not summary.startswith(unit):
                # 招聘单位不写进 company（会掉出 %国家能源% 口径），放正文抬头保住信息。
                head = f"招聘单位：{unit}"
                major = str(row.get("major") or "").strip()
                if major:
                    head += f"\n专业要求：{major}"
                summary = f"{head}\n\n{summary}" if summary else head
            out.append(RawJob(
                company="",                                   # 继承 sources.company（见模块 docstring）
                title=title,
                location=str(row.get("location") or "").strip() or None,
                job_type=str(row.get("_job_type") or "").strip() or None,
                summary=summary or None,
                jd_url=_DETAIL.format(id=job_id),
                education=str(row.get("education") or "").strip() or None,
                deadline=str(row.get("deadline") or "").strip() or None,
            ))
        return out


def _attr_or_text(node) -> str:
    """优先取 ``title`` 属性：列表把学历/专业/单位截断成「全日制硕士...」显示，全文只在 title 里。"""
    if node is None:
        return ""
    return ((node.attributes.get("title") or "").strip() or _text(node))


def _parse_list_items(html: str) -> List[dict]:
    """从列表页 HTML 抽岗位行。

    ⚠️ 每张卡都带一份**注释掉的**同构 <a>（id 与正文相同），按卡片切分后取第一个 showgw id 即可。
    ⚠️ 卡片里有两个 ``ul.list-inline``：第一个是「学历 | 专业」，第二个是「工作地点、招聘人数」。
       必须分开取——拍平成一个列表后，专业缺失的卡片会让下标整体前移，把专业当成工作地点。
    """
    out, seen = [], set()
    for chunk in html.split('<li class="list-group-item">')[1:]:
        match = _JOB_ID_RE.search(chunk)
        if not match:
            continue
        job_id = match.group(1)
        if job_id in seen:
            continue
        seen.add(job_id)
        tree = HTMLParser(chunk)
        lists = tree.css("ul.list-inline")
        def cells(index):
            if index >= len(lists):
                return []
            return [x for x in (_attr_or_text(n) for n in lists[index].css("li")) if x and x != "|"]
        spec, facts = cells(0), cells(1)
        deadline = re.search(r"报名截止日期：\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", chunk)
        out.append({
            "id": job_id,
            "title": _attr_or_text(tree.css_first("h3 a")),
            "education": spec[0] if spec else "",
            "major": spec[1] if len(spec) > 1 else "",
            "unit": _attr_or_text(tree.css_first("h5")),
            "location": next((x for x in facts if "招聘人数" not in x), ""),
            "deadline": deadline.group(1) if deadline else "",
        })
    return out


def _parse_detail(html: str) -> Optional[str]:
    """详情页正文：岗位职责 + 岗位要求。不存在/撤岗的 id 返回错误壳，这里返回 None。"""
    if _GONE_TEXT in html and "招聘岗位" not in html:
        return None
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", HTMLParser(text).text()).strip()
    match = re.search(r"岗位职责(.*)", text, re.S)
    # 页面尾部固定挂着版权行，截掉；与 enrich._detail_chnenergy 同口径。
    body = (match.group(1) if match else "").split("国家能源投资集团有限责任公司")[0].strip()
    return body or None
