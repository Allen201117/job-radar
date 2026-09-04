"""同花顺（campus.10jqka.com.cn）自建招聘门户适配器，纯 httpx、零鉴权。

必投清单「金融」里的同花顺此前**连一行源都没有**（2026-09-04 缺口普查）。官网走
campus.10jqka.com.cn 这一个门户，社招/校招/实习**共用同一个列表接口**，逐岗有稳定详情页。

公开链路（2026-09-04 live 抓包验证，无 cookie/token）：
1. GET /api/v3/school_recruitment/apply/apply_list?page={p}&pageSize=10
   -> {"erro_msg":"Success","ex_data":{"apply_show_do_list":[...],"total":99,"pages":10,...}}
   行字段：id / name / base(工作地) / intro(岗位职责) / requirement(岗位要求) /
          apply_type_first(职能) / apply_colony_name(集群) / apply_recruitment_series_name(招聘系列)
2. 稳定单岗页 https://campus.10jqka.com.cn/job/detail?id={id}
   （live 实测 id=2160 渲染出「AIME基座预训练算法工程师」标题 + 完整 JD 正文）

⚠️ 三个真实踩过的坑，改本文件前先读：
  ① **响应信封是 `ex_data` 不是 `data`**，列表键是 `apply_show_do_list` 不是 `list`。
     按常规名去取会拿到空列表、进而误判「对方没开」。
  ② **`series_id` 参数被服务端忽略**：六个招聘系列（2027届校园招聘/AIME计划/ACMer摘星计划/
     日常实习/云软件校招/社招）传任何一个都返回**同一批全量**岗位。所以只能**不带 series_id
     翻一次**，靠每行的 `apply_recruitment_series_name` 区分系列；按系列循环只会把同一批
     抓 N 遍。
  ③ **`pageSize` 被服务端硬顶到 10**（传 20/50 都只回 10 条）。因此 PAGE_SIZE 必须写 10 ——
     `paginate_all` 用它做「短页=末页」兜底，写大了会在第一页就误判抓完（实测传 20 时
     99 个岗只抓到 10 个，还自称抓全）。真实末页判据走接口自报的 `total`。

job_type 直填 `apply_recruitment_series_name`：其中「2027届校园招聘」「日常实习」「云软件校招」
能被 normalizer.is_recruitment_type 认成真招聘类型；「AIME计划」「ACMer摘星计划」认不出，
自动退回正文推断——这正是该门禁想要的行为，不要为了「填满」去硬映射。
"""
import json
import re
from typing import List, Optional

import httpx

from .base import BaseAdapter, PageResult, RawJob, paginate_all


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


class TongHuaShunAdapter(BaseAdapter):
    """同花顺招聘门户。source_url 填 `https://campus.10jqka.com.cn/job/list`。"""

    name = "tonghuashun"
    company_name = "同花顺"

    LIST_API = "https://campus.10jqka.com.cn/api/v3/school_recruitment/apply/apply_list"
    DETAIL_URL = "https://campus.10jqka.com.cn/job/detail?id={job_id}"
    PAGE_SIZE = 10   # 服务端硬顶，见文件头坑 ③；不要改大
    MAX_PAGES = 60   # 10/页 → 封顶 600 岗，当前 99，余量充足

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/plain,*/*"}

        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            def fetch_page(page: int) -> PageResult:
                response = client.get(self.LIST_API, params={"page": page, "pageSize": self.PAGE_SIZE})
                response.raise_for_status()
                payload = response.json() or {}
                envelope = payload.get("ex_data")
                if not isinstance(envelope, dict):
                    # 接口结构变了（或被挡）——必须抛错记 failed，不许安静返 0 条，
                    # 否则会被误读成「同花顺没开招聘」（见 CLAUDE.md「接口返 0 不能证明对方没开」）。
                    raise RuntimeError(f"tonghuashun: apply_list 无 ex_data 信封（msg={payload.get('erro_msg')!r}）")
                rows = envelope.get("apply_show_do_list")
                if not isinstance(rows, list):
                    raise RuntimeError("tonghuashun: ex_data.apply_show_do_list 不是列表")
                return PageResult(items=rows, total=_int_or_none(envelope.get("total")))

            rows, total, complete = paginate_all(
                fetch_page, page_size=self.PAGE_SIZE, first_page=1,
                max_pages=self.MAX_PAGES, label="tonghuashun",
            )

        if not rows:
            raise RuntimeError("tonghuashun: apply_list 返回 0 个岗位")
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []

        jobs: List[RawJob] = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("id") or "").strip()
            title = _clean(row.get("name"))
            if not job_id or not title or job_id in seen:
                continue
            seen.add(job_id)

            summary = "\n".join(
                part for part in (_clean(row.get("intro")), _clean(row.get("requirement"))) if part
            ) or None
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=_clean(row.get("base")) or None,
                job_type=_clean(row.get("apply_recruitment_series_name")) or None,
                summary=summary,
                jd_url=self.DETAIL_URL.format(job_id=job_id),
            ))
        return jobs
