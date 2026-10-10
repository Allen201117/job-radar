"""国聘（iguopin.com）通用企业岗位适配器，纯 httpx。

source_url 约定：``https://www.iguopin.com/job?company={公司全称的 URL 编码}``。
可选 ``&nature={code}``：按国聘自己的「职位性质」筛（``115xW5oQ`` = 应届生 / 校招，取自
xiaoyuan.iguopin.com 「应届生职位 → 更多」的真实跳转 ``/job?nature=115xW5oQ&nature_cn=应届生``，
列表接口的真实请求体是 ``search.nature: ["115xW5oQ"]``（数组，2026-09-17 浏览器 hook 抓到；传字符串返 total=None）。
同一集团的社招 + 校招是两条源：关键词搜索单次封顶 400 条、逐岗核验封顶 300，大集团的校招岗
会被社招挤出窗口（国家电网 / 中国石化「全部」400 条里应届生就占满 400）。加 ``&channel=campus``
只是让 ``sources.board`` 派生成 campus（classify_source_board 认 URL 里的 campus 令牌），接口不读它。
``company`` 只是本适配器读取的检索词（也兼容 ``keyword``），不是国聘列表页实际
查询串；fetch 会将它传给国聘公开搜索 API。一个源对应一个集团检索词，结果会保留
名称包含该词的在招单位/子公司岗位。

公开链路（2026-07-17 浏览器抓包验证）：
1. POST https://gp-api.iguopin.com/api/jobs/v1/recom-job
   {"search":{"page", "page_size", "keyword"}, "recom":{...}} -> data.list / data.total
2. GET https://gp-api.iguopin.com/api/jobs/v1/info?id={job_id} -> data.contents
3. 稳定单岗页 https://www.iguopin.com/job/detail?id={job_id}

列表的 ``contents`` 常已有正文，但仍逐岗调公开详情接口并仅产出详情读取成功的岗位：
这样 jd_url 的单岗页面和正文都经过真实核验，绝不拿列表链接冒充职位详情。
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from company_name_match import company_name_matches

from .base import BaseAdapter, PageResult, RawJob, paginate_all, resolve_detail_cap


_LIST_API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
_DETAIL_API = "https://gp-api.iguopin.com/api/jobs/v1/info"
_COMPANY_HOME_API = "https://gp-api.iguopin.com/api/company/index/v1/home"
_CHILDREN_API = "https://gp-api.iguopin.com/api/company/index/v1/children-list"
_DETAIL_PAGE = "https://www.iguopin.com/job/detail?id={id}"
_PAGE_SIZE = 20  # 网站自己的列表页大小；与公开 API 实际响应一致
_GROUP_CHILD_CAP = 60
_GROUP_ANCHOR_TRIES = 5   # 最多拿前 5 个不同公司去问集团；模糊搜索的头几行就够定锚，再多是白烧
_GROUP_CHILD_PAGE_CAP = 2
_DETAIL_WORKERS = 3

# 公司主页接口（归属核验的唯一依据）会失败，而且不少见。2026-10-10 实测：约 10 秒后回 HTTP 503，
# 单发 4 次里 1~2 次、3 并发连打同一家 40 次里 16 次、批量复核 609 家时 55 / 1,269 次。
# → 单次失败不能当结论，重试；重试用尽仍问不到 = 「本轮核不了」，那一行**不写**（见 _GroupGate）。
_HOME_TRIES = 3
_HOME_RETRY_SLEEP = 1.0   # 秒，第 n 次重试前等 n 倍；失败本身已经让对方喘了 10 秒，不必更长
# 国聘的明确答复「未找到对应企业或该企业审核不通过或异常」。这是**定论**不是抖动：每次问都是它。
_HOME_NOT_FOUND_CODES = frozenset({2204})
# 一条源里核不了的公司占到这个比例 = 主页接口这一轮整体不可用 → 整源记 failed、库里一行不动。
# 取 50% 与仓库里其它「本轮结果不可信就整轮放弃」的闸同档（enrich_backlog.EXPIRE_RATIO_GUARD、
# sweep_absent_jobs 的 max_expire_fraction、announcements/verify 的下架比例闸）。
_UNVERIFIED_ABORT_RATIO = 0.5
# 并发预热按这么多家一批来问；**整整一批一家都没问到** = 接口这会儿不可用，当场放弃这条源。
# 接口大面积失败时每家要白等 3×10 秒，一条源两三百家全问完再放弃就是几十分钟，而国聘几十条源同主机
# 一队串行跑在同一个分片里。单家重试后仍失败的概率实测约 6%，连续 24 家全失败只可能是接口挂了。
# ⚠️ 预热阶段不许看「问不到的占比」：它只问进程级缓存里没有的公司，后面的源里剩下的恰恰是
# 上一条源没问到的那几家，比例天然偏高（118 家已缓存 + 2 家问不到 会被算成 2/2）。比例只在全体公司上算。
_PREFETCH_CHUNK = 24

# 「这家公司在国聘口径下属于哪个集团」是**全局事实**，与是哪条源问的无关 → 进程级缓存。
# 为什么值得：单源实测（中国建筑校招源，2026-09-17）墙钟 106s 里 **56.6s（53%）花在 251 次
# company/index/v1/home 上**，而国聘 45 条源（28 社招 + 17 校招）同主机一队串行跑在同一个进程里，
# 同一集团的社招源与校招源问的是同一批 company_id，子公司展开出来的公司更是反复出现。
# ⚠️ 只缓存**定论**（"xxx" 有集团 / "" 查到了没有集团）；请求失败的 None 不缓存，
#    否则一次网络抖动会把「暂时不知道」冻成整晚的结论（`_company_group_id` 的三态语义见其 docstring）。
# ⚠️ 必须是进程级 + 加锁：并发档里 ADAPTERS 是**跨线程共享的单例**（见 run.py 的注释），
#    实例字段会被别的线程覆写，而这份缓存按 company_id 存全局事实，跨线程共享是安全的。
_GROUP_ID_CACHE: dict = {}
# 定锚用的 (group_id, 集团简称, 集团全称)，同样按 company_id 存，共用 _GROUP_ID_LOCK。
_GROUP_INFO_CACHE: dict = {}
_GROUP_ID_LOCK = threading.Lock()

# 同一个 job_id 在一晚里会被多条源抓到：同集团的社招源与校招源是同一个池子的两个视图
# （校招源 = 社招源加 nature 筛），子公司展开还会让兄弟集团的源撞上同一批岗。
# 实测中国建筑：社招 173 次详情 / 校招 124 次，且校招那批 job_id 基本是社招那批的子集。
# ⚠️ 只在**本进程本轮**内复用：详情调用同时充当「这个岗此刻真实存在」的核验，
#    跨轮/跨夜复用就等于拿旧证据放行，那是 `_detail_verified` 的语义红线。
# ⚠️ 有上限、超了就整体清空（FIFO 太重，这里只求别把 runner 内存吃光）：
#    正文动辄几 KB，45 条源 × 400 条不设限是上百 MB。
_DETAIL_CACHE: dict = {}
_DETAIL_CACHE_LOCK = threading.Lock()
_DETAIL_CACHE_MAX = 4000


def reset_process_caches() -> None:
    """清空两个进程级缓存。生产代码不调用（一个进程 = 一轮抓取，缓存就该活满整轮）；
    **单测必须在每个用例前调用**，否则上一个用例缓存下来的 job_id/company_id 会让下一个用例
    少发请求 —— 加缓存时就是这么被 test_fetch_verifies_group_child... 当场抓到的。"""
    with _GROUP_ID_LOCK:
        _GROUP_ID_CACHE.clear()
        _GROUP_INFO_CACHE.clear()
    with _DETAIL_CACHE_LOCK:
        _DETAIL_CACHE.clear()


class IguopinAdapter(BaseAdapter):
    name = "iguopin"
    max_pages = 200  # 20/页，单一集团检索词最多保护到 4,000 条
    _DETAIL_CAP = 300

    _nature: tuple = ()
    _last_group_name: str = ""   # _group_info 顺手记下集团全称，供锚点核名用（见 _expand_group_children）

    def should_skip(self, source_url: str):
        if resolve_detail_cap(self._DETAIL_CAP) == 0:
            print("[iguopin] 需详情核验、快档 cap=0 → 跳过本轮")
            return "iguopin requires detail verification; CRAWL_DETAIL_CAP=0"
        return None  # JSON POST 不适合 HEAD；由首个 GET/POST 返回真实错误

    def fetch(self, source_url: str) -> str:
        keyword = _company_keyword(source_url)
        if not keyword:
            raise ValueError("iguopin source_url must include ?company={company name}")

        self.reported_total = None
        self.fetch_complete = False
        self.coverage_stop_reason = None   # 同一实例被复用时（probe / 单测），上一条源的停因不许带到这一条
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Origin": "https://www.iguopin.com",
            "Referer": "https://www.iguopin.com/",
        }

        nature = _nature_codes(source_url)
        self._nature = nature   # 集团子公司展开沿用同一性质筛，否则校招源会把子公司的社招岗抓进来
        rows, total, complete = self._fetch_rows(keyword, headers, self.max_pages, nature=nature)
        self.reported_total = total
        self.fetch_complete = complete
        # 集团锚点必须是「核过名的我们的公司」+「集团简称也对得上」，缺一个都不展开（见方法注释）。
        group_short_name, group_id = self._expand_group_children(
            rows, headers, tokens=[t for t in (_match_token(source_url), keyword) if t])
        group_ok = self._group_membership_checker(group_id, headers) if group_id else None
        # 可选 match token：国聘关键词搜索是模糊匹配（搜「中国建筑」会夹带无关公司岗），
        # 带 &match={token} 时只放行 company_name 含 token 的岗，保「按公司精准抓取」。
        match = _match_token(source_url)
        listed = len(rows)
        # 即使没配 match，集团展开进来的行也要过归属核验——旁路必须堵死。
        if match or group_ok:
            if group_ok:
                self._prefetch_group_ids(rows, group_ok, keyword)
            rows[:] = [row for row in rows if _row_passes_match(row, match, group_ok)]
            if group_ok:
                self._account_unverified(group_ok, keyword)
        # 归属核验只有 fetch 做得了（要联网查国聘的集团口径），parse 里没有这个能力。
        # 打个标把结论带下去，否则 parse 的那道复查会按「名字核名」把真子公司再毙一次
        # （鼎和财产保险/国网江苏 名字里都不含集团名）。
        for row in rows:
            if isinstance(row, dict):
                row["_attribution_ok"] = True
        verified = self._enrich_details(rows, headers)
        print(f"[iguopin] keyword={keyword} listed={listed} matched={len(rows)} verified={verified}")
        return json.dumps({
            "list": rows,
            "_match": match,
            "_group_short_name": group_short_name,
        }, ensure_ascii=False)

    def _fetch_rows(self, keyword: str, headers: dict, max_pages: int, nature=None):
        def fetch_page(page: int) -> PageResult:
            search = {"page": page, "page_size": _PAGE_SIZE, "keyword": keyword}
            if nature:
                search["nature"] = list(nature)   # 必须是数组：字符串会让接口返 total=None、list 空
            payload = {
                "search": search,
                "recom": {"update_time": True, "company_nature": True, "hot_job": True},
            }
            response = httpx.post(_LIST_API, json=payload, headers=headers,
                                  timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
            body = response.json() or {}
            if body.get("code") != 200:
                raise RuntimeError(f"iguopin list API: {body.get('msg') or body.get('code')}")
            data = body.get("data") or {}
            total = data.get("total")
            return PageResult(items=data.get("list") or [],
                              total=total if isinstance(total, int) else None)

        return paginate_all(
            fetch_page, page_size=_PAGE_SIZE, first_page=1, max_pages=max_pages,
            label=f"iguopin:{keyword}")

    def _expand_group_children(self, rows: List[dict], headers: dict, tokens=()):
        """返回 (group_short_name, group_id)；集团元数据/子公司列表任一异常均静默回退原关键词结果。

        ⚠️ 锚点不能是「搜索结果第一行」（2026-09-17 立）。国聘关键词搜索是模糊的，第一行是谁取决于
        排序：同一个「华润置地」源，社招排序第一行碰巧是华润的公司，加上 nature=应届生 后第一行变成
        中铝瑞闽 → 集团被认成「中国铝业」→ 整源 40 家中铝子公司挂到华润置地名下。同批实测还有
        百胜中国→中国联通、中海油→国机集团、京东方→「宁波吉德电器（京东方向）」。
        判据只有一条：**集团简称本身必须过核名**（`company_name_matches(集团简称, match 或 keyword)`）。
        不能拿锚点行自己的名字当判据——「国网国际融资租赁」名字里没有「国家电网」却是真子公司，
        「中国建筑技术集团」名字以「中国建筑」开头却属于中国建研院：名字像不像和东家是谁是两回事。
        所以按顺序试前几行（各自去查一次集团），第一个集团简称对得上的才当锚点，都对不上就不展开。
        简称对不上时再看**集团全称**（`group_name`，国聘公司主页接口自带），但全称的判据更严：
        去掉 token 之后**只能剩公司后缀词**（集团/股份/有限/责任/公司/控股）。中海油：「中国海洋石油集团有限公司」
        − keyword「中国海洋石油」= 「集团有限公司」✓；中国能建：「中国能源建设股份有限公司」✓；
        而「中国建筑科学研究院有限公司」− 「中国建筑」= 「科学研究院有限公司」✗ —— 建研院不是中国建筑，
        2026-09-17 第一版全称回退用 company_name_matches 就把它又放了回去（社招源对拍当场抓到）。
        """
        tokens = [str(t or "").strip() for t in (tokens or ()) if str(t or "").strip()]

        def _passes(name: str) -> bool:
            return (not tokens) or any(company_name_matches(name, tok) for tok in tokens)

        candidates: List[str] = []
        for row in rows:
            cid = str(row.get("company_id") or "").strip() if isinstance(row, dict) else ""
            if cid and cid not in candidates:
                candidates.append(cid)
            if len(candidates) >= _GROUP_ANCHOR_TRIES:
                break
        if not candidates:
            return None, ""
        group_id, group_short_name = "", ""
        try:
            for cid in candidates:
                self._last_group_name = ""
                gid, short = self._group_info(cid, headers)
                full = getattr(self, "_last_group_name", "") or ""
                if gid and short and (_passes(short) or (full and any(_full_name_is_same_entity(full, t) for t in tokens))):
                    group_id, group_short_name = gid, short
                    break
                print(f"[iguopin] 集团「{short}」/「{full}」与 {tokens} 对不上，换下一个锚点")
            if not group_id:
                return None, ""
            children = self._group_children(group_id, headers)
            if not children:
                return group_short_name, group_id
        except Exception:
            return None, ""

        # 默认 60 家、每家最多 2 页（20 条/页）：国网实测 51 家可全覆盖，同时把集团展开
        # 控制在最多 120 次列表调用。两个 cap 均可由环境变量下调/上调，不影响原关键词路径。
        child_cap = _env_cap("IGUOPIN_GROUP_CHILD_CAP", _GROUP_CHILD_CAP)
        page_cap = _env_cap("IGUOPIN_GROUP_PAGE_CAP", _GROUP_CHILD_PAGE_CAP)
        expanded = []
        for child_name in children[:child_cap]:
            try:
                child_rows, _, _ = self._fetch_rows(child_name, headers, page_cap, nature=self._nature)
            except Exception:
                continue
            for row in child_rows:
                if isinstance(row, dict):
                    # 记**是哪个子公司名把这条搜回来的**，而不是只记一个 True。
                    # 下游要用它逐条核名——国聘的关键词搜索是模糊的，拿子公司名去搜同样会
                    # 捞回不相干的公司（见 _row_passes_match 的注释）。
                    row["_group_child"] = child_name
            expanded.extend(child_rows)
        rows[:] = _dedupe_rows(rows + expanded)
        return group_short_name, group_id

    def _company_group_id(self, company_id: str, headers: dict):
        """查这家公司在国聘口径下的集团 id。三种返回值，语义必须分开：
          · "xxx" = 有集团；  · ""  = **查到了、但它没有集团**（独立公司，定论）；
          · None = 请求/解析失败（暂时不知道）。
        把「没有集团」和「查不到」混成一种，正是张冠李戴修不掉的原因：
        中国（海南）改革发展研究院在国聘上写着「民营企业、无集团」，
        当成「查不到 → 保守放行」就永远挡不住它。
        进程级缓存只存前两种（定论），None 每次重查——见 `_GROUP_ID_CACHE` 的注释。
        """
        cid = str(company_id or "").strip()
        with _GROUP_ID_LOCK:
            if cid in _GROUP_ID_CACHE:
                return _GROUP_ID_CACHE[cid]
        found = self._fetch_company_group_id(cid, headers)
        if found is not None:
            with _GROUP_ID_LOCK:
                _GROUP_ID_CACHE[cid] = found
        return found

    def _prefetch_group_ids(self, rows, gate: "_GroupGate", keyword: str = "") -> None:
        """把本源要问的 company_id 先并发问掉，再走串行的逐行核验。

        为什么要这一步：核验本身必须逐行串行（判据要按行用），但**取事实**可以并发。
        实测（中国建筑校招源）251 次 company home 串行 56.6s，是单源墙钟 106s 的 53%。
        并发度沿用 `_DETAIL_WORKERS`（逐岗详情同样对 gp-api 开 3 路，是已在线上跑了两个月的档位），
        **不额外抬高对国聘的并发**。
        结论记在 `gate` 上（含「本轮核不了」）：问不到的公司不许在逐行核验时再串行重问一遍 ——
        主页接口失败一次要等约 10 秒，重试已经在 `_company_home` 里做过了。"""
        seen, todo = set(), []
        for row in rows or []:
            cid = _row_company_id(row)
            if not cid or cid in seen:
                continue
            seen.add(cid)
            with _GROUP_ID_LOCK:
                if cid in _GROUP_ID_CACHE:
                    continue
            todo.append(cid)
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            for start in range(0, len(todo), _PREFETCH_CHUNK):
                chunk = todo[start:start + _PREFETCH_CHUNK]
                verdicts = list(executor.map(gate.verdict, chunk))
                if len(chunk) == _PREFETCH_CHUNK and all(verdict is None for verdict in verdicts):
                    raise RuntimeError(f"iguopin 归属核验：连续 {_PREFETCH_CHUNK} 家公司的集团在国聘都问不到"
                                       f"（公司主页接口不可用），整源放弃本轮（keyword={keyword}）")

    def _company_home(self, company_id: str, headers: dict) -> dict:
        """问国聘「这家公司是谁」。三种结果，调用方必须分开处理：
          · company_info（dict，非空）= 问到了；
          · {} = 国聘明确答复没有这家公司（`_HOME_NOT_FOUND_CODES`），或答复里公司信息是空的（定论）；
          · 抛异常 = 重试用尽仍问不到。**它不是任何一种答复**，不许当成「有」也不许当成「没有」。
        重试的理由见 `_HOME_TRIES` 的注释。"""
        last: Exception = RuntimeError("iguopin company home: not attempted")
        for attempt in range(_HOME_TRIES):
            if attempt:
                time.sleep(_HOME_RETRY_SLEEP * attempt)
            try:
                response = httpx.get(_COMPANY_HOME_API, params={"company_id": company_id},
                                     headers=headers, timeout=self.timeout, follow_redirects=True)
                response.raise_for_status()
                body = response.json() or {}
                code = body.get("code")
                if code in _HOME_NOT_FOUND_CODES:
                    return {}
                info = (body.get("data") or {}).get("company_info") if code == 200 else None
                if isinstance(info, dict):
                    return info
                last = ValueError(f"iguopin company home response missing company_info (code={code})")
            except Exception as exc:  # noqa: BLE001 —— 503 / 超时 / 非 JSON 一律重试
                last = exc
        raise last

    def _fetch_company_group_id(self, company_id: str, headers: dict):
        try:
            info = self._company_home(company_id, headers)
        except Exception:
            return None                # 问不到 ≠ 没有集团；由 _GroupGate 记成「本轮核不了」
        return group_id_of(info, company_id)   # 可能是 ""，那是「无集团」的定论

    def _group_membership_checker(self, group_id: str, headers: dict) -> "_GroupGate":
        """返回 `gate(row) -> bool`：这条岗的公司在**国聘自己的口径**下是否真属于本集团。

        判据是 group_id，不是名字——名字核不住：鼎和财产保险是南方电网真子公司、
        名字里却没有「南方电网」；反过来「中国（海南）改革发展研究院」名字里有「海南」，
        被「海南电网有限责任公司」这个关键词搜了回来，实际是民营企业。
        一家公司只查一次（gate 自己记本轮结论 + 进程级 `_GROUP_ID_CACHE`：
        同一集团的社招源与校招源问的是同一批公司，45 条源跑在同一个进程里，跨源复用是白捡的）。
        失败语义见 `_GroupGate`。
        """
        return _GroupGate(group_id, lambda cid: self._company_group_id(cid, headers))

    def _account_unverified(self, gate: "_GroupGate", keyword: str) -> None:
        """核不了的行已经被 gate 拦下（没写）。这里只负责**让这件事看得见**（此时 gate 已看过全体公司）：
          · 核不了的占到一半 → 抛错，整源记 failed、库里一行不动。主页接口整体不可用时，
            「放行全部」是 2026-10-10 那次事故，「安静地写剩下几条还报 success」是绿灯零产出；
          · 少数核不了 → 本轮记「没写全」（停因进 crawl_runs），其余行照常入库。"""
        unverified, checked = len(gate.unverified), len(gate.checked)
        if not unverified:
            return
        note = (f"iguopin 归属核验：{unverified}/{checked} 家公司的集团在国聘问不到"
                f"（公司主页接口重试 {_HOME_TRIES} 次仍失败，或行里没有公司 id），这些公司的岗本轮不写")
        if unverified >= checked * _UNVERIFIED_ABORT_RATIO:
            raise RuntimeError(f"{note}；核不了的占比过高，整源放弃本轮（keyword={keyword}）")
        print(f"::warning::[iguopin] keyword={keyword} {note}")
        if self.fetch_complete:
            # 只在「列表本来翻完了」时改写：分页自己没翻完的轮次保持原状，
            # 否则 ops_watchdog 规则 G 会按这个停因把一个真缺口从榜上摘走。
            self.fetch_complete = False
            self.coverage_stop_reason = "attribution_unverified"

    def _group_info(self, company_id: str, headers: dict):
        """定锚：这家公司的集团 id / 简称 / 全称。同样是全局事实 → 进程级缓存
        （社招源与校招源是同一个集团的两个视图，锚点行往往就是同一家公司）。
        `_last_group_name` 是**实例字段**，命中缓存时也必须照样写回 —— 调用方紧接着就读它。"""
        cid = str(company_id or "").strip()
        with _GROUP_ID_LOCK:
            hit = _GROUP_INFO_CACHE.get(cid)
        if hit is not None:
            group_id, group_short_name, self._last_group_name = hit
            return group_id, group_short_name
        info = self._company_home(company_id, headers)   # 带重试；问不到会抛，由调用方回退到不展开
        if not info:
            raise ValueError("iguopin company home response missing company_info")

        group_id = group_id_of(info, company_id)
        # 集团 id 和集团名必须指同一个实体：自己就是自己的集团 → 用自己的名字，否则用上级集团的名字。
        # （旧写法只要 classify 是「央企(集团)」就用自己的名字，哪怕 group_id 指着别人 ——
        #   国聘上真有这种公司，锚在它身上会给上级集团的所有子公司贴它的简称。）
        if group_id == str(info.get("id") or company_id).strip():
            group_short_name = _text(info.get("short_name"))
            self._last_group_name = _text(info.get("name"))
        else:
            group_short_name = _text(info.get("group_short_name"))
            self._last_group_name = _text(info.get("group_name"))
        if not group_id or not group_short_name:
            raise ValueError("iguopin company home response missing group metadata")
        # 定锚这一跳问的也是 company home，结论与 `_company_group_id` 同口径（同一个 group_id_of）
        # → 顺手灌进缓存。每条源最多试 5 个锚点，45 条源就是最多 225 次可以省掉的重复请求。
        with _GROUP_ID_LOCK:
            _GROUP_ID_CACHE[cid] = group_id
            _GROUP_INFO_CACHE[cid] = (group_id, group_short_name, self._last_group_name)
        return group_id, group_short_name

    def _group_children(self, group_id: str, headers: dict) -> List[str]:
        response = httpx.get(_CHILDREN_API, params={"company_id": group_id}, headers=headers,
                             timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        body = response.json() or {}
        data = body.get("data") if body.get("code") == 200 else None
        if not isinstance(data, list):
            raise ValueError("iguopin children response missing list")
        names = []
        for item in data:
            name = _text(item.get("name") or item.get("company_name")) if isinstance(item, dict) else None
            if name and name not in names:
                names.append(name)
        return names

    def _enrich_details(self, rows: List[dict], headers: dict) -> int:
        """读取每条公开详情；只有确认存在的逐岗详情才在 parse 中放行。
        本进程本轮已核过的 job_id 直接复用（见 `_DETAIL_CACHE` 注释）。"""
        def fetch_detail(job_id: str):
            with _DETAIL_CACHE_LOCK:
                if job_id in _DETAIL_CACHE:
                    return _DETAIL_CACHE[job_id]
            try:
                response = httpx.get(_DETAIL_API, params={"id": job_id}, headers=headers,
                                     timeout=self.timeout, follow_redirects=True)
                if response.status_code >= 300:
                    return None
                body = response.json() or {}
                detail = body.get("data") if body.get("code") == 200 else None
                if not isinstance(detail, dict) or str(detail.get("job_id") or "") != job_id:
                    return None
            except (httpx.HTTPError, ValueError, TypeError):
                return None
            with _DETAIL_CACHE_LOCK:
                if len(_DETAIL_CACHE) >= _DETAIL_CACHE_MAX:
                    _DETAIL_CACHE.clear()
                _DETAIL_CACHE[job_id] = detail
            return detail

        def enrich_row(row: dict) -> bool:
            job_id = str(row.get("job_id") or "").strip()
            if not job_id:
                return False
            detail = fetch_detail(job_id)
            if detail is None:
                return False
            row["_detail_verified"] = True
            row["_jd"] = detail.get("contents") or row.get("contents")
            # Detail 是 title/source of truth，列表的瞬时卡片字段不覆盖它。
            for key in ("job_name", "company_name", "district_list", "education_cn",
                        "experience_cn", "end_time", "recruitment_type_cn"):
                if detail.get(key) not in (None, ""):
                    row[key] = detail[key]
            return True

        detail_rows = [row for row in rows[:resolve_detail_cap(self._DETAIL_CAP)]
                       if isinstance(row, dict)]
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as executor:
            return sum(executor.map(enrich_row, detail_rows))

    def parse(self, html: str) -> List[RawJob]:
        try:
            data = json.loads(html)
        except (json.JSONDecodeError, TypeError):
            return []
        rows = data.get("list") if isinstance(data, dict) else None
        match = (data.get("_match") if isinstance(data, dict) else None) or ""
        group_short_name = (data.get("_group_short_name") if isinstance(data, dict) else None) or ""
        out: List[RawJob] = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("_detail_verified"):
                continue
            job_id = str(row.get("job_id") or "").strip()
            title = str(row.get("job_name") or "").strip()
            if not job_id or not title:
                continue
            company = str(row.get("company_name") or "").strip()
            # fetch 已按国聘集团口径核过归属的行直接放行；没核过的（非本 adapter 产出的
            # payload）仍走严格核名，防模糊搜索夹带的同名子串张冠李戴。
            if not row.get("_attribution_ok") and not _row_passes_match(row, match):
                continue
            company = _company_with_group_brand(company, group_short_name)
            detail_url = _DETAIL_PAGE.format(id=job_id)
            out.append(RawJob(
                company=company,
                title=title,
                location=_location(row.get("district_list")),
                job_type=_text(row.get("recruitment_type_cn")),
                summary=_text(row.get("_jd")),
                jd_url=detail_url,
                apply_url=detail_url,
                salary_text=_salary_text(row),
                posted_at=_date(row.get("refresh_time") or row.get("update_time")),
                experience=_text(row.get("experience_cn")),
                education=_text(row.get("education_cn")),
                deadline=_text(row.get("end_time")),
            ))
        return out


def group_id_of(info: dict, company_id: str = "") -> str:
    """国聘公司主页答复 → 这家公司的集团 id。"" = 没有集团（含国聘不认这家公司）。
    adapter 的归属门、定锚和存量复核工具共用这一份，三处口径不许分叉。"""
    if not info:
        return ""
    group_id = str(info.get("group_id") or "").strip()
    if not group_id and info.get("classify_cn") == "央企(集团)":
        return str(info.get("id") or company_id).strip()   # 集团本体，自己就是自己的集团
    return group_id


def _row_company_id(row) -> str:
    return str(row.get("company_id") or "").strip() if isinstance(row, dict) else ""


class _GroupGate:
    """一条集团源本轮的归属门：`gate(row)` 只在国聘**明确说**这家公司属于本集团时放行。

    一家公司的结论有三种，语义必须分开（混成两种就是事故）：
      · True  = 国聘说它的 group_id 就是本集团 → 放行；
      · False = 国聘说它属于别的集团 / 自己就是自己的集团 / 国聘不认这家公司 → **定论，拒**；
      · None  = 问不到（重试用尽），或这一行根本没带 company_id → **本轮不写**，记进 `unverified`，
                下一轮重查。结论不进进程级缓存，但同一轮里不重问。

    🚫 None 不许放行（2026-10-10 立）。旧实现是「请求失败 → 放行，下轮重查」，理由是别因为对方接口
    抖一下丢掉整源真岗。实测它丢不掉真岗（不写 ≠ 删，库里已有的行不动），却真的把假岗放了进来：
    「中国人民解放军空军（中国石油）」65 岗、「赞比亚谦比希湿法冶炼有限公司（比亚迪股份有限公司）」……
    当天全量复核 609 家 / 4,199 岗：42 家 / 178 岗挂错，其中 164 岗是 10-09、10-10 两晚进来的；
    拿旧代码真跑一条源（中国石油），放行的 43 行里 40 行是「问不到」放进来的。而且「下轮重查」救不回来：
    下一轮查成功了只是这一行不再被刷新，已经写进去的旧行没有任何机制撤掉。
    归属是红线：核不了的就不写，宁可这一轮少几行。
    """

    def __init__(self, group_id: str, lookup_group_id):
        self._group_id = str(group_id)
        self._lookup_group_id = lookup_group_id     # cid -> "xxx" / ""（无集团，定论）/ None（问不到）
        self._verdicts: dict = {}

    def verdict(self, company_id: str) -> Optional[bool]:
        cid = str(company_id or "").strip()
        if cid not in self._verdicts:
            found = self._lookup_group_id(cid) if cid else None
            self._verdicts[cid] = None if found is None else (str(found) == self._group_id)
        return self._verdicts[cid]

    def __call__(self, row) -> bool:
        return self.verdict(_row_company_id(row)) is True

    @property
    def checked(self) -> set:
        return set(self._verdicts)

    @property
    def unverified(self) -> set:
        return {cid for cid, verdict in self._verdicts.items() if verdict is None}


def _company_keyword(source_url: str) -> str:
    query = parse_qs(urlparse(source_url).query)
    value = (query.get("company") or query.get("keyword") or [""])[0]
    return unquote(value).strip()


_CORP_SUFFIX_RE = re.compile(r"^(?:集团|股份|有限|责任|公司|控股|总公司|有限公司|股份有限公司)*$")


def _full_name_is_same_entity(full_name: str, token: str) -> bool:
    """集团全称是不是 token 这家本身：token 在开头（允许地名前缀），剩余只能是公司后缀词。"""
    name = (full_name or "").strip()
    tok = (token or "").strip()
    if not name or not tok or not company_name_matches(name, tok):
        return False
    rest = name[name.index(tok) + len(tok):]
    return bool(_CORP_SUFFIX_RE.fullmatch(rest))


def _nature_codes(source_url: str) -> tuple:
    """可选职位性质码（逗号分隔），空 = 不筛（沿用旧行为，社招 + 校招混出）。"""
    value = (parse_qs(urlparse(source_url).query).get("nature") or [""])[0]
    return tuple(code.strip() for code in unquote(value).split(",") if code.strip())


def _match_token(source_url: str) -> str:
    """可选精准过滤词：只放行 company_name 含它的岗（应对国聘关键词的模糊夹带）。"""
    value = (parse_qs(urlparse(source_url).query).get("match") or [""])[0]
    return unquote(value).strip()


def _row_passes_match(row: dict, match: str, group_ok=None) -> bool:
    """放行列表行。分两条路，判据不同：

    ① 直接关键词搜出来的行 → 按 source_url 的 `match` 核名（防「搜中国建筑夹带无关公司」）。
    ② 集团子公司展开出来的行 → **不能豁免**，改用国聘自己的集团归属核验（`group_ok`）。

    ⚠️ 2026-09-04 实测的张冠李戴：南方电网的子公司名单里有「海南电网有限责任公司」，
    adapter 拿它去关键词搜，而**国聘的搜索是按集团模糊匹配的**，回来的既有真兄弟公司
    （鼎和财产保险，名字里没有「南方电网」），也有毫不相干的
    「中国（海南）改革发展研究院有限责任公司」「洋浦国际投资咨询有限公司」「海南健康发展研究院」。
    国聘自己的公司主页写得很清楚：这三家分别是**民营企业 / 洋浦经济开发区 / 事业单位**，
    与南方电网无关。旧写法对 `_group_child` 直接 return True、整个跳过核验 →
    它们被打上「（南方电网）」入库。归属准确性是红线，不能有旁路。

    为什么不能用「子公司名核名」代替：国聘搜索是集团级的，搜「海南电网有限责任公司」
    返回的鼎和保险是**真兄弟公司但名字对不上**，按名字核会把真岗全毙掉（实测放行 0 条）。
    唯一可信的判据是国聘自己的 group_id —— 见 `_group_membership_ok`。
    """
    if not isinstance(row, dict):
        return False
    name = str(row.get("company_name") or "").strip()
    if group_ok is not None:
        # 有集团口径时它对**所有**行生效，不只对 _group_child：
        # 直接关键词搜出来的鼎和财产保险也是南方电网真子公司，按名字核会被误杀。
        return bool(group_ok(row))
    if not match:
        return True
    return company_name_matches(name, match)


def _env_cap(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return max(0, int(raw)) if raw not in (None, "") else default
    except ValueError:
        return default


def _dedupe_rows(rows: List[dict]) -> List[dict]:
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("job_id") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    return out


def _company_with_group_brand(company: str, group_short_name: str) -> str:
    company = (company or "").strip()
    brand = (group_short_name or "").strip()
    if not company or not brand or brand in company:
        return company
    return f"{company}（{brand}）"


def _location(district_list) -> Optional[str]:
    if not isinstance(district_list, list):
        return None
    values = []
    for item in district_list:
        if isinstance(item, dict) and _text(item.get("area_cn")):
            values.append(_text(item.get("area_cn")))
    return "、".join(dict.fromkeys(values)) or None


def _salary_text(row: dict) -> Optional[str]:
    if row.get("is_negotiable"):
        return "面议"
    lo, hi = row.get("min_wage"), row.get("max_wage")
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if lo <= 0 and hi <= 0:
        return None
    unit = _text(row.get("wage_unit_cn")) or "元/月"
    if lo > 0 and hi > 0:
        return f"{lo:g}-{hi:g}{unit}"
    return f"{max(lo, hi):g}{unit}"


def _date(value) -> Optional[str]:
    text = _text(value)
    return text[:10] if text else None


def _text(value) -> Optional[str]:
    text = str(value or "").strip()
    return text or None
