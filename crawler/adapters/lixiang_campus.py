"""理想汽车校园招聘 / 实习适配器（www.lixiang.com/api-web.lixiang.com，纯 httpx，零鉴权）。

li.jobs.feishu.cn（feishu adapter 现有源）只挂着**社招**门户；理想的校招/实习走的是
自建站 `www.lixiang.com/employ/campus.html` + 独立 API 网关 `api-web.lixiang.com`，
与飞书那条完全是两回事——这条源专门补校招/实习这一半。

## 接口（2026-09-09 Playwright 真渲染拦截探明，全部纯 httpx 可达、无需 cookie/签名）
- 职能分类：`GET {API}/v1/recruit/school/job/function`
  返回 10 个一级分类，每个带 `job_count`（该类自报总数，10 类合计 764）与
  `list`（二级分类叶子 id，供 job-page 用）。
- 列表：`GET {API}/v1/recruit/school/job-page?page=N&page_size=100&job_function_ids=<逗号拼叶子id>`
  必须**按一级分类逐个请求**（不能一次性把 10 类叶子 id 全塞进一个请求——那样只是省请求数，
  拿到的是同一批数据，但会丢失「按类核验抓全」的能力，见下方 fetch_complete）。
  ⚠️ **`hire_mode` 参数被服务端忽略**（live 实测传 1/2/3 结果完全相同）——不能拿它拆
  校招/实习。真正能区分的是列表自带字段 `job_mode`（"201"=正式/校招、"202"=实习）+
  `job_mode_name`（中文"正式"/"实习"）。
- 详情：`GET {API}/v1/recruit/job/detail?job_id=<id>` 返回 `description`/`requirements`
  （HTML 片段）、`department_title`、`location_title`、`subject_name`（如"2026校园招聘"）。

## robots.txt（2026-09-09 核过）
`www.lixiang.com/robots.txt` 只对**该域名的网页**生效，规则是 `Disallow: /*?*`（禁止任何带
查询串的网页路径）——本 adapter 不抓这个域的网页，只打 `api-web.lixiang.com` 的 JSON 接口。
`api-web.lixiang.com/robots.txt` 被网关直接拦截返回
`{"code":100012,"msg":"没有接口访问权限"}`（HTTP 200，非真实 robots.txt 文件内容），
即该路径本身不存在 —— 没有 robots.txt 按惯例视为无限制。

## 逐岗 jd_url
`https://www.lixiang.com/employ/detail/{id}.html?jobCode={code}&fromJob=1`
—— live 点击列表卡片确认（`ctx.expect_page` 拦到新标签页 URL，当前页 URL 不变，是 SPA
`window.open`，只看 `location.href` 会得出"没有逐岗页"的错误结论）；冷加载该 URL（新
context 直接 `goto`，不带任何 referer/session）渲染出了标题原文，过质量门。

## fetch_complete 判据（与 huawei_campus / xiaohongshu 同口径）
按 10 个一级分类逐渠道判"这一类实际抓到的条数 >= 它自报的 job_count"，10 类全部为真才
`fetch_complete=True`。二级叶子 id 在分类间互不重叠（live 验证：10 类合计抓到 764 条，
全局按 id 去重后仍是 764，无跨类重复）——全局 `seen_ids` 去重只作兜底，不改变判定逻辑。
"""
import json
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, resolve_detail_cap, resolve_list_cap

_API_BASE = "https://api-web.lixiang.com/osd-hr-recruitment-website/v1/recruit"
_FUNCTION_API = f"{_API_BASE}/school/job/function"
_LIST_API = f"{_API_BASE}/school/job-page"
_DETAIL_API = f"{_API_BASE}/job/detail"
_DETAIL_URL = "https://www.lixiang.com/employ/detail/{id}.html?jobCode={code}&fromJob=1"

# job_mode → 三桶分类要的招聘类型标签（喂给 normalizer，不自己判）
_JOB_MODE_LABEL = {"201": "校园招聘", "202": "实习"}


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class LixiangCampusAdapter(BaseAdapter):
    name = "lixiang_campus"
    company_name = "理想汽车 Li Auto"
    official_hosts = ("www.lixiang.com", "api-web.lixiang.com")

    PAGE_SIZE = 100
    MAX_PAGES_PER_CATEGORY = 30  # 单个一级分类安全上限（现状 268/100≈3页；留足余量防死循环）
    # 逐岗补正文上限。daily 快档由 env CRAWL_DETAIL_CAP=0 关掉只抓骨架，正文交给 enrich 链路补。
    DETAIL_CAP = 200

    def should_skip(self, source_url: str) -> Optional[str]:
        return None  # 公开 JSON 网关，HEAD 预检对它无意义（同 huawei_campus）

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.lixiang.com/",
        }

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        rows: List[dict] = []
        seen_ids: set = set()
        totals: List[int] = []
        drained: List[bool] = []   # 逐渠道（一级分类）判抓全
        list_cap = resolve_list_cap(1000)  # 现状 764，给 CRAWL_MAX_JOBS 调档留口子

        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers=self._headers()) as client:
            try:
                resp = client.get(_FUNCTION_API)
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise RuntimeError(f"lixiang_campus: job/function 请求失败 —— {exc}") from exc
            categories = ((payload or {}).get("data") or {}).get("list") or []
            if not categories:
                # HTTP 200 + 空 data 同样是假阴性，不许安静返 0（CLAUDE.md「接口返0不能证明没开」）。
                raise RuntimeError(
                    "lixiang_campus: job/function 返回空分类列表（HTTP 200 + 空 data）—— "
                    "不能据此判定理想没开校招，多半是接口改版，需人工核查")

            for cat in categories:
                leaf_ids = [str(x.get("id")) for x in (cat.get("list") or [])
                            if x.get("id") is not None]
                cat_total = _int_or_none(cat.get("job_count"))
                if not leaf_ids:
                    # 分类本身没有叶子 id：自报 0 就算抓全，自报非 0 则这一渠道判未抓全。
                    if cat_total is not None:
                        totals.append(cat_total)
                        drained.append(cat_total == 0)
                    continue
                ids_param = ",".join(leaf_ids)
                got = 0
                for page_no in range(1, self.MAX_PAGES_PER_CATEGORY + 1):
                    if len(rows) >= list_cap:
                        break
                    try:
                        resp = client.get(_LIST_API, params={
                            "page": page_no, "page_size": self.PAGE_SIZE,
                            "job_function_ids": ids_param,
                        })
                        resp.raise_for_status()
                        page_payload = resp.json()
                    except (httpx.HTTPError, ValueError):
                        break
                    data = (page_payload or {}).get("data") or {}
                    items = data.get("items") or []
                    if not items:
                        break
                    for item in items:
                        job_id = item.get("id")
                        if job_id is None or job_id in seen_ids:
                            continue
                        seen_ids.add(job_id)
                        rows.append(item)
                    got += len(items)
                    total_pages = _int_or_none(data.get("total_pages"))
                    if total_pages is not None and page_no >= total_pages:
                        break
                    if len(items) < self.PAGE_SIZE:
                        break  # 短页兜底（接口没给 total_pages 时）
                if cat_total is not None:
                    totals.append(cat_total)
                    drained.append(got >= cat_total)
                else:
                    drained.append(False)  # 连自报总数都没有 → 本渠道不算抓全

            if not rows:
                raise RuntimeError(
                    "lixiang_campus: 全部分类的 job-page 均为空 —— 不据此判定理想没开校招，"
                    "先核查接口是否改版")
            self._enrich_details(client, rows)

        if len(totals) == len(categories):
            self.reported_total = sum(totals)
        self.fetch_complete = len(drained) == len(categories) and all(drained)
        return json.dumps({"result": rows}, ensure_ascii=False)

    def _enrich_details(self, client: httpx.Client, rows: List[dict]) -> None:
        """按 job_id 取详情补正文（description/requirements/部门/招聘届别）。
        取不到就留空——薄卡仍可入库，正文交给 enrich 链路补；一条失败绝不拖垮整源。"""
        cap = resolve_detail_cap(self.DETAIL_CAP)
        for row in rows[:cap]:
            job_id = row.get("id")
            if job_id is None:
                continue
            try:
                resp = client.get(_DETAIL_API, params={"job_id": job_id})
                detail = (resp.json() or {}).get("data") or {}
            except (httpx.HTTPError, ValueError):
                continue
            if not isinstance(detail, dict):
                continue
            row["_description"] = detail.get("description")
            row["_requirements"] = detail.get("requirements")
            row["_department"] = detail.get("department_title")
            row["_subject"] = detail.get("subject_name")

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("result") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs: List[RawJob] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = row.get("id")
            title = str(row.get("title") or "").strip()
            if job_id is None or not title:
                continue
            code = str(row.get("code") or "").strip()
            jd_url = _DETAIL_URL.format(id=job_id, code=code)
            location = str(row.get("location_title") or "").strip() or None
            job_mode = str(row.get("job_mode") or "").strip()
            job_type = _JOB_MODE_LABEL.get(job_mode) or str(row.get("job_mode_name") or "").strip() or None

            bits = []
            dept = str(row.get("_department") or row.get("department_title") or "").strip()
            if dept:
                bits.append(f"所属部门：{dept}")
            subject = str(row.get("_subject") or "").strip()
            if subject:
                bits.append(f"招聘届别：{subject}")
            func_bits = " ".join(x for x in (
                str(row.get("first_job_function_title") or "").strip(),
                str(row.get("second_job_function_title") or "").strip(),
            ) if x)
            if func_bits:
                bits.append(f"职能分类：{func_bits}")
            # description/requirements 是详情接口给的 HTML 片段，交给 normalizer.clean_summary
            # 统一去标签/截断（同 greenhouse 等 ATS 的做法），adapter 不自己剥。
            description = str(row.get("_description") or "").strip()
            if description:
                bits.append(f"职位描述\n{description}")
            requirements = str(row.get("_requirements") or "").strip()
            if requirements:
                bits.append(f"职位要求\n{requirements}")

            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type=job_type,
                summary="\n\n".join(bits).strip() or None,
                jd_url=jd_url,
                apply_url=jd_url,
            ))
        return jobs
