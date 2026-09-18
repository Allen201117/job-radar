"""国聘（iguopin.com，国资委官方央企招聘平台）的**招聘公告**接入。

为什么单独一个模块、不走 portals.py：
- portals.py 那套是「抓 HTML 列表页 → 抓详情页 → 正则抽截止日」；国聘是 JSON 接口，
  报名起止日**本来就是结构化字段**（实测 100/100 都有），根本不需要抽。
- 它也没有逐条的官方详情页（前端路由表里只有列表路由 `/recruitment-hub/announcement`，
  没有 detail 路由 —— 2026-09-18 下载 main bundle 逐个常量核过。别再去猜 `/detail?id=`，
  那个路径会被 SPA 打回首页）。逐条入口是列表里的 `apply_url` 字段（实测 100/100 非空），
  **整轮只需要 1 次接口请求**；曾经逐条打 `/api/activity/announcement/v1/info` 补这个字段，
  纯属多余，而且第 100 来次就被限流返 403 把整轮拖崩。

为什么值得接（2026-09-18 实测）：库里原有的 118 条公告全是各省人社厅的高校 / 事业单位，
**央国企一条都没有**；国聘这 100 条里 中央企业 8 + 央企子公司 1 + 地方国企 30 + 金融 1，
且 100/100 带报名截止日 —— 正好补上供给缺口，顺带治好「截止日抽不准」。

⚠️ 合规：国聘是 CLAUDE.md 里「第三方平台禁令」的**唯一例外**（创始人 2026-07-26 拍板，
   理由是央企大多没有逐岗官方详情页）。robots.txt 实测 `Disallow:`（全站放行）。
   但 `apply_url` 有少数会落到 智联 / 前程无忧 / 中华英才（实测 3/100）—— 那几家仍是红线，
   命中即丢弃，不入库。

⚠️ 签名是复刻它前端 JS 里那套 HMAC（匿名可用、不需要登录）。**它随时可能改**：
   改了之后接口仍返 HTTP 200、但 body 里 code != 200。所以 `_call` 必须抛错，
   绝不能安静返回空列表 —— 「绿灯零产出」在本项目是明令禁止的（工程化底线）。
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
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

import db  # noqa: E402
import ops_runs  # noqa: E402

from .classify import detect_audience, detect_employer_type, is_recruitment_announcement

PORTAL_KEY = "iguopin"
_API = "https://gp-api.iguopin.com"
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


def _call(client: httpx.Client, path: str, body: dict) -> dict:
    """调一次国聘接口。⚠️ 业务码非 200 必须抛错——签名失效时 HTTP 仍是 200，
    安静返回空会变成「绿灯零产出」，正是本项目禁止的静默失败。"""
    headers = {"Content-Type": "application/json", "Device": "h5",
               "Version": "5.2.300", "Subsite": "iguopin", **_sign("POST", path)}
    resp = client.post(_API + path, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 200:
        raise RuntimeError(f"iguopin {path} 业务码 {data.get('code')}: {data.get('msg')}（签名或参数可能已失效）")
    return data.get("data") or {}


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
        r = client.get(url, headers={"User-Agent": _UA}, timeout=20, follow_redirects=True)
        return r.status_code not in (404, 410)
    except Exception:  # noqa: BLE001
        return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def harvest(sb, dry_run: bool = False, today: date | None = None, check_links: bool = True) -> dict:
    today = today or date.today()
    started = _now_iso()
    with httpx.Client(timeout=30) as client:
        items = _call(client, "/api/activity/announcement/v1/list",
                      {"page": 1, "page_size": 100}).get("list") or []
        if not items:
            raise RuntimeError("iguopin 列表返回 0 条——形态或签名可能已变（不静默放过）")

        rows, drops = [], {}

        def drop(reason: str) -> None:
            drops[reason] = drops.get(reason, 0) + 1

        def build(item: dict) -> dict | None:
            title = (item.get("title") or "").strip()
            if not title or not is_recruitment_announcement(title):
                drop("not_recruitment")     # 遴选 / 公示 / 成绩 一类，与人社厅同一道标题门
                return None
            deadline = _parse_dt(item.get("apply_end_time"))
            if deadline and deadline < today:
                drop("deadline_passed")
                return None
            # 报名入口列表里就带（实测 100/100 非空）→ **不要**再逐条打 /info：
            # 那是 100 次多余请求，而且实测会被限流返 403，白白把整轮拖崩。
            url = (item.get("apply_url") or "").strip()
            if not url.startswith("http"):
                drop("no_apply_url")
                return None
            host = urlparse(url).netloc
            if any(b in host for b in _BANNED_HOSTS):
                drop("banned_platform")     # 智联 / 前程无忧 / 中华英才 —— 第三方平台红线
                return None
            if check_links and not _link_alive(client, url):
                drop("dead_link")
                return None
            start = _parse_dt(item.get("apply_start_time"))
            return {
                "source_portal": PORTAL_KEY,
                "source_url": url,
                "title": title,
                "region": _region(item),
                "employer_type": _employer_type(item),
                "audience": _audience(item),
                "published_at": (start or _parse_dt(item.get("create_time")) or None)
                                and (start or _parse_dt(item.get("create_time"))).isoformat(),
                "deadline": deadline.isoformat() if deadline else None,
                "deadline_text": (f"{item.get('apply_start_time','')[:10]} 至 "
                                  f"{item.get('apply_end_time','')[:10]}").strip(" 至"),
                "status": "active",
                "verdict": "ok",
                "last_seen_at": _now_iso(),
                "last_checked_at": _now_iso(),
                "updated_at": _now_iso(),
            }

        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            for row in pool.map(build, items):
                if row:
                    rows.append(row)

    # 同一个 apply_url 可能挂着多条公告（实测有重复），source_url 是唯一键 → 先本地去重再 upsert
    deduped = {r["source_url"]: r for r in rows}
    if len(deduped) < len(rows):
        drops["duplicate_url"] = len(rows) - len(deduped)
    final = list(deduped.values())

    if final and not dry_run:
        sb.table("announcement_postings").upsert(final, on_conflict="source_url").execute()

    metrics = {"fetched": len(items), "kept": len(final), "drops": drops,
               "with_deadline": sum(1 for r in final if r["deadline"])}
    if not dry_run and sb is not None:
        ops_runs.record_ops_run(sb, "announcement_iguopin", metrics,
                                status=ops_runs.status_from_counts(processed=len(items), failed=0),
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
    print(f"[announce-iguopin] 拉到 {m['fetched']} / 入库 {m['kept']} / 带截止日 {m['with_deadline']}")
    print(f"[announce-iguopin] 丢弃原因：{m['drops']}")
    if args.dry_run:
        for r in m["rows"][:25]:
            print(f"  · [{r['employer_type']}·{r['region']}·{r['audience']}] {r['title'][:38]} "
                  f"| 截止 {r['deadline']} | {urlparse(r['source_url']).netloc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
