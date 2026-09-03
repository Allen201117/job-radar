"""海康威视校园招聘（campushr.hikvision.com）适配器 —— 零登录、零浏览器。

海康的校招在**独立域名** campushr.hikvision.com 上，与社招 talent.hikvision.com 完全分开
（后者被 EdgeOne 拦，抓不到；校招这个域名的列表接口是公开的，无需任何 token/cookie）。

## 接口
- 列表：`POST /api/search/crsPositionSearch/getPositionByQuery`，body `{"pageNum":N,"pageSize":M}`
  返回 `data.total` + `data.list`；标题字段是 **postAdName**（不是 positionName）。
- 数据自证是校招：live 实测 257 条的 `jobNature` 只有「校招应届生」「校招实习生」，
  `batchName` 只有「【2027校园招聘】」「【2027超新星实习生招聘】」——不含任何社招岗。

## 逐岗 jd_url
`https://campushr.hikvision.com/JobDetails.html?id={id}&type=2&batchId={batchId}`
⚠️ 这个 URL 是**拦截列表页的 window.open 抓到的**，不是猜的。
   海康列表页点击岗位走 `window.open`，当前页 location 纹丝不动 ——
   如果按「点击后 URL 没变」判断，会错误地得出「该站没有逐岗详情页」的结论（我犯过）。
⚠️ hash 路由 `#/position/list/detail/{id}` 是无效的，会被重定向回首页。
live 验证：该 URL 渲染出「【2027校园招聘】AI加速算法工程师」+ 工作性质/职位描述/职位要求全文。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class HikvisionAdapter(BaseAdapter):
    name = "hikvision"
    company_name = "海康威视"

    LIST_URL = "https://campushr.hikvision.com/api/search/crsPositionSearch/getPositionByQuery"
    DETAIL_URL = "https://campushr.hikvision.com/JobDetails.html?id={job_id}&type=2&batchId={batch_id}"
    PAGE_SIZE = 50
    MAX_PAGES = 30

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://campushr.hikvision.com/school",
            "Origin": "https://campushr.hikvision.com",
        }
        rows: List[dict] = []
        seen: set = set()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for page_no in range(1, self.MAX_PAGES + 1):
                # ⚠️ 分页参数走 **URL query**，放进 JSON body 会被静默忽略、每页恒返首批 10 条
                # （live 逐个试过：body 里的 pageNum/pageIndex/current/start 全无效，
                #  只有 ?pageNum=&pageSize= 能让首条从「AI加速算法工程师」变成「工业设计师」）。
                response = client.post(
                    self.LIST_URL,
                    params={"pageNum": page_no, "pageSize": self.PAGE_SIZE},
                    json={},
                )
                response.raise_for_status()
                data = (response.json() or {}).get("data") or {}
                if self.reported_total is None:
                    self.reported_total = _int_or_none(data.get("total"))
                page_rows = data.get("list") or data.get("records") or []
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
                # ⚠️ 不用「本页返回数 < PAGE_SIZE」判末页：站点忽略 pageSize 时每页恒 10 条，
                # 那个判据会在第一页就误判收工（我第一版就是这么只抓到 10/257 的）。
                # 改用「这一页没带来任何新 id」——对翻页失效和真末页都成立。
                if not gained:
                    break
        if not rows:
            raise RuntimeError("hikvision: empty position list")
        self.fetch_complete = (
            self.reported_total is not None and len(rows) >= self.reported_total
        )
        return json.dumps({"list": rows}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("list") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            job_id = str(row.get("id") or "").strip()
            title = str(row.get("postAdName") or row.get("positionName") or "").strip()
            batch_id = str(row.get("batchId") or "").strip()
            # batchId 是详情页必需参数，缺了链接打不开 —— 拿不到就整条跳过，不入库半截链接。
            if not (job_id and title and batch_id):
                continue
            bits = []
            batch = str(row.get("batchName") or "").strip()
            if batch:
                bits.append(f"招聘批次：{batch}")
            dept = str(row.get("adNeedDept") or "").strip()
            if dept:
                bits.append(f"需求部门：{dept}")
            for key, label in (("postDuty", "岗位职责"), ("postRequire", "任职要求"),
                               ("jobDesc", "职位描述"), ("jobRequirement", "职位要求")):
                val = str(row.get(key) or "").strip()
                if val:
                    bits.append(f"【{label}】\n{val}")
            summary = "\n\n".join(bits).strip() or None
            jd_url = self.DETAIL_URL.format(job_id=job_id, batch_id=batch_id)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=str(row.get("workPlace") or "").strip(),
                # jobNature 就是「校招应届生」/「校招实习生」，正是三桶分类要的强信号。
                job_type=str(row.get("jobNature") or "").strip() or None,
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
            ))
        return jobs
