"""比亚迪招聘适配器：社招（BydAdapter）与校招（BydCampusAdapter）两条渠道。

两条渠道是官网的两套接口，别互相套参数：
- 社招：position/queryList（zpType=00251，pageNum 是行偏移量）+ position/queryDetail。
- 校招：postEntryConfig/list（投递入口）→ schoolPortal/queryPositionList → schoolPortal/queryPosition。

🚫 校招别用 position/queryList 换 zpType=00252 去取（2026-10-11 实测）：它有返回、自报 15,582 条，但
   官网没有任何页面这样调它（app.js + 65 个懒加载分块全扫过，传给它的渠道码只有 00251 社招 / 00254 技工），
   其中 11,972 条是 planYear=2024、2024-06 一次性建的旧需求，剩下 3,606 条是 2027 届的内部需求条目
   （正文带一栏「工作经验：3年以上…」的岗位族模板）。官网校招页当天自报「在招职位 (384)」，每个岗下面
   再选「岗位方向 × 部门意向」，页面给学生看的正文没有工作经验那一栏。

逐岗页面 URL 的查询串由前端加密（密钥只有 12 字节，不是标准 AES 的长度，标准库算不出同样的结果），
所以让官方页面自己的 Vue Router 批量生成，无需逐个点击；生成后再用它自己的解码器回验。
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import httpx

from .base import BaseAdapter, RawJob, exc_brief, resolve_detail_cap
from .china_location import is_china_company_location

logger = logging.getLogger(__name__)

_API = "https://job.byd.com/portal/api/portal-api"
_PAGE_PREFIX = "https://job.byd.com/portal/pc/#"

# 在官方页面里生成详情 URL。两处都是量出来的，别改回去：
#   ① 取 route.fullPath，不取 href。href 会过 vue-router 的 cleanPath（把 `//` 压成 `/`），而密文是 base64、
#      本身会出现 `//`：被压掉一个字符的链接打开是空白页。2026-10-11 实测校招 386 条里 6 条、库里社招在招
#      7,481 条里 96 条是这种坏链接。页面自己跳转时写进地址栏的就是 fullPath。
#   ② 用页面自己的 parseQuery 解一遍，解回同一个 id 才算数。解不回的不给 URL（宁可这轮不写，不写坏链接）。
_RESOLVE_DETAIL_URLS_JS = """({path, queries}) => {
    const router = document.querySelector('#app').__vue__.$router;
    const parse = router.options.parseQuery;
    const base = location.origin + location.pathname;
    return queries.map(query => {
        const full = router.resolve({path, query}).route.fullPath;
        const cut = full.indexOf('?');
        let back = null;
        try {
            back = cut < 0 ? null : (parse(full.slice(cut + 1)) || {}).id;
        } catch (e) {
            back = null;
        }
        return [query.id, String(back) === String(query.id) ? base + '#' + full : null];
    });
}"""

_ROUTER_READY_JS = """() => {
    const root = document.querySelector('#app');
    return root && root.__vue__ && root.__vue__.$router;
}"""

# 反方向：把库里详情链接的密文解回岗位 id（社招撤岗核验用，见 crawler/byd_liveness.py）。
# 只认「解得出 15~20 位数字、且再加密回去与原密文逐字相同」的。老的坏链接（上面 ① 说的 `//` 被压掉）
# 试着在某个 `/` 处补回，唯一解才认：补回后的密文解出 id、该 id 加密回来就是补回后的密文、
# 且路由的 href 给它生成的正是库里这条坏链接。最后一条直接问路由，不自己猜 cleanPath 的压法
# （各版本对 `///` 的处理不一样）。
_DECODE_DETAIL_URLS_JS = """({path, encs}) => {
    const router = document.querySelector('#app').__vue__.$router;
    const dec = s => {
        try { const q = router.resolve(path + '?' + s).route.query; return q && q.id != null ? String(q.id) : null; }
        catch (e) { return null; }
    };
    const enc = id => router.resolve({path, query: {id}}).route.fullPath.split('?')[1];
    const viaHref = id => router.resolve({path, query: {id}}).href.split('?')[1];
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

# 社招详情接口回的空骨架里，唯一有值的字段是 collectionStatus（2026-10-11 实测 5,429 个已撤岗 + 300 个伪 id
# 无一例外）；在招岗最少 10 个字段有值（列表 2,078 个 id 逐个问：10~13 个）。多出任何一个别的有值字段都不认作
# 空骨架——接口哪天给骨架加了默认字段，byd_liveness 的阴性对照会当场不过，而不是悄悄判错。
_GONE_ALLOWED_KEYS = frozenset({"collectionStatus"})


def social_detail_state(status_code, body, asked_id: str) -> str:
    """社招 position/queryDetail 的一次回答 → 'live' / 'gone' / 'unknown'。

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


def _unique(values) -> List[str]:
    """去空、去重、保持出现顺序。"""
    seen = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            seen.setdefault(text, None)
    return list(seen)


class _BydPortal(BaseAdapter):
    """两条渠道共用的部分：请求头、逐岗详情并发、让官方页面生成详情 URL。"""

    company_name = "比亚迪"
    DETAIL_ROUTE = ""      # 详情页的前端路由，子类填
    # 详情是公开 httpx 接口（非浏览器、很快）→ 默认覆盖全量列表逐岗补 JD 正文。
    # 旧 DETAIL_CAP=20 只补 20 个 → 其余 ~2000 岗全是无正文薄卡（不进 count_valid_active_jobs）。
    # 快档 daily 仍可用 env CRAWL_DETAIL_CAP=0 跳过逐岗富化（resolve_detail_cap），只抓列表骨架。
    DETAIL_CAP = 6000
    DETAIL_WORKERS = 10  # 单 host(job.byd.com) 并发上限：礼貌 + 防限流
    ROUTE_BATCH_SIZE = 500

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

    def _detail_url_prefix(self) -> str:
        return f"{_PAGE_PREFIX}{self.DETAIL_ROUTE}?"

    def _detail_query(self, job_id: str) -> dict:
        """官方页面跳详情时传给路由的 query，逐字照它自己的写法。"""
        raise NotImplementedError

    def _fetch_one_detail(self, client: httpx.Client, job_id: str) -> dict:
        raise NotImplementedError

    def _evaluate_in_page(self, source_url: str, script: str, args: list) -> list:
        """打开官方页面、等它的 Vue Router 就绪，对 args 里每一项执行一次 script，结果依次拼起来。"""
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
            for arg in args:
                out.extend(page.evaluate(script, arg))
            browser.close()
        return out

    def _batches(self, items: List[str]) -> List[List[str]]:
        return [items[start:start + self.ROUTE_BATCH_SIZE] for start in range(0, len(items), self.ROUTE_BATCH_SIZE)]

    def _generate_detail_urls(self, source_url: str, job_ids: List[str]) -> dict:
        """{job_id: 详情 URL}。只含官方解码器能解回同一个 id 的；解不回的不在返回值里。"""
        if not job_ids:
            return {}
        resolved = self._evaluate_in_page(source_url, _RESOLVE_DETAIL_URLS_JS, [
            {"path": self.DETAIL_ROUTE, "queries": [self._detail_query(i) for i in batch]}
            for batch in self._batches(job_ids)
        ])
        urls = {job_id: url for job_id, url in resolved if url}
        missing = len(job_ids) - len(urls)
        if missing:
            logger.warning(
                "%s: %d/%d 个岗的详情 URL 没通过官方解码器回验，本轮不写这些岗",
                self.name, missing, len(job_ids),
            )
        return urls

    def _fetch_details(self, client: httpx.Client, job_ids: List[str]) -> dict:
        """并发用公开详情接口给全量列表逐岗补 JD 正文。返回 {job_id: detail}。
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


class BydAdapter(_BydPortal):
    name = "byd"
    LIST_API = f"{_API}/position/queryList"
    DETAIL_API = f"{_API}/position/queryDetail"
    DETAIL_ROUTE = "/social/socialPositionDetails"
    # 招聘类型按渠道填，不填部门名：部门名不是招聘类型，normalizer 会改用正文重推（正文有「应届」→ 写成校招），
    # 不带正文的快档抓取又写回部门名，同一行的 job_type 在两种值之间来回变（2026-10-11 实测近 3 天见过的行
    # 全是部门名、1,660 行「校招」全是 4 天以上没见过的）。
    JOB_TYPE = "社招"
    LIST_PAGE_SIZE = 1000
    # 社招撤岗不走 run.py 的 list-absence，走 crawler/byd_liveness.py（不在全量列表 + 详情接口空骨架，双条件）。
    # 列表本身是全集（2026-10-11 全集对拍：库里 7,481 个在招岗，详情在招却不在列表的 0 个），不开 absence 的
    # 原因是它认的是「这一轮没被写库」——列表里有、却被后面的清洗挡掉的行同样没被写库，那不是撤岗。
    supports_absence_liveness = False

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

    def _detail_query(self, job_id: str) -> dict:
        return {"id": job_id}  # 社招列表点进详情只带 id

    def decode_detail_urls(self, source_url: str, jd_urls: List[str]) -> dict:
        """{库里的详情链接: (岗位 id, 修好的链接或 None)}；解不出来的不在返回里。
        修好的链接只在老的坏链接上出现（`//` 被压成 `/`，见 _DECODE_DETAIL_URLS_JS 上方说明）。"""
        prefix = self._detail_url_prefix()
        encs = sorted({u[len(prefix):] for u in jd_urls if (u or "").startswith(prefix)})
        if not encs:
            return {}
        decoded = {}
        for enc, job_id, fixed in self._evaluate_in_page(source_url, _DECODE_DETAIL_URLS_JS, [
                {"path": self.DETAIL_ROUTE, "encs": batch} for batch in self._batches(encs)]):
            if job_id:
                decoded[prefix + enc] = (str(job_id), prefix + fixed if fixed else None)
        return decoded

    def _fetch_one_detail(self, client: httpx.Client, job_id: str) -> dict:
        """单岗 queryDetail（公开 httpx POST）→ data dict；任何网络/解析错误返回空（不阻断整批）。"""
        try:
            response = client.post(self.DETAIL_API, json={"id": job_id, "pageSize": 4})
            response.raise_for_status()
            return (response.json() or {}).get("data") or {}
        except (httpx.HTTPError, ValueError):
            return {}

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        headers = self._headers()
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            list_rows = self._fetch_list_rows(client)
            job_ids = [str(row.get("id")) for row in list_rows]
            detail_urls = self._generate_detail_urls(source_url, job_ids)
            if not detail_urls:  # 一个 URL 都没有就别再打两千次详情接口了
                raise RuntimeError(
                    "byd: official router generated no encrypted detail URLs"
                )

            details = self._fetch_details(client, job_ids)

        prefix = self._detail_url_prefix()
        jobs = []
        for row in list_rows:
            job_id = str(row.get("id") or "").strip()
            detail_url = detail_urls.get(job_id)
            if detail_url and detail_url.startswith(prefix):
                jobs.append({
                    "row": row,
                    "detail": details.get(job_id) or {},
                    "jd_url": detail_url,
                })
        if not jobs:
            raise RuntimeError(
                "byd: official router generated no encrypted detail URLs"
            )
        self.fetch_complete = (
            self.reported_total is not None
            and len(list_rows) >= self.reported_total
            and len(jobs) == len(list_rows)  # 有岗没拿到可用 URL = 这轮没写全
        )
        return json.dumps({"jobs": jobs}, ensure_ascii=False)

    def parse(self, html: str) -> List[RawJob]:
        try:
            rows = (json.loads(html) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        prefix = self._detail_url_prefix()
        jobs = []
        for item in rows:
            detail = item.get("detail") or {}
            row = item.get("row") or {}
            jd_url = str(item.get("jd_url") or "").strip()
            title = str(detail.get("positionName") or row.get("positionName") or "").strip()
            province = str(detail.get("province") or row.get("province") or "").strip()
            city = str(detail.get("city") or row.get("city") or "").strip()
            location = "-".join(part for part in (province, city) if part)
            if not (title and jd_url.startswith(prefix) and is_china_company_location(location)):
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
                job_type=self.JOB_TYPE,
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


# 官网字典（common/queryCodeTree 的 0085 / 0011 / 0010 三棵树，2026-10-11 读取）。
# 0085 里还有 008503 校园大使 / 008504 储干：当天没有对应的投递入口，不认识的性质一律不抓、不猜。
_NATURE_GRADUATE = "008501"    # 应届生
_NATURE_INTERN = "008502"      # 实习生
_KNOWN_NATURES = (_NATURE_GRADUATE, _NATURE_INTERN)
_FLAG_YES, _FLAG_NO = "00111", "00112"   # 字典 0011：是 / 否
_DEGREE_RANK = {"00103": (1, "大专"), "00107": (2, "本科"), "00108": (3, "硕士"), "00109": (4, "博士")}

_SUMMARY_NAME_CAP = 8   # 「岗位方向 / 部门意向」各列前几个；一个岗最多见过 66 个方向，全列会把正文挤出摘要


def _capped(names: List[str], unit: str) -> str:
    if len(names) <= _SUMMARY_NAME_CAP:
        return "、".join(names)
    return "、".join(names[:_SUMMARY_NAME_CAP]) + f" 等 {len(names)} 个{unit}"


def _inner_positions(detail: dict) -> List[dict]:
    return [x for x in (detail.get("positionInfoList") or []) if isinstance(x, dict)]


def _work_places(row: dict, detail: dict) -> List[str]:
    return _unique(re.split(r"[,，/、]", str(detail.get("workPlace") or row.get("workPlace") or "")))


def _degree_names(inner: List[dict]) -> List[str]:
    """这个岗下面各「方向 × 部门」接受的学历，由低到高、去重。不认识的码不算。"""
    found = set()
    for item in inner:
        for code in str(item.get("degree") or "").split(","):
            if code.strip() in _DEGREE_RANK:
                found.add(_DEGREE_RANK[code.strip()])
    return [name for _rank, name in sorted(found)]


def _campus_job_type(nature: str, batch: str) -> str:
    """按渠道填招聘类型。详情页给应届生岗挂「应届生」「2027届」两个标签，实习岗不挂届别
    → 届别只写进校招那一类。"""
    if nature == _NATURE_INTERN:
        return "实习"
    return f"{batch}届校招" if re.fullmatch(r"20\d{2}", batch) else "校招"


def _school_summary(row: dict, detail: dict) -> Optional[str]:
    """校招正文。官网详情页是「先选岗位方向和部门意向，再显示对应的工作职责 / 职位要求」，一个岗下面
    最多见过 72 组；库里一岗一行，所以把方向、部门、地点、学历排在最前，正文按出现顺序接在后面
    （入库只留前 400 字）。段名用官网页面上的原词。"""
    inner = _inner_positions(detail)
    if not inner:
        return None
    parts = []
    directions = _unique(x.get("researchDirection") for x in inner)
    divisions = _unique(x.get("division") for x in inner)
    cities = _work_places(row, detail)
    degrees = _degree_names(inner)
    if directions:
        parts.append(f"【岗位方向】{_capped(directions, '方向')}")
    if divisions:
        parts.append(f"【部门意向】{_capped(divisions, '部门')}")
    if len(cities) > 1:
        parts.append(f"【工作地点】{'、'.join(cities)}")
    if degrees:
        parts.append(f"【学历】{' / '.join(degrees)}")

    # 同一段正文挂在多个「方向 × 部门」下面的只写一遍。
    groups = {}
    for item in inner:
        duty = str(item.get("jobDuty") or "").strip()
        need = str(item.get("jobRequirements") or "").strip()
        if duty or need:
            groups.setdefault((duty, need), []).append(item)
    for (duty, need), items in groups.items():
        if len(groups) > 1:
            head = "｜".join(
                x for x in (
                    "、".join(_unique(i.get("researchDirection") for i in items)),
                    "、".join(_unique(i.get("division") for i in items)),
                ) if x
            )
            if head:
                parts.append(f"【{head}】")
        if duty:
            parts.append(f"【工作职责】\n{duty}")
        if need:
            parts.append(f"【职位要求】\n{need}")
    return "\n\n".join(parts) or None


class BydCampusAdapter(_BydPortal):
    """比亚迪校招门户（job.byd.com 的「校园招聘」）：应届生 + 实习生两个投递入口。

    一行 = 官网校招列表里的一个岗（一个详情页）。「博士生」「外派专项」两个入口是「应届生」按学历 /
    是否外派筛出来的子集（2026-10-11 逐 id 对过：65/65、26/26 都在应届生的 384 个里），不另抓。
    """

    name = "byd_campus"
    ENTRY_API = f"{_API}/postEntryConfig/list"
    LIST_API = f"{_API}/schoolPortal/queryPositionList"
    DETAIL_API = f"{_API}/schoolPortal/queryPosition"
    DETAIL_ROUTE = "/school/schoolPositionDetail"
    LIST_PAGE_SIZE = 1000   # 实测一页能回全（384 / 384）；仍按 totalCount 翻页
    DETAIL_WORKERS = 4
    MAX_LIST_PAGES = 50
    # 校招列表 = 官网「在招职位」的全集（逐入口核对 totalCount，见 fetch），列表里没有的岗在官网也找不到入口。
    # ⚠️ 现在只打印 dry-run 数字、不下架：这个 adapter 只在带浏览器的重档跑，那里没开 LIVENESS_ABSENCE_APPLY，
    #    run.ABSENCE_OBSERVE_DEFAULT 里也有它（新源先观察）。
    # ⚠️ 开落库之前要先想清两件事：某个入口被关掉时它的岗会整批算缺席（实习生入口现在只有 2 个岗，
    #    占全源不到 1%，50% 安全闸拦不住）；入口全关时本轮是 0 岗、run.py 记 empty，根本走不到按缺席下架。
    supports_absence_liveness = True

    def _detail_query(self, job_id: str) -> dict:
        # 列表页点「申请职位」时的原样：{id, abroad: 非外派入口传空串, degree: 入口没限定学历时是 null}。
        return {"id": job_id, "abroad": "", "degree": None}

    @staticmethod
    def _body(response) -> dict:
        response.raise_for_status()
        body = response.json()
        # HTTP 200 + 业务码非 0 / 形状不对 = 接口没按预期工作，必须报错，不能当成「没有岗」。
        if not isinstance(body, dict) or body.get("code") != 0:
            code = body.get("code") if isinstance(body, dict) else type(body).__name__
            raise RuntimeError(f"byd_campus: 接口业务码异常 code={code}")
        return body

    def _fetch_channels(self, client: httpx.Client) -> List[tuple]:
        """开着的投递入口 → [(届别, 招聘性质码)]，去重。入口全关（校招季结束）返回空列表。"""
        entries = self._body(client.get(self.ENTRY_API)).get("data")
        if not isinstance(entries, list):
            raise RuntimeError("byd_campus: 投递入口接口没有返回列表")
        statuses = {str(e.get("status") or "") for e in entries if isinstance(e, dict)}
        if entries and not statuses & {_FLAG_YES, _FLAG_NO}:
            # 有入口、却没有一个的开关值是认识的 = 字典变了，不能读成「入口全关」。
            raise RuntimeError(f"byd_campus: 投递入口的开关值不认识 {sorted(statuses)}")
        channels = {}
        for entry in entries:
            if not isinstance(entry, dict) or str(entry.get("status") or "") != _FLAG_YES:
                continue
            nature = str(entry.get("campusNature") or "").strip()
            if nature not in _KNOWN_NATURES:
                logger.warning("byd_campus: 不认识的招聘性质 %r（入口 %r），不抓",
                               nature, entry.get("postEntryName"))
                continue
            channels.setdefault((str(entry.get("batch") or "").strip(), nature), None)
        if not channels:
            logger.warning("byd_campus: 没有开着的投递入口（接口回了 %d 个入口），本轮 0 岗", len(entries))
        return list(channels)

    def _school_list_payload(self, batch: str, nature: str, page_index: int) -> dict:
        # 与列表页自己发的请求体逐字段相同；abroad / degree 留空 = 不按外派 / 学历筛，取这个入口的全部。
        return {
            "topicCode": "", "batch": batch, "campusNature": nature, "abroad": "", "degree": "",
            "jobType": [], "researchDirection": [], "workPlace": [], "keywords": "",
            "pageSize": self.LIST_PAGE_SIZE, "pageIndex": page_index,
        }

    def _fetch_channel_rows(self, client: httpx.Client, batch: str, nature: str) -> tuple:
        """一个入口的全部岗 → ({id: row}, 官网自报总数)。首页失败抛错；后续页失败保留已抓的。"""
        rows_by_id: Dict[str, dict] = {}
        total = 0
        for page_index in range(1, self.MAX_LIST_PAGES + 1):
            try:
                body = self._body(client.post(
                    self.LIST_API, json=self._school_list_payload(batch, nature, page_index)))
            except Exception as exc:
                if page_index == 1:
                    raise
                logger.warning("byd_campus: 入口 %s/%s 第 %d 页失败，保留已抓 %d 条：%s",
                               batch, nature, page_index, len(rows_by_id), exc_brief(exc))
                break
            rows = body.get("data")
            if page_index == 1:
                page = body.get("page")
                reported = _int_or_none(page.get("totalCount")) if isinstance(page, dict) else None
                if reported is None or not isinstance(rows, list):
                    raise RuntimeError("byd_campus: 列表接口没有返回 data / page.totalCount")
                total = reported
            before = len(rows_by_id)
            for row in rows if isinstance(rows, list) else []:
                job_id = str((row or {}).get("id") or "").strip()
                if job_id:
                    rows_by_id.setdefault(job_id, row)
            if len(rows_by_id) >= total or len(rows_by_id) == before:  # 抓够了 / 这一页没带来新岗
                break
        if total and not rows_by_id:
            # 自报有岗、却一行带 id 的都没有 = 行的形状变了。安静返回 0 行会被记成「这个入口没有岗」。
            raise RuntimeError(f"byd_campus: 入口 {batch}/{nature} 自报 {total} 个岗，列表里一行都认不出")
        return rows_by_id, total

    def _fetch_one_detail(self, client: httpx.Client, job_id: str) -> dict:
        try:
            body = self._body(client.get(
                self.DETAIL_API, params={"id": job_id, "abroad": "", "degree": ""}))
        except (httpx.HTTPError, ValueError, RuntimeError):
            return {}
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def fetch(self, source_url: str) -> str:
        self.reported_total = None
        self.fetch_complete = False
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers()) as client:
            rows_by_id: Dict[str, dict] = {}
            reported = 0
            lists_complete = True
            for batch, nature in self._fetch_channels(client):
                rows, total = self._fetch_channel_rows(client, batch, nature)
                reported += total
                # 逐个入口判「抓到它自报的总数了吗」：入口之间若有重叠，拿总和当分母会恒判没抓全。
                lists_complete = lists_complete and len(rows) >= total
                for job_id, row in rows.items():
                    rows_by_id.setdefault(job_id, row)
            self.reported_total = reported
            job_ids = list(rows_by_id)
            detail_urls = self._generate_detail_urls(source_url, job_ids)
            if job_ids and not detail_urls:
                raise RuntimeError("byd_campus: official router generated no encrypted detail URLs")
            listed = [job_id for job_id in job_ids if job_id in detail_urls]
            details = self._fetch_details(client, listed)
            if listed and resolve_detail_cap(self.DETAIL_CAP) and not details:
                # 重档要补正文却一个详情都没取到 = 详情接口整个坏了。只写标题会变成一批没有正文的薄卡、状态还是成功。
                raise RuntimeError(f"byd_campus: {len(listed)} 个岗的详情一个都没取到")

        jobs = [
            {"row": rows_by_id[job_id], "detail": details.get(job_id) or {}, "jd_url": detail_urls[job_id]}
            for job_id in listed
        ]
        writable = sum(1 for item in jobs if self._raw_job(item) is not None)
        if jobs and not writable:
            # 列表有行、URL 也有，却一行都映射不出来（字段改名 / URL 形状变了）：必须记失败，不能记成空源。
            raise RuntimeError(f"byd_campus: 列表 {len(jobs)} 行一行都映射不出岗位")
        # 列表里的每个岗都写得进库才算抓全：少写了一个还在列表里的岗，按缺席下架就会把它当成撤岗。
        self.fetch_complete = lists_complete and writable == len(job_ids)
        return json.dumps({"jobs": jobs}, ensure_ascii=False)

    def _raw_job(self, item: dict) -> Optional[RawJob]:
        row = item.get("row") or {}
        detail = item.get("detail") or {}
        jd_url = str(item.get("jd_url") or "").strip()
        title = str(detail.get("jobName") or row.get("jobName") or "").strip()
        nature = str(row.get("campusNature") or "").strip()
        # 多地岗的地点取官网列出的第一个在华城市，全部城市写进正文。整串交给 normalizer 只会被别名表挑走
        # 其中一个，挑哪个不可预期（lenovo / huawei_campus / sf_express_campus 也是取第一个）。
        location = next((c for c in _work_places(row, detail) if is_china_company_location(c)), "")
        if not (
            title
            and nature in _KNOWN_NATURES
            and jd_url.startswith(self._detail_url_prefix())
            and location
        ):
            return None
        degrees = _degree_names(_inner_positions(detail))
        return RawJob(
            company=self.company_name,
            title=title,
            location=location,
            job_type=_campus_job_type(nature, str(row.get("batch") or "").strip()),
            summary=_school_summary(row, detail),
            jd_url=jd_url,
            apply_url=jd_url,
            # 列表里唯一的日期在页面上叫「更新于」，不是发布日 → 不填 posted_at。
            experience=None if nature == _NATURE_INTERN else "应届/不限",
            education=degrees[0] if degrees else None,  # 各方向里要求最低的那一档
        )

    def parse(self, html: str) -> List[RawJob]:
        try:
            items = (json.loads(html) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        return [job for job in (self._raw_job(item) for item in items) if job is not None]
