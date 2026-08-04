"""阿里巴巴集团 BU 招聘门户通用适配器（直连公开 position/search JSON 接口，零浏览器）。

阿里各业务集团共用同一套招聘门户（Spring SPA），每个 BU 一个白标域名：
  talent.taotian.com(淘天) / careers.aliyun.com(阿里云) / talent.amap.com(高德) /
  talent.dingtalk.com(钉钉) / talent.ele.me(饿了么·淘宝闪购) / cn-jobs.cainiao.com(菜鸟) /
  jobs.hujing-dme.com(虎鲸文娱·优酷大麦) / talent-holding.alibaba.com(控股集团) /
  aidc-jobs.alibaba.com(阿里国际) / careers-tongyi.alibaba.com(通义) / 等。
host 从 source_url 动态解析，一个 adapter 全家通用；company 由 sources.company 兜底填充。

流程（全 httpx 匿名）：
  1. GET https://{host}/?lang=zh 种 SESSION + XSRF-TOKEN cookie；
  2. POST https://{host}/position/search?_csrf={XSRF-TOKEN}
     json={"channel":"GROUP_OFFICIAL_SITE","language":"zh","pageIndex":N,"pageSize":50,...}
     返回 {"content":{"totalCount":N,"datas":[{id,name,workLocations,description,
     requirement,publishTime,...}]}}，服务端按域名圈定本 BU 岗位；翻页到收齐 totalCount。
逐岗稳定详情页 = `https://{host}/off-campus/position-detail?lang=zh&positionId={id}`
（id-only；13 个 BU 域逐一 live render-verify 过：渲染出本岗标题+JD 正文，过质量门。
 注意集团目录域 talent.alibaba.com / talent.freshippo.com 的 detail 路由**不渲染**详情
 （回落到「更多招聘」导航页），不能当 source 入库——只用 BU 自有域。）
"""
import json
from typing import Optional
from urllib.parse import urlparse

import httpx

import normalizer
from .base import RawJob
from .playwright_base import PlaywrightAdapter


def _first(post: dict, keys) -> str:
    for k in keys:
        v = post.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AlibabaAdapter(PlaywrightAdapter):
    """阿里集团 BU 门户通用层。source_url 填该 BU 域的列表页，如
    `https://talent.taotian.com/off-campus/position-list?lang=zh`。"""

    name = "alibaba"
    company_name = ""  # 由 sources.company 兜底填充（一个 adapter 服务全部 BU 域）
    official_hosts = ()  # host 动态解析，不做静态白名单

    _PAGE_SIZE = 100
    _MAX_PAGES = 5    # 服务端 offset 硬封顶 500/过滤条件（实测 careers.aliyun.com：第 6 页恒返空）
    # totalCount>500 时按「品类 subCategories + 大城市 regions(adcode)」双维分片补漏，按 id 去重。
    # sort 参数被服务端忽略（实测 6 种猜测全 same），无法翻转排序抄尾，只能靠分片并集逼近全量。
    _REGION_SHARDS = ("330100", "110100", "310100", "440300", "440100")  # 杭州/北京/上海/深圳/广州
    posts_keys = ("content.datas",) + PlaywrightAdapter.posts_keys

    # 板块开关（子类 AlibabaCampusAdapter 覆盖）。判据 2026-08-04 live 实测（淘天域，浏览器内同源实测）：
    #   channel="GROUP_OFFICIAL_SITE" → 605 条，batchName=null            → 社招
    #   channel="" / 任意服务端不认的值 → 34 条，batchName=淘天集团2026届秋季应届生招聘 → 校招
    # ⚠️ 「校招用空 channel」是服务端 fallback 行为，不是文档化契约 → 绝不能只信这个参数：
    # _map 里还要用 payload 自证是校招（batchName/categoryType），详见 AlibabaCampusAdapter。
    _CHANNEL = "GROUP_OFFICIAL_SITE"
    _PORTAL = "off-campus"        # 详情页与 Referer 的路由段
    _JOB_TYPE = "社会招聘"

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        host = urlparse(source_url).netloc
        if not host:
            raise RuntimeError(f"alibaba: 无法从 source_url 解析 host: {source_url}")
        base = f"https://{host}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,en;q=0.9",
            "Content-Type": "application/json",
            "Referer": f"{base}/{self._PORTAL}/position-list",
            "Origin": base,
        }
        collected = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            # 1) 种 cookie 拿 XSRF-TOKEN（部分域首页即种，部分要列表页路由）
            client.get(f"{base}/?lang=zh")
            csrf = client.cookies.get("XSRF-TOKEN")
            if not csrf:
                client.get(f"{base}/{self._PORTAL}/position-list?lang=zh")
                csrf = client.cookies.get("XSRF-TOKEN")
            if not csrf:
                raise RuntimeError(f"alibaba: 拿不到 XSRF-TOKEN ({host})")

            seen_ids = set()
            # 接口是否至少成功应答过一次。用来区分两种「一条都没有」：
            #   · 接口 200 且 totalCount=0 → **真的没岗**（校招频道在正式批开闸前完全正常）
            #   · 接口从没答上来（超时/5xx/JSON 坏） → 真故障，必须 raise 让 crawl_run 记 failed
            # 不区分的话，「2027 届还没开闸」会天天被记成抓取失败，把真故障淹在噪音里。
            api_answered = [False]

            def sweep(regions: str = "", sub_categories: str = ""):
                """单过滤条件下翻页收齐（服务端 offset 封顶 500/条件），返回该条件 totalCount。"""
                total: Optional[int] = None
                got = 0
                for page in range(1, self._MAX_PAGES + 1):
                    try:
                        resp = client.post(f"{base}/position/search?_csrf={csrf}", json={
                            "channel": self._CHANNEL, "language": "zh",
                            "batchId": "", "categories": "", "deptCodes": [],
                            "key": "", "regions": regions, "subCategories": sub_categories,
                            "pageIndex": page, "pageSize": self._PAGE_SIZE,
                        })
                        resp.raise_for_status()
                        payload = resp.json()
                        api_answered[0] = True
                    except (httpx.HTTPError, ValueError):
                        break
                    content = payload.get("content") or {}
                    rows = content.get("datas") or []
                    if not rows:
                        break
                    fresh = []
                    for row in rows:
                        rid = row.get("id")
                        if rid in seen_ids:
                            continue
                        seen_ids.add(rid)
                        row["_host"] = host
                        fresh.append(row)
                    if fresh:
                        collected.append({"content": {"datas": fresh}})
                    got += len(rows)
                    if total is None:
                        total = _int_or_none(content.get("totalCount"))
                    if total and got >= total:
                        break
                return total

            # 2) 全量翻页；totalCount 超 offset 封顶时「品类 + 大城市」双维分片补漏（id 已去重）
            grand_total = sweep()
            if grand_total is not None:
                self.reported_total = grand_total
            if (grand_total or 0) > self._MAX_PAGES * self._PAGE_SIZE:
                try:
                    cat_resp = client.post(f"{base}/category/list?_csrf={csrf}", json={
                        "channel": "group_official_site", "language": "zh",
                    })
                    cat_tree = cat_resp.json().get("content") or []
                except (httpx.HTTPError, ValueError):
                    cat_tree = []
                for cat in cat_tree:
                    codes = ",".join(
                        s.get("code") or "" for s in (cat.get("categories") or []) if s.get("code")
                    )
                    if codes:
                        sweep(sub_categories=codes)
                for adcode in self._REGION_SHARDS:
                    sweep(regions=adcode)
        if not collected and not api_answered[0]:
            raise RuntimeError(f"alibaba: position/search 无应答 ({host})")
        if not collected:
            # 接口答了、就是 0 条：校招频道在正式批开闸前的正常状态（2026-08-04 实测 13 个 BU
            # 里 11 个校招 0 条）。返回空信封让上层记 0 岗成功，而不是 failed。
            self.reported_total = 0
            self.fetch_complete = True
            return json.dumps({"_intercepted": []}, ensure_ascii=False)
        self.fetch_complete = (
            self.reported_total is not None and len(seen_ids) >= self.reported_total
        )
        return json.dumps({"_intercepted": collected}, ensure_ascii=False)

    def _map(self, post: dict) -> Optional[RawJob]:
        if not isinstance(post, dict):
            return None
        pid = _first(post, ("id",))
        title = _first(post, ("name",))
        host = post.get("_host") or ""
        if not (pid and title and host):
            return None
        desc = _first(post, ("description",))
        req = _first(post, ("requirement",))
        summary = (desc + ("\n\n【任职要求】\n" + req if req else "")).strip() or None
        jd_url = f"https://{host}/{self._PORTAL}/position-detail?lang=zh&positionId={pid}"
        locs = post.get("workLocations")
        location = locs[0] if isinstance(locs, list) and locs and isinstance(locs[0], str) else None
        return RawJob(
            company=self.company_name or "",
            title=title,
            location=location,
            job_type=self._JOB_TYPE,
            summary=summary,
            jd_url=jd_url,
            apply_url=jd_url,
            posted_at=normalizer.pick_publish_date(post),
        )


class AlibabaCampusAdapter(AlibabaAdapter):
    """阿里各 BU 的**校招**频道。source_url 填 `https://{host}/campus/position-list?lang=zh`。

    2026-08-04 live 实测（淘天域，页面同源发请求，逐值对拍）：
        channel="GROUP_OFFICIAL_SITE"  → totalCount=605，batchName=null                     ← 社招
        channel=""（或服务端不认的任意值）→ totalCount=34， batchName=淘天集团2026届秋季应届生招聘 ← 校招
        channel="campus_group_official_site" → totalCount=0（是岗位上的 channels 取值，不是入参取值）
    即：校招不是「另一个 channel 常量」，而是**不传 channel 时的默认集**。

    ⚠️ 为什么不能只信这个入参：它是服务端 fallback 行为、不是文档化契约，哪天默认集改成社招
    我们就会把 3000 个社招岗当校招灌进校招专区（比漏抓更糟——用户按校招投了个社招岗）。
    所以 _map 里用 **payload 自证**：只放行 categoryType=freshman 或 batchName 含「届」的行，
    自证不过的一律丢弃。这与项目「精度红线：能返回数据 ≠ 猜对了」同一条原则。

    详情页 `https://{host}/campus/position-detail?lang=zh&positionId={id}` 已 live 验证渲染出
    本岗标题（浏览器打开 positionId=199902900003 → 标题「算法工程师- AIGC方向（T-Star Lab26届秋招）」）。
    """

    name = "alibaba_campus"
    _CHANNEL = ""            # 见上：校招 = 不传 channel 的默认集
    _PORTAL = "campus"
    _JOB_TYPE = "校园招聘"

    def _map(self, post: dict) -> Optional[RawJob]:
        job = super()._map(post)
        if job is None:
            return None
        # payload 自证：校招行带 categoryType="freshman" 与 batchName（如「淘天集团2026届秋季应届生招聘」）。
        # 两者皆无 → 说明服务端默认集已不是校招，宁可这轮抓 0 条，也不把社招岗灌进校招专区。
        category_type = (post.get("categoryType") or "").strip().lower()
        batch_name = (post.get("batchName") or "").strip()
        if category_type != "freshman" and "届" not in batch_name:
            return None
        # 批次名里带届别（「2026届秋季应届生招聘」）→ 喂给 normalizer 的届别抽取，比标题更可靠。
        if batch_name:
            job.job_type = f"{self._JOB_TYPE} {batch_name}"
        return job
