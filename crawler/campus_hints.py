"""校招入口线索表（车道 3「聚合站线索」）：公司名 → 候选网申链接。

线索来自 `targets_campus_2027.json` 的 `campus_url_hint`（以及 harvest_campus_hints.py 从公开
校招汇总页抓回来写进同一字段的结果）。

🚩 **线索只是线索，不是入口**：这些 URL 没有经过任何核验，可能过期、可能指错公司。
所以本模块只负责「把线索读出来 + 挡掉禁抓域名」，**入库前照样走 fingerprint → 归属核验 →
probe 探活 → 真抓回读健康岗**，与搜索车道拿到的候选完全同一道门。

禁抓域：BOSS / 智联 / 前程无忧 / 猎聘 等第三方招聘平台是红线（CLAUDE.md「边界」），
线索命中即丢；国聘是创始人拍板的唯一例外，但它有自己的车道 4，不从这里进。
"""
import json
import os
from urllib.parse import urlparse


TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets_campus_2027.json")

# 与 entry_finder._THIRD_PARTY_HOSTS 同性质，但这里是**线索入口**的过滤，写全独立一份：
# 聚合站抓回来的链接里第三方平台占比高，挡在最前面比让它们一路走到 classify 更省。
_BANNED_HOSTS = (
    "zhipin.com", "zhaopin.com", "51job.com", "liepin.com", "lagou.com",
    "jobui.com", "kanzhun.com", "nowcoder.com", "shixiseng.com",
    "yingjiesheng.com", "dajie.com", "maimai.cn", "linkedin.com", "indeed.com",
    "niuqizp.com", "chinahr.com", "job5156.com",
)


def _host_matches(host, domain):
    return host == domain or host.endswith("." + domain)


def is_allowed_hint(url):
    """纯函数：这条线索允许进漏斗吗（http(s) + 非第三方招聘平台）。"""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:  # noqa: BLE001
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ("http", "https") or not host:
        return False
    return not any(_host_matches(host, domain) for domain in _BANNED_HOSTS)


def hints_from_targets(rows):
    """targets 行列表 → {公司名: 线索URL}。纯函数，不读盘。

    同一家给多行时**先出现的胜出**（targets 文件是人工/脚本按可信度排过的），
    且 company 与 cn 两个名字都登记 —— 必投清单用的是品牌短名，targets 用的可能是全称。
    """
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("campus_url_hint") or "").strip()
        if not url or not is_allowed_hint(url):
            continue
        for key in (row.get("company"), row.get("cn")):
            name = str(key or "").strip()
            if name and name not in out:
                out[name] = url
    return out


_CACHE = None


def load_hints(path=None):
    """读 targets 文件并缓存（同一进程只读一次）。读不到返回空表，不抛。"""
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    target = path or TARGETS_FILE
    try:
        with open(target, encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception:  # noqa: BLE001 —— 线索表缺失只是少一条车道，不该拖垮漏斗
        rows = []
    hints = hints_from_targets(rows if isinstance(rows, list) else [])
    if path is None:
        _CACHE = hints
    return hints


def hint_for(company, hints=None):
    """公司名 → 线索 URL。**只认精确同名**（去空白）。

    🚫 刻意不做子串匹配：这里的键是「线索表里的公司名」，清单名 ⊂ 线索表名会让
    「京东」直接吃到「京东方」的网申链接 —— 那正是 CLAUDE.md「必投清单公司名 ↔
    sources.company」那块碑记的张冠李戴红线，而本车道又恰恰没有 resolve_owner 那种
    「最长清单名胜出」的消歧手段。宁可漏一家（回落下一条车道），不可指错一家。
    """
    table = load_hints() if hints is None else hints
    return table.get(str(company or "").strip()) or None
