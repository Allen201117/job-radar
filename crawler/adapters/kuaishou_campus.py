"""快手**校园招聘**门户（campus.kuaishou.cn）—— 纯 httpx 零鉴权零浏览器。

与既有 `kuaishou` adapter 的关系：那个抓的是社招（`zhaopin.kuaishou.cn/#/official/**social**/`，
需要 Playwright 拦截页面签名请求）。校招是**另一个站**，且接口是公开的 `/open/` 路径，httpx 直连即可。
2026-08-04 之前库里快手校招岗 = 1 个，就是因为只接了社招那个站。

接口（2026-08-04 live 实测）：
  1) 招聘子项目字典（用来发现「今年是哪个项目」）——GET，零参数即可：
     `https://campus.kuaishou.cn/recruit/campus/e/api/v1/dictionary/batch?types=recruitSubProject`
     → result.recruitSubProject = [{code:"20271779425607", name:"2027应届生"},
                                   {code:"20271772783534", name:"2027实习生"}, …历年]
  2) 职位列表——**POST**（GET 会返 40014 parameter is incorrect）：
     `https://campus.kuaishou.cn/recruit/campus/e/api/v1/open/positions/simple`
     body `{"recruitSubProjectCodes":[code],"pageSize":100,"pageNum":1}`
     → result.total / result.list[{id,name,description,positionDemand,workLocationDicts,…}]
  3) 逐岗详情页 `https://campus.kuaishou.cn/#/campus/job-info/{id}`
     （已 live 浏览器打开 id=13012 验证：渲染出岗位名「【快Star】多模态大模型数据策略算法工程师」
       + 职位描述 + 任职要求全文）

⚠️ **项目码必须动态发现，不许硬编码**：`20271779425607` 这种码每届都变，写死就等于明年自动失效，
而校招 adapter 恰恰是每年只在换届时才最需要它工作的。字典接口把码和名字（"2027应届生"）一起给了，
按名字里的年份挑当季即可——顺带这个名字也是最可靠的届别来源，直接喂给 grad_class 抽取。
"""
import json
import re
from typing import Optional

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter

_HOST = "https://campus.kuaishou.cn"
_DICT_API = f"{_HOST}/recruit/campus/e/api/v1/dictionary/batch"
_LIST_API = f"{_HOST}/recruit/campus/e/api/v1/open/positions/simple"
_DETAIL = _HOST + "/#/campus/job-info/{id}"

# 子项目名形如「2027应届生」「2027实习生」「2026应届生」。取年份用来挑当季，取后缀用来分校招/实习。
_SUBPROJECT_NAME_RE = re.compile(r"(20\d{2})\s*(应届|实习|校园|秋招|春招)")


def _parse_subproject(name: str):
    """子项目名 → (年份, 是否实习)。认不出返回 (None, False)。"""
    m = _SUBPROJECT_NAME_RE.search(str(name or ""))
    if not m:
        return None, False
    return int(m.group(1)), m.group(2) == "实习"


class KuaishouCampusAdapter(PlaywrightAdapter):
    """source_url 填 `https://campus.kuaishou.cn/`（本 adapter 只服务快手一家，host 写死）。"""

    name = "kuaishou_campus"
    company_name = "快手 Kuaishou"
    official_hosts = ("campus.kuaishou.cn",)

    _PAGE_SIZE = 100
    _MAX_PAGES = 30          # 100×30=3000/子项目，远超实测规模（2027 应届 77 + 实习 228）
    # 只抓最近 N 届：历年子项目（2020~2025）里的岗早就关了，抓回来全是死链，纯属给探活添堵。
    _RECENT_CLASSES = 2
    posts_keys = ("result.list",) + PlaywrightAdapter.posts_keys

    def _discover_subprojects(self, client: httpx.Client) -> list:
        """发现招聘子项目，只留最近 _RECENT_CLASSES 届。返回 [(code, name, grad_year, is_intern)]。"""
        resp = client.get(_DICT_API, params={"types": "recruitSubProject"})
        resp.raise_for_status()
        rows = ((resp.json() or {}).get("result") or {}).get("recruitSubProject") or []
        parsed = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = (row.get("code") or "").strip()
            label = (row.get("name") or "").strip()
            year, is_intern = _parse_subproject(label)
            if code and year:
                parsed.append((code, label, year, is_intern))
        if not parsed:
            raise RuntimeError("kuaishou_campus: 字典接口没返回可识别的招聘子项目")
        newest = max(p[2] for p in parsed)
        # 保留当季与上一届：换届当口两届并存（27 届正式批已开、26 届还在收尾），都要。
        return [p for p in parsed if p[2] > newest - self._RECENT_CLASSES]

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": f"{_HOST}/",
            "Origin": _HOST,
        }
        collected = []
        totals = 0
        complete_all = True
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            for code, label, _year, _is_intern in self._discover_subprojects(client):
                got = 0
                total: Optional[int] = None
                for page in range(1, self._MAX_PAGES + 1):
                    try:
                        resp = client.post(_LIST_API, json={
                            "recruitSubProjectCodes": [code],
                            "pageSize": self._PAGE_SIZE,
                            "pageNum": page,
                        })
                        resp.raise_for_status()
                        result = (resp.json() or {}).get("result") or {}
                    except (httpx.HTTPError, ValueError):
                        # 首页就失败 → 该子项目这轮放弃（其余子项目继续）；中途失败保留已拿到的。
                        complete_all = False
                        break
                    rows = result.get("list") or []
                    if not rows:
                        break
                    for row in rows:
                        if isinstance(row, dict):
                            # 子项目名带届别（"2027应届生"），是比标题更可靠的届别来源 → 落到 job_type 供抽取
                            row["_subproject"] = label
                    collected.append({"result": {"list": rows}})
                    got += len(rows)
                    if total is None:
                        total = result.get("total")
                        if isinstance(total, int):
                            totals += total
                    if isinstance(total, int) and got >= total:
                        break
                else:
                    complete_all = False   # 跑满 _MAX_PAGES 还没收齐 → 不敢自称抓全
                if isinstance(total, int) and got < total:
                    complete_all = False
        if not collected:
            raise RuntimeError("kuaishou_campus: 所有子项目都没返回职位")
        self.reported_total = totals or None
        self.fetch_complete = complete_all
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        pid = post.get("id")
        title = (post.get("name") or "").strip()
        if not pid or not title:
            return None
        # 只要在招的：positionStatusCode=Release 是「已发布」，其余（暂停/关闭）不入库，
        # 免得列表夹带的已关闭岗进来再靠探活慢慢清（wt/hotjob 那种 52%/71% 死岗的教训）。
        if (post.get("positionStatusCode") or "").strip() != "Release":
            return None
        desc = (post.get("description") or "").strip()
        demand = (post.get("positionDemand") or "").strip()
        summary = (desc + ("\n\n【任职要求】\n" + demand if demand else "")).strip() or None
        locs = post.get("workLocationDicts")
        location = None
        if isinstance(locs, list) and locs and isinstance(locs[0], dict):
            location = (locs[0].get("name") or "").strip() or None
        jd_url = _DETAIL.format(id=pid)
        # 子项目名（"2027应届生"/"2027实习生"）进 job_type：既让 recruitmentCategory 分对校招/实习桶，
        # 也让 grad_class 抽到准确届别（比从标题猜可靠得多）。
        subproject = (post.get("_subproject") or "").strip()
        job_type = subproject or "校园招聘"
        return RawJob(
            company=self.company_name,
            title=title,
            location=location,
            job_type=job_type,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )
