"""比亚迪招聘适配器。

列表和详情 JSON 接口公开，但逐岗页面 URL 含前端 AES 加密参数。适配器先用公开
queryList 按行偏移量拉全列表，再让官方页面的 Vue Router 批量生成每个职位的加密
详情 URL；无需逐个点击。queryDetail 只用于有限正文富化，不限制列表岗位产出。
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import httpx

from .base import BaseAdapter, RawJob, exc_brief, resolve_detail_cap
from .china_location import is_china_company_location

logger = logging.getLogger(__name__)


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list_offsets(total: int, page_size: int) -> List[int]:
    """Return queryList row offsets; its pageNum parameter is an offset, not a page index."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    return list(range(0, max(1, total), page_size))


_ROUTER_READY_JS = """() => {
    const root = document.querySelector('#app');
    return root && root.__vue__ && root.__vue__.$router;
}"""

# 官方路由把整段 query 做 AES 加密（stringifyQuery / parseQuery 成对），密文是 base64，里面会有 '/'。
# 🚫 详情链接只能用 route.fullPath 拼，不能用 route.href（2026-10-11 立）：
# ❌ Vue Router 生成 href 时要过一遍 cleanPath，把连续的 '/' 压成一个——密文里恰好有 '//' 的岗（约 1.3%）
#    链接少一个字符，官方页面解不出 id，打开是空壳页（页面自己的 queryDetail 回 code=4005）。
#    库里 7,481 个在招岗有 96 个是这种坏链接，其中 32 个当天还在官网列表里。
# ✅ fullPath 不过 cleanPath；'#' 之前的部分（路由 base）仍取自 href，那一段没有密文。
#    每条链接再用官方路由解回去，id 对不上的不出（jd_url 准确性高于一切）。
_BUILD_DETAIL_URLS_JS = """ids => {
    const router = document.querySelector('#app').__vue__.$router;
    return ids.map(id => {
        const resolved = router.resolve({path: '/social/socialPositionDetails', query: {id}});
        const fullPath = resolved.route.fullPath;
        const back = router.resolve(fullPath).route.query || {};
        const prefix = new URL(resolved.href.split('#')[0], location.origin).href;
        return [id, prefix + '#' + fullPath, back.id == null ? null : String(back.id)];
    });
}"""

# 把库里的详情链接解回岗位 id（撤岗核验用，见 crawler/byd_liveness.py）。只认「解得出 15~20 位数字
# 且再加密回去与原密文逐字相同」的；老的坏链接（'//' 被压成 '/'）试着在某个 '/' 处补回，唯一解才认——
# 「补回后的密文解出 id、该 id 加密回来就是补回后的密文、且官方路由的 href 给它生成的正是库里这条坏链接」。
# 最后一条直接问路由，不自己猜 cleanPath 的压法（各版本对 '///' 的处理不一样）。
_DECODE_DETAIL_URLS_JS = """encs => {
    const router = document.querySelector('#app').__vue__.$router;
    const ROUTE = '/social/socialPositionDetails';
    const dec = s => {
        try { const q = router.resolve(ROUTE + '?' + s).route.query; return q && q.id != null ? String(q.id) : null; }
        catch (e) { return null; }
    };
    const enc = id => router.resolve({path: ROUTE, query: {id}}).route.fullPath.split('?')[1];
    const viaHref = id => router.resolve({path: ROUTE, query: {id}}).href.split('?')[1];
    const valid = id => !!id && /^\\d{15,20}$/.test(id);
    const variants = (s, n) => {
        const pos = [];
        for (let i = 0; i < s.length; i++) if (s[i] === '/') pos.push(i);
        const out = [];
        if (n === 1) for (const i of pos) out.push(s.slice(0, i) + '/' + s.slice(i));
        if (n === 2) for (let a = 0; a < pos.length; a++) for (let b = a; b < pos.length; b++) {
            const t = s.slice(0, pos[b]) + '/' + s.slice(pos[b]);
            out.push(t.slice(0, pos[a]) + '/' + t.slice(pos[a]));
        }
        return out;
    };
    return encs.map(s => {
        const id = dec(s);
        if (valid(id) && enc(id) === s) return [s, id, null];
        const hits = new Map();
        for (const n of [1, 2]) for (const cand of variants(s, n)) {
            const cid = dec(cand);
            if (valid(cid) && enc(cid) === cand && viaHref(cid) === s) hits.set(cand, cid);
        }
        if (hits.size === 1) { const [cand, cid] = [...hits.entries()][0]; return [s, cid, cand]; }
        return [s, null, null];
    });
}"""

DETAIL_URL_PREFIX = "https://job.byd.com/portal/pc/#/social/socialPositionDetails?"

# 空骨架里唯一有值的字段是 collectionStatus（2026-10-11 实测 5,429 个已撤岗 + 300 个伪 id 无一例外）；
# 在招岗最少 10 个字段有值（列表 2,078 个 id 逐个问：10~13 个）。多出任何一个别的有值字段都不认作空骨架
# ——接口哪天给骨架加了默认字段，byd_liveness 的阴性对照会当场不过，而不是悄悄判错。
_GONE_ALLOWED_KEYS = frozenset({"collectionStatus"})


def detail_state(status_code, body, asked_id: str) -> str:
    """queryDetail 的一次回答 → 'live' / 'gone' / 'unknown'。

    官网对「已撤岗」和「从没有过这个 id」回的是同一种东西：HTTP 200 + code=0 + 字段全空的骨架
    （没有任何状态字段，页面拿它渲染出来就是空壳）。在招岗回带同一个 id + 岗位名。
    code != 0（如 4005 数据校验不通过）、半截数据、非 200 一律 unknown——宁可漏判不可错杀。
    ⚠️ 'gone' 只说明「此刻官网查不到这个已发布岗位」，调用方必须再配上「不在全量列表里」+ 阳性对照
    才能下架（接口整体退化时也可能对在招岗回空骨架）。"""
    if status_code != 200 or not isinstance(body, dict) or body.get("code") != 0:
        return "unknown"
    data = body.get("data")
    if not isinstance(data, dict):
        return "unknown"
    name = str(data.get("positionName") or "").strip()
    if data.get("id") is not None and str(data.get("id")) == str(asked_id) and name:
        return "live"
    filled = {k for k, v in data.items() if v not in (None, "", [], {})}
    if data.get("id") is None and not name and filled <= _GONE_ALLOWED_KEYS:
        return "gone"
    return "unknown"


def _verified_detail_urls(resolved) -> dict:
    """[(岗位 id, 详情链接, 官方路由从这条链接里解回的 id)] → {岗位 id: 详情链接}，只留解回去对得上的。
    前缀不是我们入库的那一种也不留（官网哪天换了路由 base，fetch 会因为一条链接都没有而报错，不会安静出 0 岗）。"""
    return {
        str(job_id): url
        for job_id, url, back_id in resolved
        if url and url.startswith(DETAIL_URL_PREFIX)
        and back_id is not None and str(back_id) == str(job_id)
    }


class BydAdapter(BaseAdapter):
    name = "byd"
    company_name = "比亚迪"
    LIST_API = "https://job.byd.com/portal/api/portal-api/position/queryList"
    DETAIL_API = "https://job.byd.com/portal/api/portal-api/position/queryDetail"
    LIST_PAGE_SIZE = 1000
    # queryDetail 是公开 httpx 接口（非浏览器、很快）→ 默认覆盖全量列表逐岗补 JD 正文（~2k 岗，并发约 1-2min）。
    # 旧 DETAIL_CAP=20 只补 20 个 → 其余 ~2000 岗全是无正文薄卡（不进 count_valid_active_jobs）。
    # 快档 daily 仍可用 env CRAWL_DETAIL_CAP=0 跳过逐岗富化（resolve_detail_cap），只抓列表骨架。
    DETAIL_CAP = 6000
    DETAIL_WORKERS = 10  # 单 host(job.byd.com) 并发上限：礼貌 + 防限流
    ROUTE_BATCH_SIZE = 500
    # 撤岗不走 run.py 的 list-absence，走 crawler/byd_liveness.py（不在全量列表 + 详情接口空骨架，双条件）。
    # 列表本身是全集（2026-10-11 全集对拍：库里 7,481 个在招岗，详情在招却不在列表的 0 个），不开 absence 的
    # 原因是它认的是「这一轮没被写库」——列表里有、却被后面的清洗挡掉的行同样没被写库，那不是撤岗。
    supports_absence_liveness = False

    def should_skip(self, source_url: str) -> Optional[str]:
        return None

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://job.byd.com/portal/pc/",
            "Origin": "https://job.byd.com",
        }

    def _list_payload(self, offset: int) -> dict:
        return {
            "positionTypeArr": [],
            "positionProvinceArr": [],
            "positionCityArr": [],
            "positionOrgArr": [],
            "vagueCondition": "",
            "searchType": 1,
            "zpType": "00251",
            "pageNum": offset,
            "pageSize": self.LIST_PAGE_SIZE,
        }

    def _fetch_list_rows(self, client: httpx.Client) -> List[dict]:
        rows_by_id = {}
        total = 0
        offsets = [0]
        complete = True  # 翻页途中失败会置 False；只有它仍为 True 时下面的一致性检查才有意义
        for offset in offsets:
            try:
                response = client.post(self.LIST_API, json=self._list_payload(offset))
                response.raise_for_status()
                body = response.json() or {}
            except Exception as exc:
                if offset == 0:
                    raise  # 首页（offset=0）失败交给 run.py 记录为 failed
                logger.warning(
                    "byd: offset=%d 抓取失败，保留已抓 %d 条（尽力而为）：%s",
                    offset, len(rows_by_id), exc_brief(exc),
                )
                complete = False
                break  # 后续页尽力而为，保留已抓的行；不再触发下面的一致性检查
            data = body.get("data") or {}
            rows = data.get("data") or []
            if offset == 0:
                reported = _int_or_none(data.get("total"))
                if reported is not None:
                    self.reported_total = reported
                total = int(data.get("total") or len(rows))
                offsets.extend(_list_offsets(total, self.LIST_PAGE_SIZE)[1:])
            for row in rows:
                job_id = str((row or {}).get("id") or "").strip()
                if job_id:
                    rows_by_id[job_id] = row
        # 这条一致性检查只在「全部翻页请求都成功、但去重后仍凑不齐官方自报总数」时才有意义
        # （原本就存在的数据完整性断言，与本次翻页异常处理无关）；途中失败已经 break+置 complete=False，
        # 不应再被这里二次 raise 掉——那会把刚保留下来的部分页又白白丢掉。
        if complete and total and len(rows_by_id) < total:
            raise RuntimeError(
                f"byd: queryList returned {len(rows_by_id)} unique rows, expected {total}"
            )
        return list(rows_by_id.values())

    def _router_batches(self, source_url: str, script: str, items: List[str]) -> list:
        """打开官方页面，等它的 Vue Router 就绪，把 items 分批喂给 script，结果按原顺序拼回。"""
        from playwright.sync_api import sync_playwright

        out = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                locale="zh-CN",
                viewport={"width": 1366, "height": 900},
            )
            page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_function(_ROUTER_READY_JS, timeout=15000)
            for start in range(0, len(items), self.ROUTE_BATCH_SIZE):
                out.extend(page.evaluate(script, items[start:start + self.ROUTE_BATCH_SIZE]))
            browser.close()
        return out

    def _generate_detail_urls(self, source_url: str, job_ids: List[str]) -> dict:
        """{岗位 id: 详情链接}。官方路由解回去 id 对不上的不在返回里。"""
        return _verified_detail_urls(self._router_batches(source_url, _BUILD_DETAIL_URLS_JS, job_ids))

    def decode_detail_urls(self, source_url: str, jd_urls: List[str]) -> dict:
        """{库里的详情链接: (岗位 id, 修好的链接或 None)}；解不出来的不在返回里。

        修好的链接只在老的坏链接上出现（'//' 被压成 '/'，见 _BUILD_DETAIL_URLS_JS 上方说明）。"""
        encs = sorted({u[len(DETAIL_URL_PREFIX):] for u in jd_urls if (u or "").startswith(DETAIL_URL_PREFIX)})
        decoded = {}
        for enc, job_id, fixed in self._router_batches(source_url, _DECODE_DETAIL_URLS_JS, encs):
            if job_id:
                decoded[DETAIL_URL_PREFIX + enc] = (str(job_id), DETAIL_URL_PREFIX + fixed if fixed else None)
        return decoded

    def _fetch_one_detail(self, client: httpx.Client, job_id: str) -> dict:
        """单岗 queryDetail（公开 httpx POST）→ data dict；任何网络/解析错误返回空（不阻断整批）。"""
        try:
            response = client.post(self.DETAIL_API, json={"id": job_id, "pageSize": 4})
            response.raise_for_status()
            return (response.json() or {}).get("data") or {}
        except (httpx.HTTPError, ValueError):
            return {}

    def _fetch_details(self, client: httpx.Client, job_ids: List[str]) -> dict:
        """并发用公开 queryDetail 给全量列表逐岗补 JD 正文（tagDetailList → summary）。返回 {job_id: detail}。
        cap=0（快档 CRAWL_DETAIL_CAP=0）→ 跳过逐岗富化；否则取前 cap 个（默认 DETAIL_CAP 覆盖全量）。"""
        cap = resolve_detail_cap(self.DETAIL_CAP)
        targets = job_ids[:cap] if cap else []
        if not targets:
            return {}
        details = {}
        with ThreadPoolExecutor(max_workers=self.DETAIL_WORKERS) as ex:
            futures = {ex.submit(self._fetch_one_detail, client, jid): jid for jid in targets}
            for fut in as_completed(futures):
                detail = fut.result()
                if detail:
                    details[futures[fut]] = detail
        return details

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = self._headers()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            list_rows = self._fetch_list_rows(client)
            job_ids = [str(row.get("id")) for row in list_rows]
            detail_urls = self._generate_detail_urls(source_url, job_ids)

            details = self._fetch_details(client, job_ids)

        jobs = []
        for row in list_rows:
            job_id = str(row.get("id") or "").strip()
            detail_url = detail_urls.get(job_id)
            if detail_url and "socialPositionDetails?" in detail_url:
                jobs.append({
                    "row": row,
                    "detail": details.get(job_id) or {},
                    "jd_url": detail_url,
                })
        if not jobs:
            raise RuntimeError(
                "byd: official router generated no encrypted detail URLs"
            )
        # 抓全 = 列表翻到了自报总数，且每一行都拿到了验过的详情链接；少一条链接就是少一个岗，不算抓全。
        self.fetch_complete = (
            self.reported_total is not None
            and len(list_rows) >= self.reported_total
            and len(jobs) == len(list_rows)
        )
        return json.dumps({"jobs": jobs}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for item in rows:
            detail = item.get("detail") or {}
            row = item.get("row") or {}
            jd_url = str(item.get("jd_url") or "").strip()
            title = str(detail.get("positionName") or row.get("positionName") or "").strip()
            province = str(detail.get("province") or row.get("province") or "").strip()
            city = str(detail.get("city") or row.get("city") or "").strip()
            location = "-".join(part for part in (province, city) if part)
            if not (
                title
                and jd_url.startswith("https://job.byd.com/portal/pc/#/social/")
                and "socialPositionDetails?" in jd_url
                and is_china_company_location(location)
            ):
                continue
            sections = []
            for section in detail.get("tagDetailList") or []:
                if not isinstance(section, dict):
                    continue
                name = str(section.get("name") or "").strip()
                text = str(section.get("detail") or "").strip()
                if text:
                    sections.append(f"【{name}】\n{text}" if name else text)
            jobs.append(RawJob(
                company=self.company_name,
                title=title,
                location=location,
                job_type=(
                    str(
                        detail.get("orgName")
                        or detail.get("fatherOrgName")
                        or row.get("orgAliasName")
                        or row.get("fatherOrgAliasName")
                        or ""
                    ).strip()
                    or None
                ),
                summary="\n\n".join(sections) or None,
                jd_url=jd_url,
                apply_url=jd_url,
                posted_at=(
                    str(
                        detail.get("publishTime")
                        or row.get("publishTime")
                        or row.get("createTime")
                        or ""
                    )[:10]
                    or None
                ),
            ))
        return jobs
