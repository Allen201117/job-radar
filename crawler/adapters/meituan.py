"""美团招聘公开岗位 API 适配器（零登录、零浏览器）。"""
import json
import re
import time
import uuid
from typing import List, Optional

import httpx

import normalizer
from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MeituanAdapter(BaseAdapter):
    name = "meituan"
    company_name = "美团"

    API_URL = "https://zhaopin.meituan.com/api/official/job/getJobList"
    DETAIL_URL = (
        "https://zhaopin.meituan.com/web/position/detail"
        "?jobUnionId={job_id}&highlightType=social"
    )
    PAGE_SIZE = 50
    # 官网社招实测 ~2830 岗；旧上限 20×50=1000 封顶只抓到 ~35%。提到 80×50=4000
    # 覆盖全量（分页按 page_rows<PAGE_SIZE 自然停，不会真跑满 80 页）。
    MAX_PAGES = 80

    # 板块过滤（子类 MeituanCampusAdapter 覆盖）。空 = 社招默认集。
    # ⚠️ jobType 是**对象数组** [{"code":"4","subCode":["1"]}]，不是字符串数组——
    # 传字符串（jobType:["1"]）服务端会静默忽略/返回 None，看起来像「校招没岗」。
    # 这个形状是 2026-08-04 在校招页装 XHR 拦截器截获真实请求才确定的，猜不出来。
    JOB_TYPE_FILTER: list = []
    TYPE_CODE_FILTER: list = []

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://zhaopin.meituan.com/web/position",
            "Origin": "https://zhaopin.meituan.com",
        }
        rows = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_no in range(1, self.MAX_PAGES + 1):
                payload = {
                    "page": {"pageNo": page_no, "pageSize": self.PAGE_SIZE},
                    "jobShareType": "1",
                    "keywords": "",
                    "cityList": [],
                    "department": [],
                    "jfJgList": [],
                    "jobType": self.JOB_TYPE_FILTER,
                    "typeCode": self.TYPE_CODE_FILTER,
                    "specialCode": [],
                    "u_query_id": uuid.uuid4().hex,
                    "r_query_id": f"{int(time.time() * 1000)}{page_no}",
                }
                response = client.post(self.API_URL, json=payload)
                response.raise_for_status()
                data = ((response.json() or {}).get("data") or {})
                if self.reported_total is None:
                    page = data.get("page") if isinstance(data.get("page"), dict) else {}
                    total = _int_or_none(page.get("totalCount"))
                    if total is None:
                        total = _int_or_none(data.get("total"))
                    if total is not None:
                        # Crawl coverage visibility: official reported total only, no pagination changes.
                        self.reported_total = total
                page_rows = data.get("list") or []
                if not page_rows:
                    break
                rows.extend(page_rows)
                if len(page_rows) < self.PAGE_SIZE:
                    break
        if not rows:
            raise RuntimeError("meituan: empty getJobList response")
        self.fetch_complete = (
            self.reported_total is not None and len(rows) >= self.reported_total
        )
        return json.dumps({"data": {"list": rows}}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = ((json.loads(html) or {}).get("data") or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs = []
        for row in rows:
            job_id = str(row.get("jobUnionId") or "").strip()
            title = str(row.get("name") or "").strip()
            city_names = [
                str(city.get("name") or "").strip()
                for city in (row.get("cityList") or [])
                if isinstance(city, dict)
                and is_china_company_location(str(city.get("name") or ""))
            ]
            if not (job_id and title and city_names):
                continue
            duty = str(row.get("jobDuty") or row.get("desc") or "").strip()
            requirement = str(row.get("jobRequirement") or "").strip()
            summary = (
                duty + ("\n\n【任职要求】\n" + requirement if requirement else "")
            ).strip() or None
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location="、".join(dict.fromkeys(city_names)),
                job_type=(
                    str(row.get("jobFamilyGroup") or row.get("jobFamily") or "").strip()
                    or None
                ),
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=normalizer.pick_publish_date(row),
            ))
        return jobs


class MeituanCampusAdapter(MeituanAdapter):
    """美团**校园招聘**板块。source_url 填 `https://zhaopin.meituan.com/web/campus`。

    与社招同一个 getJobList 接口、同一个域，只是多带板块过滤——但那个过滤的形状**猜不出来**：

    2026-08-04 探证过程（值得记住，是「猜 ≠ 验」的又一个样本）：
      · 先猜 `jobShareType` 1/2/3 是板块开关 → 三个值返回的**是同一批岗**（首条都是「HRBP（外派巴西）」），
        只有 totalCount 不同，纯属误导；
      · 再猜 `typeCode:["4"]` / `specialCode:["4"]` → total=0；猜 `jobType:["1"]`（字符串）→ total=None；
      · 最后在校招页装 XHR 拦截器截获真实请求，才看到 **jobType 是对象数组**：
        `{"jobType":[{"code":"4","subCode":["2"]}],"typeCode":["2"]}`。
      传字符串时服务端静默忽略、返回 None，表现得跟「校招没岗」一模一样——这正是只靠猜会得出
      「美团校招抓不到」错误结论的原因。

    校招枚举（GET api/official/job/search/enum?enumType=CAMPUS_HIRING）：
      父 code=4，子 code 1=应届生 / 2=转正实习 / 6=日常实习。
    live 实测：应届生 68 + 转正实习 104 + 日常实习 249 = 合并查询 total 421（一致）。
    详情页 `?jobUnionId={id}&highlightType=campus` 已 live 打开验证（渲染出岗位名 + 岗位职责全文）。
    """

    name = "meituan_campus"
    DETAIL_URL = (
        "https://zhaopin.meituan.com/web/position/detail"
        "?jobUnionId={job_id}&highlightType=campus"
    )
    # 三个子板块一次查全（合并查 total 与分开查之和一致，无需分三次）
    JOB_TYPE_FILTER = [{"code": "4", "subCode": ["1", "2", "6"]}]
    TYPE_CODE_FILTER = ["1", "2", "6"]

    # 行内 `jobType` 就是招聘类型（live 三桶对拍：应届生行=1 / 转正实习行=2 / 日常实习行=2；
    # 社招基线行=3）。用它填 job_type，而不是父类的 jobFamilyGroup——后者是**职能类别**
    # （"用户运营""运营类"），拿它当招聘类型会让 recruitmentCategory 把校招岗判成社招。
    _ROW_JOB_TYPE_LABEL = {"1": "校园招聘 应届生", "2": "实习"}

    def parse(self, html: str) -> List[RawJob]:
        """复用父类解析，仅把 job_type 换成招聘类型（父类填的是职能类别）。

        按 jd_url 里的 jobUnionId 把 RawJob 对回原始行——父类会丢掉无中国城市的行，
        位置下标对不齐，用 id 匹配才稳。
        """
        jobs = super().parse(html)
        try:
            rows = ((json.loads(html) or {}).get("data") or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return jobs
        by_id = {
            str(row["jobUnionId"]): row
            for row in rows
            if isinstance(row, dict) and row.get("jobUnionId")
        }
        for job in jobs:
            m = re.search(r"jobUnionId=(\d+)", job.jd_url or "")
            row = by_id.get(m.group(1)) if m else None
            if not row:
                continue
            label = self._ROW_JOB_TYPE_LABEL.get(str(row.get("jobType") or "").strip())
            if label:
                job.job_type = label
        return jobs
