"""联想校园招聘（talent.lenovo.com.cn）适配器 —— 零登录、零浏览器、零签名。

## 接口（2026-09-09 真 Chrome 实测 https://talent.lenovo.com.cn/position）
- 列表：`GET /gateway/jobBase/list?pageNum=N&pageSize=M`，同源、无签名、无鉴权。
  返回 `{code:0,message:"请求成功",result:{rows:[...],total:N}}`；`pageSize` 会被服务端遵守
  （live 试过 pageSize=50/100 均生效，不是被静默忽略的那类站）。
- 字典：`GET /gateway/sysDict/all`（页面加载时自己拉，用来把 workPlace / educationRequired /
  projectType 的字典码翻成中文）。`projectType`：1=应届生招聘，3=人才项目，2=实习生招聘
  （live 实测当前 90 条里只有 1/3 两种，2 现在没有在招——与页面描述「实习生项目已结束」一致）。
  `workPlace` 是逗号分隔的 `city_portal` 字典码（如 "6,1,5"），多城市取第一个作展示地点，
  全部城市写进 summary。`educationRequired` 是 `education` 字典码。
- 详情页 `https://talent.lenovo.com.cn/position/detail?id={id}` 冷加载能渲染出标题
  （live 验过 id=2339 →「数据开发工程师」）。SPA 路由，httpx 拿不到渲染后的正文，
  故 jd_url 只用于用户点击跳转，正文来自列表接口自带的 jobDuties/jobRequirement（HTML 全文）。
- `robots.txt` 返回的是 SPA 的 HTML 兜底页（200 text/html，不是真 robots 文件）→ 视为无限制；
  `should_skip` 对列表接口与 /position 页面的 HEAD 预检均实测 200，不会被跳过。

## 字典码人工誊抄（2026-09-09 从 /gateway/sysDict/all 摘录，只收列表中实际出现过的 city_portal 码；
   完整字典远大于此，缺的码走「未知城市」兜底，不阻断入库）
"""
import json
import logging
import re
from typing import Dict, List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_list_cap

logger = logging.getLogger(__name__)


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# city_portal 字典码 → 中文城市名（2026-09-09 live 摘自 /gateway/sysDict/all，含全部已登记城市）。
CITY_DICT: Dict[str, str] = {
    "1": "北京", "6": "天津", "5": "深圳", "2": "上海", "8": "武汉", "7": "成都",
    "22": "合肥", "23": "苏州", "13": "大连", "3": "广州", "16": "西安", "24": "南宁",
    "15": "郑州", "26": "长沙", "12": "杭州", "21": "兰州", "17": "沈阳", "30": "东京",
    "28": "乌鲁木齐", "9": "惠州", "11": "太原", "27": "昆山", "32": "无锡", "20": "南京",
    "10": "厦门", "31": "莫里斯维尔", "14": "重庆",
}

# education 字典码 → 中文学历（2026-09-09 live 摘自 /gateway/sysDict/all）。
EDUCATION_DICT: Dict[str, str] = {
    "1": "专科", "2": "本科", "3": "硕士研究生", "4": "MBA", "5": "博士研究生",
}

# projectType 字典码 → 我方招聘类型口径（2026-09-09 live：projectType 只出现 1/3，2 目前无在招岗）。
PROJECT_TYPE_DICT: Dict[int, str] = {
    1: "校招",
    2: "实习",
    3: "校招（人才项目）",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").replace("&nbsp;", " ").strip()


class LenovoAdapter(BaseAdapter):
    name = "lenovo"
    company_name = "联想 Lenovo"

    LIST_URL = "https://talent.lenovo.com.cn/gateway/jobBase/list"
    DETAIL_URL = "https://talent.lenovo.com.cn/position/detail?id={job_id}"
    PAGE_SIZE = 50
    _MAX_JOBS = 8000  # 只是个上限保险丝（live 实测联想总量 90），真正边界由 CRAWL_MAX_JOBS 调档

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        max_rows = resolve_list_cap(self._MAX_JOBS)
        max_pages = max(1, -(-max_rows // self.PAGE_SIZE))
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://talent.lenovo.com.cn/position",
            "Origin": "https://talent.lenovo.com.cn",
        }
        rows: List[dict] = []
        seen: set = set()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_no in range(1, max_pages + 1):
                try:
                    response = client.get(
                        self.LIST_URL,
                        params={"pageNum": page_no, "pageSize": self.PAGE_SIZE},
                    )
                    response.raise_for_status()
                    body = response.json() or {}
                    if body.get("code") != 0:
                        raise RuntimeError(f"lenovo: list error {body.get('message')}")
                    result = body.get("result") or {}
                except Exception:
                    if page_no == 1:
                        raise  # 首页失败交给 run.py 记录为 failed
                    logger.warning(
                        "lenovo: 第 %d 页抓取失败，保留已抓 %d 条（尽力而为）", page_no, len(rows)
                    )
                    break  # 后续页尽力而为，保留已抓的行；fetch_complete 由下方与 reported_total 比对天然置 False
                if self.reported_total is None:
                    self.reported_total = _int_or_none(result.get("total"))
                page_rows = result.get("rows") or []
                if not page_rows:
                    break
                gained = 0
                for row in page_rows:
                    job_id = str(row.get("id") or "").strip()
                    if not job_id or job_id in seen:
                        continue
                    seen.add(job_id)
                    rows.append(row)
                    gained += 1
                if self.reported_total is not None and len(rows) >= self.reported_total:
                    break
                # ⚠️ 不用「本页返回数 < PAGE_SIZE」判末页：与 hikvision 同款保险——万一站点某天
                # 忽略 pageSize，这条判据在真末页和翻页失效两种情况下都成立，不会误判提前收工。
                if not gained:
                    break
                if len(rows) >= max_rows:
                    break  # 撞本地上限 = 没抓全，下方与 reported_total 比对天然让 fetch_complete=False
        # HTTP 200 + 空 rows 但 total>0 是假阴性信号（CLAUDE.md「接口返 0/403 不能证明对方没开」
        # 同类坑），必须抛错记 failed，不许安静当成「零岗」入库或跳过。
        if not rows:
            reported = self.reported_total
            if reported and reported > 0:
                raise RuntimeError(
                    f"lenovo: empty rows but reported_total={reported} (被判定为假阴性，非真空)"
                )
            raise RuntimeError("lenovo: empty jobBase/list response")
        self.fetch_complete = (
            self.reported_total is not None and len(rows) >= self.reported_total
        )
        return json.dumps({"rows": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("rows") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("jobName") or "").strip()
            if not (job_id and title):
                continue

            city_codes = [c.strip() for c in str(row.get("workPlace") or "").split(",") if c.strip()]
            cities = [CITY_DICT.get(code, code) for code in city_codes]
            cities = list(dict.fromkeys(c for c in cities if c))
            location = cities[0] if cities else ""

            project_type = _int_or_none(row.get("projectType"))
            job_type = PROJECT_TYPE_DICT.get(project_type) or str(row.get("typeName") or "").strip() or None

            edu_code = str(row.get("educationRequired") or "").strip()
            education = EDUCATION_DICT.get(edu_code) or None

            bits = []
            type_name = str(row.get("typeName") or "").strip()
            if type_name:
                bits.append(f"职能分类：{type_name}")
            if len(cities) > 1:
                bits.append(f"招聘城市：{'、'.join(cities)}")
            duties = _strip_html(row.get("jobDuties") or "")
            if duties:
                bits.append(f"【岗位职责】\n{duties}")
            requirement = _strip_html(row.get("jobRequirement") or "")
            if requirement:
                bits.append(f"【任职要求】\n{requirement}")
            summary = "\n\n".join(bits).strip() or None

            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type=job_type,
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                education=education,
            ))
        return jobs
