"""腾讯校园招聘（join.qq.com）适配器 —— 零登录、零浏览器。

⚠️ 腾讯的校招**不在** careers.tencent.com 上。那个站的 attrId=2 只有 16 个新加坡英文岗
（live 2026-09-03 实测），常规 2027 届秋招全部在独立域名 join.qq.com，共 869 岗。

## 接口
- 列表：`POST /api/v1/position/searchPosition`
  ⚠️ **必须先 GET 首页拿 cookie**，否则接口返回 `count=869` 却给 `positionList: []` ——
     很容易被误判成「被限流了」，其实只是缺会话。
  ⚠️ **列表在 `data.positionList`，不是 `data.list`**。读错字段同样会看到「有总数没数据」。
- 详情：`GET /api/v1/jobDetails/getJobDetailsByPidAndId?pid={projectId}&id={position}`
  返回 `data.desc`（岗位职责+要求全文）。

## 逐岗 jd_url
`https://join.qq.com/post_detail.html?pid={projectId}&id={position}`
- pid = 列表行的 `projectId`（1=应届毕业生项目），id = 列表行的 `position`（岗位序号）。
- ⚠️ 不要用 `postId` 拼 `jobdesc.html?postId=` —— 那是从 JS bundle 里挖到的旧模板，
  live 实测返回 `<title>404 | 腾讯校招</title>`。
- ⚠️ 也不要用列表行的 `id` 字段（那是另一个内部编号，`getPostIdByPidAndId` 用它查不到东西）。
- 用 pid+id 而非 postId 还有一个好处：同一岗位跨批次会换 postId，但 pid+id 稳定
  （live 对拍 5 条，4 条 postId 一致、第 5 条 postId 变了而标题正文不变）。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_detail_cap


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TencentCampusAdapter(BaseAdapter):
    name = "tencent_campus"
    company_name = "腾讯"

    HOME_URL = "https://join.qq.com/"
    LIST_URL = "https://join.qq.com/api/v1/position/searchPosition"
    DETAIL_API = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPidAndId"
    DETAIL_URL = "https://join.qq.com/post_detail.html?pid={pid}&id={pos}"
    PAGE_SIZE = 50
    MAX_PAGES = 40
    # 逐岗补正文；daily 快档由 env CRAWL_DETAIL_CAP=0 关掉，只抓列表骨架。
    DETAIL_CAP = 200

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": self.HOME_URL,
            "Origin": "https://join.qq.com",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        rows: List[dict] = []
        seen: set = set()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:
            # 建立会话：不带 cookie 时接口只回 count、不回列表（见文件头）。
            try:
                client.get(self.HOME_URL)
            except Exception:
                pass
            for page_no in range(1, self.MAX_PAGES + 1):
                # ⚠️ 分页参数是 **pageIndex**，不是 pageNum/page/pageNo —— 后三者一律被静默忽略、
                # 每页都返回同一批 50 条（live 逐个对拍过：只有 pageIndex 会让首条 position 从 783 变 191）。
                # 被忽略时接口照样 200 + count=869，不翻页自检就会只入库首页 50 条还以为成功了。
                response = client.post(self.LIST_URL, json={
                    "pageIndex": page_no, "pageSize": self.PAGE_SIZE,
                    "keyword": "", "workCity": "", "positionType": "", "recruitType": 0,
                })
                response.raise_for_status()
                data = (response.json() or {}).get("data") or {}
                if self.reported_total is None:
                    self.reported_total = _int_or_none(data.get("count"))
                page_rows = data.get("positionList") or []
                if not page_rows:
                    break
                for row in page_rows:
                    key = (row.get("projectId"), row.get("position"))
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(row)
                if self.reported_total is not None and len(rows) >= self.reported_total:
                    break
                if len(page_rows) < self.PAGE_SIZE:
                    break
            if not rows:
                raise RuntimeError("tencent_campus: empty position list (会话未建立或接口改版)")
            self._enrich_details(client, rows)
        self.fetch_complete = (
            self.reported_total is not None and len(rows) >= self.reported_total
        )
        return json.dumps({"positionList": rows}, ensure_ascii=False)

    def _enrich_details(self, client: httpx.Client, rows: List[dict]) -> None:
        """逐岗补正文。取不到就留空——列表已有标题/城市/BG，薄卡仍可入库，
        正文交给 enrich 链路补；一条失败绝不拖垮整源。"""
        cap = resolve_detail_cap(self.DETAIL_CAP)
        for row in rows[:cap]:
            pid, pos = row.get("projectId"), row.get("position")
            if pid is None or pos is None:
                continue
            try:
                resp = client.get(self.DETAIL_API, params={"pid": pid, "id": pos})
                detail = (resp.json() or {}).get("data") or {}
                if isinstance(detail, dict) and detail.get("desc"):
                    row["_desc"] = detail.get("desc")
            except Exception:
                continue

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("positionList") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            pid, pos = row.get("projectId"), row.get("position")
            title = str(row.get("positionTitle") or "").strip()
            if pid is None or pos is None or not title:
                continue
            # workCities 是空格分隔的多地点串（"深圳总部 北京 上海 …"）；取首个作主地点，
            # 全串留在 summary 里，避免丢掉「该岗多地可投」这个对校招用户重要的信息。
            cities = str(row.get("workCities") or "").strip()
            location = cities.split(" ")[0].strip() if cities else ""
            bits = []
            if cities:
                bits.append(f"工作地点：{cities}")
            bgs = str(row.get("bgs") or "").strip()
            if bgs:
                bits.append(f"所属 BG：{bgs}")
            if row.get("_desc"):
                bits.append(str(row["_desc"]).strip())
            summary = "\n\n".join(bits).strip() or None
            jd_url = self.DETAIL_URL.format(pid=pid, pos=pos)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                # projectName/recruitLabelName 即「应届毕业生」「实习生」，正是三桶分类要的信号。
                job_type=str(row.get("recruitLabelName") or row.get("projectName") or "").strip() or None,
                summary=summary,
                jd_url=jd_url,
                apply_url=jd_url,
            ))
        return jobs
