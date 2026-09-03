"""阿里巴巴**校招主站**（campus-talent.alibaba.com）适配器 —— 零登录、零浏览器。

⚠️ 与已有的 `alibaba_campus` 不是一回事，两个都要留：
- `alibaba_campus`（adapters/alibaba.py）抓的是**各 BU 自己的** `{bu}.com/campus/position-list`
  （高德 45 / 淘天 34 / 控股 10…），它们抓全了，但那是各 BU 的零散口子；
- 本文件抓的是**集团统一校招主站**，2026-09-04 live 实测 1,075 岗
  （2027届应届生 479 + 日常实习生 347 + 研究型实习生 249）。

2026-09-03 曾判本站「login_wall（匿名 POST 返回 403）」——**结论是错的**。它要的不是登录，
是 CSRF：先 GET 任意页面拿 `XSRF-TOKEN` cookie，再把该值当 query 参数 `?_csrf=` 带上即可。
不带、或随便塞一个 uuid，都返回 403（三种都实测过）。

## 接口
- 批次清单：`POST /searchCondition/listBatch?_csrf={token}` body `{"language":"zh","channel":"campus_group_official_site"}`
  → `content.{graduate,internship,topTalentPlan}[]`，每项含 `id`(batchId) + `name`。
  **这就是站点自己声明的「当前开着哪些项目」**，所以本 adapter 不需要像网易那样从项目名里
  解析届次去猜——批次清单里没有的就是没开。
  ⚠️ `topTalentPlan`（阿里星）的 id 与 graduate **相同**（都是 100000760001），按 id 去重，
     否则同一批岗会被抓两遍。
- 岗位列表：`POST /position/search?_csrf={token}`
  body `{"batchId":…,"pageIndex":1,"pageSize":100,"customDeptCode":"","channel":"campus_group_official_site","language":"zh"}`
  → `content.totalCount` + `content.datas[]`，行里**直接带** `description`(职位描述) +
    `requirement`(任职要求)，不用逐岗富化。
  ⚠️ 翻页参数是 `pageIndex`（1-based）。已按「第 2 页首条标题变了没」自检过确实生效
     （page1=AI应用算法工程师 / page2=云基础设施规划与交付数据工程师）。
  ⚠️ `pageSize=100` 实测生效（返回 100 条），不像有些站点会静默钳到 10。

## 逐岗 jd_url
`https://campus-talent.alibaba.com/campus/position/{id}`
- 路由取自站点 JS bundle 里的路由表（`/campus/position/`），**并 live 核过**：
  id=199907740040 打开渲染的正是「AI应用算法工程师」，含毕业时间要求与完整职位描述。
- ⚠️ 列表行里的 `positionUrl` 恒为 null，别指望它。

## 公司名
恒为「阿里巴巴」。行里的 `circleNames` 是**这个岗可投的 BU 列表**（一个岗常挂 13 个 BU），
不是岗位归属，绝不能拿它派生 company —— 那会把同一个岗拆成十几家公司。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob
from .china_location import is_china_company_location


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AlibabaCampusPortalAdapter(BaseAdapter):
    name = "alibaba_campus_portal"
    company_name = "阿里巴巴"
    official_hosts = ("campus-talent.alibaba.com",)

    ORIGIN = "https://campus-talent.alibaba.com"
    HOME_URL = ORIGIN + "/campus/position"
    BATCH_URL = ORIGIN + "/searchCondition/listBatch"
    LIST_URL = ORIGIN + "/position/search"
    DETAIL_URL = ORIGIN + "/campus/position/{job_id}"
    CHANNEL = "campus_group_official_site"

    PAGE_SIZE = 100
    MAX_PAGES = 60

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": self.HOME_URL,
            "Origin": self.ORIGIN,
        }

    @staticmethod
    def batch_ids(payload) -> List[int]:
        """从 listBatch 响应里取批次 id，**按 id 去重且保序**。
        去重不是洁癖：阿里星与应届生共用 100000760001，不去重整批岗会被抓两遍。"""
        content = (payload or {}).get("content") or {}
        ids: List[int] = []
        seen = set()
        for group in ("graduate", "internship", "topTalentPlan"):
            for item in content.get(group) or []:
                batch_id = _int_or_none((item or {}).get("id"))
                if batch_id is not None and batch_id not in seen:
                    seen.add(batch_id)
                    ids.append(batch_id)
        return ids

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        rows: List[dict] = []
        seen: set = set()
        batch_totals: List[int] = []
        batches_drained: List[bool] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:
            # 建立 CSRF 会话：token 在 cookie XSRF-TOKEN 里，随后每个 POST 用 ?_csrf= 带上。
            client.get(self.HOME_URL)
            token = client.cookies.get("XSRF-TOKEN")
            if not token:
                raise RuntimeError("alibaba_campus_portal: 拿不到 XSRF-TOKEN cookie（站点改版或被拦）")
            params = {"_csrf": token}

            batches = self.batch_ids(client.post(
                self.BATCH_URL, params=params,
                json={"language": "zh", "channel": self.CHANNEL}).json())
            if not batches:
                raise RuntimeError("alibaba_campus_portal: listBatch 没返回任何批次（当前无在招项目？）")

            for batch_id in batches:
                total, got = None, 0
                for page in range(1, self.MAX_PAGES + 1):
                    try:
                        payload = client.post(self.LIST_URL, params=params, json={
                            "batchId": batch_id, "pageIndex": page, "pageSize": self.PAGE_SIZE,
                            "customDeptCode": "", "channel": self.CHANNEL, "language": "zh",
                        }).json()
                    except (httpx.HTTPError, ValueError):
                        break
                    if not payload.get("success"):
                        break
                    content = payload.get("content") or {}
                    if total is None:
                        total = _int_or_none(content.get("totalCount"))
                    page_rows = content.get("datas") or []
                    if not page_rows:
                        break
                    fresh = 0
                    for row in page_rows:
                        key = str(row.get("id") or "")
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        rows.append(row)
                        fresh += 1
                    got += len(page_rows)
                    if total is not None and got >= total:
                        break
                    # 末页判据看「这一页有没有带来新岗」，不看页长——短页不该收工。
                    if not fresh:
                        break
                if total is not None:
                    batch_totals.append(total)
                    batches_drained.append(got >= total)
                else:
                    batches_drained.append(False)
        if not rows:
            raise RuntimeError("alibaba_campus_portal: 批次都取到了但一个岗都没有")
        if len(batch_totals) == len(batches_drained):
            self.reported_total = sum(batch_totals)
        self.fetch_complete = bool(batches_drained) and all(batches_drained)
        return json.dumps({"datas": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("datas") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("name") or "").strip()
            if not job_id or not title:
                continue
            # status 只放行在招的；接口偶尔会带上已停止投递的历史岗。
            if str(row.get("status") or "").strip().lower() not in ("", "recruit"):
                continue
            places = [str(x).strip() for x in (row.get("workLocations") or []) if str(x).strip()]
            location = places[0] if places else ""
            if location and not is_china_company_location(location):
                continue
            bits = []
            if places:
                bits.append("工作地点：" + " / ".join(places))
            batch_name = str(row.get("batchName") or "").strip()
            if batch_name:
                bits.append("招聘项目：" + batch_name)
            desc = str(row.get("description") or "").strip()
            req = str(row.get("requirement") or "").strip()
            if desc:
                bits.append("职位描述：" + desc)
            if req:
                bits.append("任职要求：" + req)
            jd_url = self.DETAIL_URL.format(job_id=job_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location or None,
                job_type=str(row.get("categoryName") or "").strip() or None,
                summary="\n".join(bits).strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
            ))
        return jobs
