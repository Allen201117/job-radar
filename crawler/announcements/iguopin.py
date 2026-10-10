"""国聘（iguopin.com，国资委官方央企招聘平台）的**招聘公告**接入。

为什么单独一个模块、不走 portals.py：
- portals.py 那套是「抓 HTML 列表页 → 抓详情页 → 正则抽截止日」；国聘是 JSON 接口，
  报名起止日**本来就是结构化字段**（实测 100/100 都有），根本不需要抽。
- 它也没有逐条的官方详情页（前端路由表里只有列表路由 `/recruitment-hub/announcement`，
  没有 detail 路由 —— 2026-09-18 下载 main bundle 逐个常量核过。别再去猜 `/detail?id=`，
  那个路径会被 SPA 打回首页）。逐条入口是列表里的 `apply_url` 字段（实测 100/100 非空），
  不需要逐条打 `/api/activity/announcement/v1/info` 补这个字段——纯属多余，而且会被限流。

为什么值得接（2026-09-18 实测）：库里原有的 118 条公告全是各省人社厅的高校 / 事业单位，
**央国企一条都没有**；国聘正好补上这块供给缺口，报名起止日还是结构化字段。

🚫 列表接口**没有翻页**，每次查询硬顶 100 条；不带筛选时回的是「置顶 + 即将截止」（2026-10-10 立）：
❌ 现象：/programs 455 张公告里 131 张（28.8%）写「今天截止」；国聘 275 行里 204 行（74%）在 0~2 天内截止，
   且几乎都是截止前 0~2 天才首次入库 —— 用户看到时只剩一两天。
✅ 根因（逐项实测，不是推断）：
   · `page=1/2/3` 三次返回**同一批** 100 条，响应里 `page / page_size / total` 恒为 0 —— 翻页参数根本没被读；
     PC 版与手机版页面自己发的请求体里也没有任何翻页字段，页面滚到底只有一句「海量招聘信息请通过国聘App搜索查找」。
   · 默认这 100 条 = 7 条置顶（sort_order > 100）+ 93 条 `apply_status=2`（即将截止 = 距截止 0~2 天），
     后者与「只筛即将截止」查询的前 93 条逐条相同。所以「只取默认列表」= 系统性地只收马上要截止的。
   · 页面上的「排序方式」（按更新时间 / 按截止时间）服务端不认：照页面原样发过去，返回与默认列表逐条相同。
   · 在报名期的真实总量是**几千条**（被限流前已见到 3,183 条不同的；光「正在报名 × 事业单位」就 1,400+），
     不是几百条 —— 「全部取回」在这个接口上做不到。
✅ 防：按页面自己的公开筛选维度切片 —— 状态（1 正在报名 / 2 即将截止）× 分类，每格各取前 100
   （`collect_in_window`，一轮 32 次请求）。**撞 100 的格子如实记进台账 `capped_cells`，不假装取全了**。
⚠️ 限流：约 1 次/秒连续打到第 200 次左右，接口开始回 **HTTP 200 + 业务码 403「账号类型错误或权限不足」**，
   几分钟后自动恢复（2026-10-10 实测两次）。所以请求数有硬预算（`IGUOPIN_MAX_REQUESTS`）+ 每次间隔 1 秒；
   中途被限流就带着已取到的收工并把台账记成 partial，**别把预算调高去硬切到省 / 地市**。
⚠️ 「招满即止 / 报满即止」的公告约占四成，国聘登记的结束日对它们只是**上限**（1,382 条里 1,254 条填在 11~12 月），
   不是「报到那天都来得及」。把它原样当报名截止日展示 = 告诉用户「还有两个月」，而实际是越早投越好。
   ⇒ deadline 仍存国聘登记的那一天（国聘自己也是到那天才标「结束报名」，过期治理照常），
     但 deadline_text 存国聘的原话「招满即止」，卡片据此写「招满即止 · 最晚 X」（见 `_window_of`、
     `lib/announcement-postings.isRollingDeadline`）。
   🚫 别改成「deadline 留空 + 按发布日 45 天 TTL 过期」：试过，当场丢掉 173 条还在报的（平安银行 / 腾讯投资 /
     阳光电源的 2027 届校招都是 8 月开、招满即止）—— 秋招本来就一开几个月。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import hmac
import os
import random
import re
import string
import sys
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

import db  # noqa: E402
import ops_runs  # noqa: E402

from .classify import detect_audience, detect_employer_type, is_recruitment_announcement
from .quality import assess

PORTAL_KEY = "iguopin"
_API = "https://gp-api.iguopin.com"
_LIST_PATH = "/api/activity/announcement/v1/list"
# 接口硬顶：一次查询最多回这么多条，且没有翻页（见文件头）。回满 = 这一格没取全。
_LIST_CAP = 100
# 在报名期内的两档状态（取值来自国聘前端 JS 的枚举）：1 正在报名（距截止 ≥3 天）/ 2 即将截止（0~2 天）。
# 3 即将报名、4 结束报名 不取。顺序即优先级：预算不够或中途被限流时，先保住还有时间报的那一档。
_IN_WINDOW_STATUS = ((1, "正在报名"), (2, "即将截止"))
# 分类码取自国聘公告页筛选组件（2026-10-10 读页面状态）。条目自带的 `category_code` 里出现这张表没有的码时，
# `collect_in_window` 会当场补查并记进台账 `new_category_codes` —— 国聘增删分类不至于静默漏一整类。
_CATEGORY_CODES = {
    "1122Rdki": "中央企业", "117px91": "央企子公司", "11XYejY": "地方国企", "116ac59Z": "银行证券保险基金",
    "113ps2iC": "文化央企", "11q4iQX": "事业单位", "11FVb3h": "教师", "112wtwyJ": "医疗", "112cQaL8": "医疗单位",
    "115EByuz": "公务员", "115nA8wj": "名企及互联网", "112nzgGK": "外资企业", "112ajAY5": "合资企业",
    "114oKfhE": "民营企业", "113d8Ned": "其他",
}
# 单轮请求预算。现在一轮 32 次（2 个状态 + 2 × 15 个分类，2026-10-10 实测）；留余量给新冒出来的分类码，
# 但离限流线（约 200 次）远远的。
_MAX_REQUESTS = int(os.environ.get("IGUOPIN_MAX_REQUESTS", "60"))
_PAUSE_SECONDS = float(os.environ.get("IGUOPIN_REQUEST_PAUSE", "1.0"))
# 连续几次请求失败（网络层）就收工——对方在抖的时候别一格一格硬撞。
_MAX_REQUEST_ERRORS = 3
# 点新入口（死链检查）这一步的总时限、单个入口的超时、并发。超时一律算「够不着、放行」，所以把单个超时
# 压短不会多判死；总时限到了还没点到的入口这一轮不入库、留给下一轮（见 harvest）。
_LINK_CHECK_BUDGET_SECONDS = float(os.environ.get("IGUOPIN_LINK_CHECK_BUDGET", "480"))
_LINK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_LINK_WORKERS = 8
_SECRET = "cu4&dYe*feF8t$E9m"   # 前端硬编码常量；不是账号密钥，换了会 code!=200 直接报错
_BUCKET = 180                    # 3 分钟时间桶
_BEIJING = timezone(timedelta(hours=8))
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 第三方商业招聘平台红线（CLAUDE.md）：apply_url 落到这些域名的公告一律不入库。
_BANNED_HOSTS = ("zhaopin.com", "chinahr.com", "51job.com", "zhipin.com", "liepin.com", "lagou.com")


def _sign(method: str, path: str) -> dict[str, str]:
    ts = int(datetime.now(timezone.utc).timestamp())
    nonce = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    day = datetime.fromtimestamp(ts, _BEIJING).strftime("%Y%m%d")
    key = hmac.new(_SECRET.encode(), f"{day}:{ts // _BUCKET}".encode(), hashlib.sha256).hexdigest()
    payload = "|".join([str(ts), nonce, method.upper(), path, "h5"])
    return {
        "Sign": hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest(),
        "T": str(ts),
        "Nonce": nonce,
    }


class IguopinApiError(RuntimeError):
    """HTTP 200 但拿不到正常数据：业务码不是 200，或响应体根本不是 JSON 对象。
    签名失效、参数不认、被限流（实测是业务码 403）、网关页都长这样。"""

    def __init__(self, path: str, code, msg):
        super().__init__(f"iguopin {path} 业务码 {code}: {msg}（签名失效 / 参数不认 / 被限流）")
        self.code = code


class _Stop(Exception):
    """collect_in_window 内部用：这一轮该收工了（预算用完 / 被接口拒绝 / 连续失败）。"""


def _call(client: httpx.Client, path: str, body: dict) -> dict:
    """调一次国聘接口。⚠️ 业务码非 200 必须抛错——签名失效时 HTTP 仍是 200，
    安静返回空会变成「绿灯零产出」，正是本项目禁止的静默失败。"""
    headers = {"Content-Type": "application/json", "Device": "h5",
               "Version": "5.2.300", "Subsite": "iguopin", **_sign("POST", path)}
    resp = client.post(_API + path, headers=headers, json=body)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        # 限流前后可能回网关页 / 截断的 body。归到同一类错误里，中途遇到才能「带着已取到的收工」而不是整轮崩掉。
        raise IguopinApiError(path, "bad_body", "HTTP 200 但响应体不是 JSON 对象")
    if data.get("code") != 200:
        raise IguopinApiError(path, data.get("code"), data.get("msg"))
    payload = data.get("data")
    return payload if isinstance(payload, dict) else {}


def collect_in_window(call, max_requests: int | None = None, pause: float | None = None) -> tuple[list[dict], dict]:
    """把在报名期内的公告按「状态 × 分类」切片取回来。`call(body) -> list[dict]` 调一次列表接口。

    为什么要切：接口没有翻页、一次硬顶 100 条，而在报名期的有几千条（见文件头）。
    切到哪：某个状态整体不满 100 就不用再切；满了就按分类各查一次。分类这一层仍回满 100 的格子
    记进 `capped_cells` —— 它们没取全，这是**已知且如实上报**的，不是成功。再往下切（省 / 地市）
    一轮要几百次请求、会撞限流，所以不做。

    失败口径：
    - 第一次请求就失败 → 原样抛出（签名坏了 / 接口变了，整轮必须响）。
    - 之后遇到接口拒绝 → 带着已取到的收工，`api_rejected=True` + 原样记下业务码（实测被限流时是 403）。
    - 之后遇到网络层错误 → 这一格跳过并计数，连续 `_MAX_REQUEST_ERRORS` 次就收工。
    """
    budget = _MAX_REQUESTS if max_requests is None else max_requests
    gap = _PAUSE_SECONDS if pause is None else pause
    names = dict(_CATEGORY_CODES)
    status_name = dict(_IN_WINDOW_STATUS)
    seen: dict[str, dict] = {}
    need: list[int] = []                      # 整体回满 100、需要再按分类切的状态
    queue: deque[tuple[int, str]] = deque()   # 待查的（状态, 分类码）
    stats = {"requests": 0, "capped_cells": [], "new_category_codes": [], "by_status": {},
             "api_rejected": False, "api_error_code": None, "budget_exhausted": False, "request_errors": 0}
    consecutive_errors = 0

    def fetch(body: dict) -> list[dict] | None:
        """返回这一格的条目；这一格没取到返回 None；该收工了抛 _Stop。"""
        nonlocal consecutive_errors
        if stats["requests"] >= budget:
            stats["budget_exhausted"] = True
            raise _Stop
        first = stats["requests"] == 0
        if not first and gap:
            time.sleep(gap)
        stats["requests"] += 1
        try:
            items = call(body) or []
        except IguopinApiError as exc:
            if first:
                raise
            # 观测是「接口拒了」，不是「被限流」——后者只是最常见的原因（实测业务码 403）。码原样记下来。
            stats["api_rejected"] = True
            stats["api_error_code"] = exc.code
            raise _Stop
        except httpx.HTTPError:
            if first:
                raise
            stats["request_errors"] += 1
            consecutive_errors += 1
            if consecutive_errors >= _MAX_REQUEST_ERRORS:
                raise _Stop
            return None
        consecutive_errors = 0
        for it in items:
            # 没有 id 的条目（没见过，但别因此把整轮搞崩）退回用入口链接当键。
            seen[str(it.get("announcement_id") or it.get("apply_url") or id(it))] = it
        return items

    def discover(items: list[dict]) -> None:
        """条目自带的分类码里有表里没有的 → 记下来，并给每个要切的状态各补查一格。"""
        for it in items:
            labels = it.get("category_cn") or []
            for i, code in enumerate(it.get("category_code") or []):
                if code and code not in names:
                    names[code] = labels[i] if i < len(labels) else code
                    stats["new_category_codes"].append(f"{code}={names[code]}")
                    queue.extend((s, code) for s in need)

    try:
        for status in status_name:
            items = fetch({"apply_status": [status]})
            # 没取到不等于不满 100：保守地照样切
            if items is None or len(items) >= _LIST_CAP:
                need.append(status)
        queue.extend((s, code) for s in need for code in _CATEGORY_CODES)
        discover(list(seen.values()))
        while queue:
            status, code = queue.popleft()
            items = fetch({"apply_status": [status], "category_codes": [code]})
            if items is None:
                continue
            if len(items) >= _LIST_CAP:
                stats["capped_cells"].append(f"{status_name[status]}|{names[code]}")
            discover(items)
    except _Stop:
        pass

    for it in seen.values():
        key = status_name.get(it.get("apply_status"), f"状态{it.get('apply_status')}")
        stats["by_status"][key] = stats["by_status"].get(key, 0) + 1
    return list(seen.values()), stats


_SOCIETY_OPEN = re.compile(r"(面向社会|社会公开招聘|社会公开招募)")


def _audience(item: dict) -> str:
    """应届 / 社会。**以标题为准，国聘自己的标签只当兜底。**

    ⚠️ 2026-09-18 实测：`announcement_tags` 里 81/100 打着「校招」，其中包括
    「赣州旅游投资集团2026年**社会**公开招聘公告」这种明显的社招 —— 这个标签不可信。
    ⚠️ `graduation_years_cn` 95/100 非空，但填的大多是「**无**毕业年份要求」，
    意思恰恰相反。早期版本把「非空」当成应届信号，等于把一批社招标成了应届。
    """
    title = item.get("title") or ""
    from_title = detect_audience(title)
    if from_title != "unknown":
        return from_title
    # 只认真实年份（'2026'/'2027'），不认「无毕业年份要求」。
    years = [y for y in (item.get("graduation_years_cn") or []) if str(y).strip()[:2].isdigit()]
    # 「面向社会公开招聘」是弱社招信号：它同时又常写着届别要求（如赣州旅游投资集团那条
    # 标题写「社会公开招聘」、毕业年份写 2026）。两个信号都真，答案就是**两者皆可**，
    # 不该二选一。⚠️ 这个词只在国聘这一侧判，不动 classify._EXPERIENCED ——
    # 「面向社会公开招聘」是事业单位公告的通用套话，加进共用分类器会把一大批存量行翻面。
    if _SOCIETY_OPEN.search(title):
        return "both" if years else "experienced"
    if years:
        return "fresh_grad"
    labels = {str((t or {}).get("label") or "") for t in (item.get("announcement_tags") or [])}
    if labels == {"社招"}:
        return "experienced"
    return "unknown"


# 直辖市在国聘给的是「北京」，人社厅那边是「北京市」——单独兜一下。
_MUNICIPALITY = {"北京": "北京市", "天津": "天津市", "上海": "上海市", "重庆": "重庆市"}

# GB/T 2260 省级行政区划码 → 省名。国聘的 `districts` 形如
# "000000.320000.320300.320321"，第二段就是省级码 —— 取省级正好与各省人社厅那批行数据
# （region 都是「北京市」「广东省」这种省级写法）口径一致，分面里不会出现「杭州」和「浙江省」两个条目。
_PROVINCE_BY_CODE = {
    "110000": "北京市", "120000": "天津市", "130000": "河北省", "140000": "山西省",
    "150000": "内蒙古自治区", "210000": "辽宁省", "220000": "吉林省", "230000": "黑龙江省",
    "310000": "上海市", "320000": "江苏省", "330000": "浙江省", "340000": "安徽省",
    "350000": "福建省", "360000": "江西省", "370000": "山东省", "410000": "河南省",
    "420000": "湖北省", "430000": "湖南省", "440000": "广东省", "450000": "广西壮族自治区",
    "460000": "海南省", "500000": "重庆市", "510000": "四川省", "520000": "贵州省",
    "530000": "云南省", "540000": "西藏自治区", "610000": "陕西省", "620000": "甘肃省",
    "630000": "青海省", "640000": "宁夏回族自治区", "650000": "新疆维吾尔自治区",
    "710000": "台湾省", "810000": "香港特别行政区", "820000": "澳门特别行政区",
}


def _province_of(code: str | None) -> str | None:
    """从 "000000.320000.320300.320321" 取省名。"""
    parts = (code or "").split(".")
    return _PROVINCE_BY_CODE.get(parts[1]) if len(parts) > 1 else None


# 地名后面常见的行政后缀；出现它就说明前面那几个字确实是在当地名用。
_PLACE_SUFFIX = "市区县州盟旗省"
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _mentions_place(haystack: str, name: str) -> bool:
    """标题/公司名里是否真的**提到了**这个地名（中文词边界，不是裸子串）。

    ⚠️ 裸子串会出事：「**五大连**池风景区教育幼儿园」里含「大连」，于是这条黑龙江的公告
    被判成辽宁省（2026-09-18 扫全部 60 条有地区的行时抓到）。这是本项目反复踩的同一类坑
    （「京东」命中「京东方」）。判据：命中处前面不是汉字（词首），或后面紧跟行政后缀 / 非汉字。
    """
    for m in re.finditer(re.escape(name), haystack):
        before = haystack[m.start() - 1] if m.start() else ""
        after = haystack[m.end()] if m.end() < len(haystack) else ""
        at_word_start = not before or not _CJK.match(before)
        ends_cleanly = not after or after in _PLACE_SUFFIX or not _CJK.match(after)
        if at_word_start or ends_cleanly:
            return True
    return False


def _region(item: dict) -> str | None:
    """地区（省级）。跨地区 / 全国 → 「全国」；单一地区**必须与标题或公司名对得上**才敢用。

    ⚠️ 国聘的 districts 是按名字自动地理编码的，**会错**（2026-09-18 实测两例）：
      「**福州市**鼓楼区国有资产投资发展集团」→ 开封（410204 = 河南开封鼓楼区，两地都有鼓楼区）
      「**贵州**锦丰矿业有限公司」→ 徐州（320321 = 江苏丰县，匹配上了「锦**丰**」）
    写错的地区比没有地区坏得多：用户按「福建」筛看不到它，按「河南」筛却看到一条福州的岗。
    ⇒ 交叉验证：市名或省名（去掉省/市/自治区后缀）任一**按中文词边界**出现在标题/公司名里才采信，
      否则返回 None（`_mentions_place`，裸子串会把「五大连池」认成「大连」）。
      上面两例都会被这道门挡下（标题里既没有「开封」「河南」，也没有「徐州」「江苏」）。
    ⇒ 宁可漏判不可错杀 —— 本项目「归属准确性高于一切」的红线。代价是像「电子科技大学格拉斯哥学院」
      （在成都、标题里既无「成都」也无「四川」）会退回未知，可以接受。
    """
    ds = [d for d in (item.get("districts_cn") or []) if d]
    codes = [c for c in (item.get("districts") or []) if c]
    if not ds:
        return None
    if len(ds) > 1 or ds[0] == "全国":
        return "全国"
    city = ds[0]
    province = _province_of(codes[0] if codes else None)
    haystack = f"{item.get('title') or ''}{item.get('main_company_name') or ''}{item.get('source') or ''}"
    # 省名去掉行政后缀再比对：「山东省」要能被标题里的「山东大学」认出来。
    bare = re.sub(r"(省|市|自治区|特别行政区|维吾尔|壮族|回族)", "", province) if province else None
    if _mentions_place(haystack, city) or (bare and _mentions_place(haystack, bare)):
        return province or _MUNICIPALITY.get(city, city)
    return None


# 国聘自己的分类 → 本表 employer_type。企业类它分得比标题细，用它的；
# 事业单位 / 教师 / 医疗 这些交回给 detect_employer_type(标题)，与人社厅那边同口径。
_CATEGORY_MAP = {
    "中央企业": "央企", "央企子公司": "央企",
    "地方国企": "地方国企",
    "银行证券保险基金": "金融",
    "名企及互联网": "企业", "外资企业": "企业",
}


def _employer_type(item: dict) -> str | None:
    for c in item.get("category_cn") or []:
        if c in _CATEGORY_MAP:
            return _CATEGORY_MAP[c]
    return detect_employer_type(item.get("title") or "")


def _parse_dt(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _link_alive(client: httpx.Client, url: str) -> bool:
    """逐条真点一次报名入口。

    ⚠️ 只有 404/410 才判死。403 / 412 / 5xx / 超时**一律放行** —— 政府站和 Akamai 常对
    非浏览器 UA 返 412/403（本项目在国家电网上踩过），够不着 ≠ 对方撤了，判死会误杀在招公告。
    """
    try:
        r = client.get(url, headers={"User-Agent": _UA}, timeout=_LINK_TIMEOUT, follow_redirects=True)
        return r.status_code not in (404, 410)
    except Exception:  # noqa: BLE001
        return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 国聘页面上「截止」后面显示的那段文字（`apply_time`）写着这些 = 没有固定截止日，招满为止。
_ROLLING = re.compile(r"满即止|满为止")


def _window_of(item: dict) -> tuple[date | None, str, date | None]:
    """报名窗 → (deadline, deadline_text, published)。

    ⚠️ `apply_end_time` 是结构化字段，但**不总是报名截止日**：国聘页面展示的是 `apply_time` 这段文字。
    2026-10-10 实测 3,604 条：apply_time 是单个日期的 2,121 条里 2,118 条与 apply_end_time 相同（可信）；
    写「招满即止 / 报满即止」的 1,382 条，apply_end_time 只是国聘登记的最晚结束日。
    ⇒ 两种都把 apply_end_time 存进 deadline（到那天国聘自己也会标结束），区别只在 deadline_text：
      滚动的存国聘原话，读侧据此不把它写成「报名截止 X」。
    """
    start = _parse_dt(item.get("apply_start_time"))
    shown = str(item.get("apply_time") or "").strip()
    if _ROLLING.search(shown):
        text = shown[:40]
    else:
        text = (f"{str(item.get('apply_start_time') or '')[:10]} 至 "
                f"{str(item.get('apply_end_time') or '')[:10]}").strip(" 至")
    return _parse_dt(item.get("apply_end_time")), text, start or _parse_dt(item.get("create_time"))


def _incomplete(stats: dict) -> int:
    """这一轮有几处没按计划取完：接口中途拒了 / 有格子请求失败 / 预算用完队列没查完。>0 → 台账记 partial，别报 success。
    撞 100 上限的格子（capped_cells）不算：那是接口的硬限制，如实记数即可。"""
    return stats["request_errors"] + bool(stats["api_rejected"]) + bool(stats["budget_exhausted"])


def _known_active_urls(sb) -> set[str]:
    """库里正在展示的国聘入口。⚠️ 行数已过千，必须分页取（PostgREST 单次 1000 行静默截断）。"""
    rows = db.fetch_all_rows(lambda: sb.table("announcement_postings").select("source_url")
                             .eq("source_portal", PORTAL_KEY).eq("status", "active"))
    return {r["source_url"] for r in rows}


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def harvest(sb, dry_run: bool = False, today: date | None = None, check_links: bool = True,
            call=None) -> dict:
    """`call(body) -> list[dict]` 留给单测注入（不打真实网络）；默认走真实接口。"""
    today = today or date.today()
    started = _now_iso()
    persist = sb is not None and not dry_run
    with httpx.Client(timeout=30) as client:
        fetch_list = call or (lambda body: _call(client, _LIST_PATH, body).get("list") or [])
        items, stats = collect_in_window(fetch_list)
        if not items:
            raise RuntimeError("iguopin 列表返回 0 条——形态或签名可能已变（不静默放过）")

        # 库里已经在展示的入口不重复点：每轮几百上千条逐个 GET 既慢也没必要（存量行重点一次也改变不了它的状态）。
        known = _known_active_urls(sb) if persist else set()
        # 点新入口有总时限：首轮有上千个新入口，境外 runner 连不上的站每个要等到超时，不封顶会把整个 job 拖到
        # 被取消——而写库在最后，被取消 = 一条都没进，下一轮从头再来。超时没点到的**这一轮不入库**（不是放行），
        # 下一轮它们仍是新入口、接着点。即将截止的排前面：正在报名的晚一天进来无妨，它们晚一天可能就过期了。
        link_deadline = time.monotonic() + _LINK_CHECK_BUDGET_SECONDS
        items.sort(key=lambda it: it.get("apply_status") != 2)

        def build(item: dict) -> tuple[dict | None, str | None]:
            """→ (入库行, 丢弃原因)。计数在主线程做，线程里只判不记。"""
            title = (item.get("title") or "").strip()
            if not title or not is_recruitment_announcement(title):
                return None, "not_recruitment"   # 遴选 / 公示 / 成绩 一类，与人社厅同一道标题门
            # quality.assess 的标题层：「…笔试公告 / 面试公告 / 体能测评公告 / 公告汇总」——是招聘流程的一部分，
            # 但报名这一步已经过去了。国聘条目没有可信的公告正文（mobile_content 多是单位简介），所以 assess 里
            # 只有标题这一层对它成立；正文层（报名已关 / 正文里的截止日 / 汇总页）不判，报名窗以结构化字段为准。
            if assess(title, "", today=today).reason == "process_notice":
                return None, "process_notice"
            # 报名入口列表里就带 → **不要**再逐条打 /info：多余，而且会被限流。
            url = (item.get("apply_url") or "").strip()
            if not url.startswith("http"):
                return None, "no_apply_url"
            host = urlparse(url).netloc
            if any(b in host for b in _BANNED_HOSTS):
                return None, "banned_platform"   # 智联 / 前程无忧 / 中华英才 —— 第三方平台红线
            deadline, deadline_text, published = _window_of(item)
            if deadline and deadline < today:
                return None, "deadline_passed"   # 国聘自己登记的结束日已过：招满即止的也一样不收
            if check_links and url not in known:
                if time.monotonic() > link_deadline:
                    return None, "link_check_deferred"
                if not _link_alive(client, url):
                    return None, "dead_link"
            return {
                "source_portal": PORTAL_KEY,
                "source_url": url,
                "title": title,
                "region": _region(item),
                "employer_type": _employer_type(item),
                "audience": _audience(item),
                "published_at": published.isoformat() if published else None,
                "deadline": deadline.isoformat() if deadline else None,
                "deadline_text": deadline_text,
                "status": "active",
                "verdict": "ok",
                "last_seen_at": _now_iso(),
                "last_checked_at": _now_iso(),
                "updated_at": _now_iso(),
            }, None

        rows, drops = [], {}
        with cf.ThreadPoolExecutor(max_workers=_LINK_WORKERS) as pool:
            for row, reason in pool.map(build, items):
                if row:
                    rows.append(row)
                else:
                    drops[reason] = drops.get(reason, 0) + 1

    # 同一个 apply_url 可能挂着多条公告（实测有重复），source_url 是唯一键 → 先本地去重再 upsert
    deduped = {r["source_url"]: r for r in rows}
    if len(deduped) < len(rows):
        drops["duplicate_url"] = len(rows) - len(deduped)
    final = list(deduped.values())

    if persist:
        for chunk in _chunks(final, 500):
            sb.table("announcement_postings").upsert(chunk, on_conflict="source_url").execute()

    metrics = {"fetched": len(items), "kept": len(final), "drops": drops,
               "with_deadline": sum(1 for r in final if r["deadline"]),
               "rolling": sum(1 for r in final if _ROLLING.search(r["deadline_text"] or "")),
               "new_urls": sum(1 for r in final if r["source_url"] not in known),
               **stats}
    incomplete = _incomplete(stats)
    if stats["api_rejected"]:
        print(f"::warning::[announce-iguopin] 第 {stats['requests']} 次请求被接口拒绝（业务码 "
              f"{stats['api_error_code']}，多半是限流），本轮只取到 {len(items)} 条")
    if stats["budget_exhausted"]:
        print(f"::warning::[announce-iguopin] 请求预算 {stats['requests']} 次用完，还有格子没查——"
              f"多半是国聘新增了分类（{stats['new_category_codes']}），把 IGUOPIN_MAX_REQUESTS 与分类表对一下")
    if drops.get("link_check_deferred"):
        print(f"::warning::[announce-iguopin] {drops['link_check_deferred']} 个新入口没在 "
              f"{_LINK_CHECK_BUDGET_SECONDS:.0f} 秒内点完，本轮没入库，留给下一轮")
    if persist:
        ops_runs.record_ops_run(sb, "announcement_iguopin", metrics,
                                status=ops_runs.status_from_counts(processed=len(items), failed=incomplete),
                                started_at=started, finished_at=_now_iso())
    metrics["rows"] = final
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description="国聘招聘公告抓取")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-link-check", action="store_true", help="跳过逐条点开报名入口（省时间，别在 CI 用）")
    args = ap.parse_args()
    db.load_environment()
    sb = None if args.dry_run else db.get_supabase()
    m = harvest(sb, dry_run=args.dry_run, check_links=not args.no_link_check)
    print(f"[announce-iguopin] 请求 {m['requests']} 次 / 拉到 {m['fetched']}（{m['by_status']}）/ 入库 {m['kept']} "
          f"/ 其中新入口 {m['new_urls']} / 带截止日 {m['with_deadline']} / 招满即止 {m['rolling']}")
    print(f"[announce-iguopin] 丢弃原因：{m['drops']}")
    if m["capped_cells"]:
        print(f"[announce-iguopin] 回满 100 条、没取全的格子（{len(m['capped_cells'])}）：{m['capped_cells']}")
    if m["new_category_codes"]:
        print(f"[announce-iguopin] 筛选表里没有、本轮补查的分类码：{m['new_category_codes']}")
    if args.dry_run:
        for r in m["rows"][:25]:
            print(f"  · [{r['employer_type']}·{r['region']}·{r['audience']}] {r['title'][:38]} "
                  f"| 截止 {r['deadline']}（{r['deadline_text']}） | {urlparse(r['source_url']).netloc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
