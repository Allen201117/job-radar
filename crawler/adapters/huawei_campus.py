"""华为校园招聘（career.huawei.com 新站）适配器 —— 零登录、零浏览器。

⚠️ 华为校招**不在**我们原有的 `reccampportal` 那套接口上。`huawei.py` 打的是老门户
`career.huawei.com/reccampportal/.../getJob/newHr`，传 `jobType=2`（该门户的「校招」）
live 实测 `totalRows=0`，于是长期被判成「华为没开校招」。**这个结论是错的**：
华为官网 2026-08-15 就挂着「华为2027届应届生招聘启动」，招聘对象写得清清楚楚
（2027 年 1-12 月毕业的国内本硕 + 2026-2027 毕业的博士与海外本硕博）。
校招搬到了新站 `career.huawei.com/cn/campus-recruitment`，走另一个网关。
——正是 CLAUDE.md「接口返 0 不能证明对方没开」那条碑说的情形，判据只能是对方页面自己怎么说。

## 接口（2026-09-04 live 探明，纯 httpx 可达）
- 列表：`POST {GATEWAY}/recruitmentPosition/pub/getJobPage?X-HW-ID={APP_ID}`
  body `{"curPage":1,"pageSize":50,"jobType":"CR","recruitmentType":["FRESH_GRADUATE"]}`
  总数在 `data.pageVO.totalRows`，行在 `data.result`。
  `recruitmentType`：`FRESH_GRADUATE`=应届生(69) / `INTERN`=实习生(31)。
  ⚠️ **必须带那一组 `x-*` 请求头**（x-hw-id / x-jalor-tenantalias / x-language / x-alb-gray /
     x-referer）。少了它们接口照样返 **HTTP 200**，但 body 里 `data` 为空 ——
     又是一个「200 + 空数据」的假阴性，别据此判定「华为没开」。
- 正文：`POST {GATEWAY}/recruitmentPosition/pub/getPositionIntentionList` body `{"jobId":…}`
  华为校招岗是「伞形岗位」：列表和详情接口的 mainBusiness/jobRequire 都只有一句占位
  「请您详见岗位意向中的岗位职责」，真正的职责/要求按**岗位意向（方向）**分开放在这个接口里
  （AI Infra工程师 有 4 个方向，每个方向 300+ 字）。不取它就是一张薄卡、不算「有效在招」。

## 逐岗 jd_url
`https://career.huawei.com/cn/job-details?advertisementId={advertisementId}`
- 用列表行的 **advertisementId**（36384），不是 `advertisementsIntegrationId`（219744）也不是
  `jobId`（103891）。这三个字段同时存在且值都不一样，取错就是坏链。
- 探法是拦 `window.open`：点卡片时当前页 URL 纹丝不动（新标签页打开），
  只看 `location.href` 会得出「没有逐岗详情页」的错误结论。
- ⚠️ **一个 advertisementId 一条岗**，不要按「岗位意向」拆成多条：所有方向共用同一个
  详情页 URL，拆开会撞 canonical_jd_url 的 active 唯一索引、互相覆盖。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_detail_cap

_GATEWAY = "https://apigw-dgg-b0.huawei.com/api/apig/channelhw"
_APP_ID = "app_000000035886"
# recruitmentType → 三桶分类要的招聘类型标签（喂给 normalizer，不自己判）
_SCENARIOS = (("FRESH_GRADUATE", "校园招聘"), ("INTERN", "实习生"))


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(text) -> str:
    """接口正文里的换行是字面量 `<br>`，转成真换行，顺手压掉首尾空白。"""
    return str(text or "").replace("<br>", "\n").replace("<BR>", "\n").strip()


class HuaweiCampusAdapter(BaseAdapter):
    name = "huawei_campus"
    company_name = "华为"
    official_hosts = ("career.huawei.com", "apigw-dgg-b0.huawei.com")

    LIST_API = f"{_GATEWAY}/recruitmentPosition/pub/getJobPage?X-HW-ID={_APP_ID}"
    INTENTION_API = f"{_GATEWAY}/recruitmentPosition/pub/getPositionIntentionList?X-HW-ID={_APP_ID}"
    DETAIL_URL = "https://career.huawei.com/cn/job-details?advertisementId={adv}"
    PAGE_SIZE = 50
    MAX_PAGES = 40
    # 逐岗补正文（伞形岗位的方向说明）。daily 快档由 env CRAWL_DETAIL_CAP=0 关掉只抓骨架。
    DETAIL_CAP = 200
    # 单个岗位最多拼几个方向的正文——AI Infra 有 4 个方向、单个 300+ 字，全拼进去会过长。
    MAX_INTENTIONS = 6

    def should_skip(self, source_url: str) -> Optional[str]:
        return None  # 公开 JSON 网关，跳过 HEAD 预检（HEAD 对该网关无意义）

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN",
            "Content-Type": "application/json",
            "Referer": "https://career.huawei.com/",
            # ↓ 这五个头缺一不可，见文件头注释（缺了返 200 但 data 为空）
            "x-alb-gray": "prod",
            "x-hw-id": _APP_ID,
            "x-jalor-tenantalias": "hcm",
            "x-language": "zh_CN",
            "x-referer": "https://career.huawei.com/cn",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        rows: List[dict] = []
        seen: set = set()
        totals: List[int] = []
        drained: List[bool] = []   # 完整性逐渠道判，见下方 fetch_complete
        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers=self._headers()) as client:
            for scenario, label in _SCENARIOS:
                total: Optional[int] = None
                got = 0
                for page_no in range(1, self.MAX_PAGES + 1):
                    try:
                        resp = client.post(self.LIST_API, json={
                            "curPage": page_no, "pageSize": self.PAGE_SIZE,
                            "jobType": "CR", "recruitmentType": [scenario],
                        })
                        resp.raise_for_status()
                        payload = resp.json()
                    except (httpx.HTTPError, ValueError):
                        break
                    data = (payload or {}).get("data") or {}
                    if total is None:
                        total = _int_or_none((data.get("pageVO") or {}).get("totalRows"))
                    page_rows = data.get("result") or []
                    if not page_rows:
                        break
                    for row in page_rows:
                        adv = row.get("advertisementId")
                        if adv is None or adv in seen:
                            continue
                        seen.add(adv)
                        row["_scenario"] = label
                        rows.append(row)
                    got += len(page_rows)
                    if total is not None and got >= total:
                        break
                    if len(page_rows) < self.PAGE_SIZE:
                        break
                if total is not None:
                    totals.append(total)
                    drained.append(got >= total)
                else:
                    drained.append(False)   # 连总数都没拿到 → 本渠道不算抓全
            if not rows:
                raise RuntimeError(
                    "huawei_campus: empty getJobPage —— 多半是 x-* 请求头缺失（返 200 但 data 空）"
                    "或网关改版，不要据此判定华为没开校招")
            self._enrich_intentions(client, rows)
        if len(totals) == len(_SCENARIOS):
            self.reported_total = sum(totals)
        # 逐渠道判抓全（与 huawei/xiaohongshu 同口径）：两个场景各自都抓到自报总数才算抓全。
        self.fetch_complete = len(drained) == len(_SCENARIOS) and all(drained)
        return json.dumps({"result": rows}, ensure_ascii=False)

    def _enrich_intentions(self, client: httpx.Client, rows: List[dict]) -> None:
        """按 jobId 取「岗位意向」补正文。取不到就留空——薄卡仍可入库，
        正文交给 enrich 链路补；一条失败绝不拖垮整源。"""
        cap = resolve_detail_cap(self.DETAIL_CAP)
        for row in rows[:cap]:
            job_id = row.get("jobId")
            if job_id is None:
                continue
            try:
                resp = client.post(self.INTENTION_API, json={"jobId": job_id})
                items = (resp.json() or {}).get("data") or []
            except (httpx.HTTPError, ValueError):
                continue
            if not isinstance(items, list):
                continue
            blocks = []
            places = ""
            for item in items:
                if isinstance(item, dict) and item.get("jobPlaceName"):
                    places = str(item["jobPlaceName"]).strip()
                    break
            if places:
                row["_places"] = places
            for item in items[:self.MAX_INTENTIONS]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("positionIntention") or "").strip()
                duty = _clean(item.get("jobResponsibilities"))
                need = _clean(item.get("jobDemand"))
                if not (duty or need):
                    continue
                parts = [f"【方向】{name}" if name else "【方向】"]
                if duty:
                    parts.append(f"岗位职责：\n{duty}")
                if need:
                    parts.append(f"岗位要求：\n{need}")
                blocks.append("\n".join(parts))
            if blocks:
                row["_intentions"] = "\n\n".join(blocks)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("result") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            adv = row.get("advertisementId")
            title = str(row.get("jobName") or row.get("externalJobName") or "").strip()
            if adv is None or not title:
                continue
            # ⚠️ 地点只能取列表自带的 **jobAddress**（`China\\Guangdong-Shenzhen,…` 逗号分隔）。
            # 中文的 jobCity/jobArea 只在**详情**接口里有，列表行恒为 None；靠它取地点的话，
            # daily 快档（CRAWL_DETAIL_CAP=0 不逐岗富化）会把这 100 个岗全部写成无地点，
            # 城市筛选一个都命中不了。normalizer 认得这个格式（实测 → 「深圳」）。
            # 中文城市串（意向接口的 jobPlaceName）拿到就用，只用于 summary 展示。
            addresses = [x.strip() for x in str(row.get("jobAddress") or "").split(",") if x.strip()]
            location = addresses[0] if addresses else ""
            # summary 里的「多地可投」展示串**只用意向接口给的中文城市名**。快档（不富化）拿不到它时
            # 宁可不写这一行：clean_location 的城市别名表只覆盖主要城市，逐个归一会拼出
            # 「苏州/杭州/北京/China\\Hunan-Changsha/…」这种中英混杂串，比不写更糟。
            # 筛选用的 location 字段两档都正确（normalizer 认得 `China\\Province-City`）。
            cities = str(row.get("_places") or "").strip()
            bits = []
            if cities:
                bits.append(f"工作地点：{cities}")
            dept = str(row.get("deptName") or "").strip()
            if dept:
                bits.append(f"所属部门：{dept}")
            if row.get("_intentions"):
                bits.append(str(row["_intentions"]))
            # ⚠️ 没取到方向正文时**什么都不补**。列表自带的 mainBusiness/jobRequire 是占位句
            # 「请您详见岗位意向中的岗位职责」，把它当正文写进卡片既骗用户、又把薄卡凑够
            # 60 字混进「有效在招」计数——「指标诚实，不拿低质量岗滥竽充数」不许这么干。
            # 快档只出骨架，正文由 enrich 链路（不设 CRAWL_DETAIL_CAP）补齐。
            jd_url = self.DETAIL_URL.format(adv=adv)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location or None,
                # scenarioName/_scenario 即「应届生」「实习生」，正是三桶分类要的信号；
                # 分类交给 normalizer，adapter 不自己判。
                job_type=str(row.get("scenarioName") or row.get("_scenario") or "").strip() or None,
                summary="\n\n".join(bits).strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=str(row.get("lastUpdateDate") or "").strip() or None,
            ))
        return jobs
