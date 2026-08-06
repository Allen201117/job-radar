"""校招板块批量探测器 —— 按 ATS 平台模板成批补校招源，取代逐家手工啃。

## 为什么要有它

2026-08-04 手工啃了阿里/快手/美团/网易四家自建门户，每家 ~30-45 分钟。而库里 **94% 的源
（968/1025）是通用 ATS 平台**，只有 5%（57 个）是自建门户——手工逐家啃的是那 5%，
方向就错了。平台的校招板块 URL 是**模板化**的，可以批量推导 + 批量探活。

## 平台层的真实缺口（2026-08-04 实测，别照 URL 正则瞎算）

    beisen  212 源  ❌ 无需补：发 Category:[] 一次抓全社招+校招+实习（迁移 186 已据此去重）
    wt       35 源  ❌ 无需补：_RECRUIT_TYPES=(2,1,12) 三类都翻
    feishu   64 租户 ❌ 无需补：**live 验证 /campus 与 /index 返回同一批岗**
                      （小鹏/小米 岗位 ID 交集 600/600，只是 jd_url 前缀不同）
    hotjob   51 租户 ✅ 缺 8：school.html 是独立 recruitType，adapter 按页面名决定
    moka    219 租户 ✅ 缺 143：campus-recruitment 是独立 portal

## 四道门，每一道都是踩过坑加的

1. **robots 门**——今天 kuaishou 校招站 robots.txt 是 `Disallow: /`，本地 adapter 跑得欢
   （510 岗），上生产一条不进。**本地能 fetch ≠ 能抓**。
2. **可解析门**——候选 URL 能被对应 adapter 解析出 ≥1 个岗。
3. **⚠️ 非重复门（最重要）**——候选板块返回的必须**不是**该租户既有源那一批岗。
   今天差点栽在飞书上：`/campus` 与 `/index` jd_url 完全不同（portal 前缀不同）→ 按 URL 比
   交集为 0，看着像两个板块；按**岗位 ID** 比才发现是同一批 600 个岗。若照此建 23 个源，
   就是迁移 186 那场灾难重演（双源抢岗 → last_seen_at 搁浅 → 缺席探活永久失效 → 死岗下不了架）。
   **所以比对必须用岗位身份，不能用 URL 字符串。**
4. **产出验收门**——复用 gap_funnel 已验证工艺：插 disabled 源 → 真抓一轮 →
   回读香港库该源健康岗 ≥1 才 enable；否则删源删脏岗。

编排与 IO 在 campus_board_probe_run.py，本模块只放纯函数（可单测、不打网络）。
"""

import re
from typing import Iterable, Optional

from campus_lane import is_campus_season

# 失败退避（天）：不同原因复查价值差很多，别一刀切天天重探。
RETRY_DAYS = {
    "robots_blocked": 3650,    # 合规禁止基本不会变，等于永久搁置（要变也是人工发现）
    "unreachable": 30,
    "empty_board": 14,         # 现在没岗，开闸后可能有 → 两周后再看
    "duplicate_board": 3650,   # 与既有源同一批岗，平台机制决定的，不会变
    "no_healthy_jobs": 30,
}

# 校招季（秋招 8-11 月 / 春招 2-4 月）的退避覆盖：只对「等开闸」类状态生效。
#
# 为什么要有它：`empty_board` = 板块在、但当下没挂岗，**正是等开闸的状态**。淡季两周一探
# 合理；但秋招开闸是突发的（2026-08-03 单日入库 +2030 个校招岗），14 天退避意味着 8/5 探空的
# 板块要等到 8/19 才复查——整个 8 月上中旬的开闸窗口全错过，而这正是应届生最需要看到岗位的时候。
#
# 只缩 empty_board，不动其它：`unreachable`/`no_healthy_jobs` 是链路问题不是时令问题，
# 缩短只会空烧；`robots_blocked`/`duplicate_board` 是结构性结论，永远不该因季节改变。
CAMPUS_SEASON_RETRY_DAYS = {
    "empty_board": 3,
}


def retry_days(state: str, month: Optional[int] = None) -> int:
    """某个失败状态该退避多少天再复查；校招季对「等开闸」类状态加速。

    month=None（未传月份）时一律走淡季表——宁可探得慢，也不因为拿不到时令而误判成旺季。
    """
    if is_campus_season(month) and state in CAMPUS_SEASON_RETRY_DAYS:
        return CAMPUS_SEASON_RETRY_DAYS[state]
    return RETRY_DAYS.get(state, 30)

# 平台 → 该平台的校招板块是否需要**单独建源**。False = 既有源已抓全三类，补了就是重复源。
NEEDS_SEPARATE_CAMPUS_SOURCE = {
    "hotjob": True,
    "moka": True,
    "beisen": False,   # Category:[] 不按类别过滤
    "wt": False,       # _RECRUIT_TYPES=(2,1,12)
    "feishu": False,   # live 验证：portal 不影响返回集
    "xiaomi_feishu": False,
    "nio_feishu": False,
    "xpeng_feishu": False,
    "horizon_feishu": False,
}

_HOTJOB_RE = re.compile(r"^(https?://[^/]+)/([^/]+)/pb/([a-z]+)\.html", re.I)
_MOKA_RE = re.compile(
    r"^(https?://[^/]+)/(social-recruitment|campus-recruitment|campus_apply|apply)/([^/]+)(?:/(\d+))?", re.I)

# 从 jd_url 抽「岗位身份」用的模式：各平台的详情页里那个稳定 id。
# ⚠️ 必须剥掉 portal / 板块前缀——身份是岗位 id，不是整条 URL（见文件头第 3 道门）。
_IDENTITY_PATTERNS = (
    re.compile(r"/position/(\d+)/detail"),        # feishu
    re.compile(r"[?&]jobId=(\d+)"),               # moka / 通用
    re.compile(r"[?&]postId=([\w-]+)"),           # hotjob / wt
    re.compile(r"/job-info/(\d+)"),               # kuaishou
    re.compile(r"[?&]positionId=(\d+)"),          # alibaba
    re.compile(r"[?&]jobUnionId=(\d+)"),          # meituan
    re.compile(r"/(\d{4,})(?:[/?#]|$)"),          # 兜底：路径末段的长数字
)


def job_identity(jd_url: Optional[str]) -> Optional[str]:
    """从详情页 URL 抽稳定岗位身份（剥掉板块/portal 前缀）。抽不出返回 None。"""
    if not jd_url:
        return None
    for pattern in _IDENTITY_PATTERNS:
        m = pattern.search(jd_url)
        if m:
            return m.group(1)
    return None


def job_identities(jd_urls: Iterable[str]) -> set:
    """一批 URL → 岗位身份集合（抽不出的丢弃）。"""
    out = set()
    for u in jd_urls or []:
        ident = job_identity(u)
        if ident:
            out.add(ident)
    return out


def is_duplicate_board(existing_jd_urls, candidate_jd_urls, overlap_threshold: float = 0.8) -> bool:
    """候选板块是不是既有源那一批岗（= 建了就是重复源）。

    比**岗位身份**不比 URL 字符串：同一个岗在不同 portal 下 URL 不同，按 URL 比会得出
    「交集 0 = 两个板块」的错误结论（飞书实测：/campus 与 /index 岗位 ID 交集 600/600，
    URL 交集 0）。

    判据：候选集里有 ≥threshold 比例的岗已出现在既有源里 → 判重复。
    两边任一抽不出身份（空集）时**保守判重复**——宁可漏建一个源，也不建重复源：
    漏建只是少抓一个板块，建重复会让缺席探活对整个租户永久失效（迁移 186 教训）。
    """
    cand = job_identities(candidate_jd_urls)
    exist = job_identities(existing_jd_urls)
    if not cand or not exist:
        return True
    return len(cand & exist) >= len(cand) * overlap_threshold


def campus_candidate_url(adapter_name: str, source_url: str) -> Optional[str]:
    """由租户既有（社招）源推导校招板块候选 URL。推不出 / 该平台无需单独源 → None。"""
    if not NEEDS_SEPARATE_CAMPUS_SOURCE.get(adapter_name or ""):
        return None
    url = source_url or ""

    if adapter_name == "hotjob":
        m = _HOTJOB_RE.match(url)
        if not m or m.group(3).lower() == "school":
            return None
        return f"{m.group(1)}/{m.group(2)}/pb/school.html"

    if adapter_name == "moka":
        m = _MOKA_RE.match(url)
        if not m or m.group(2).lower() in ("campus-recruitment", "campus_apply"):
            return None
        # 不带 portal id：moka 会 302 到该租户正确的校招 portal
        # （实测 /campus-recruitment/xcmg → /campus-recruitment/xcmg/148091；
        #  portal id 不可推导——约一半是 social+1，另一半完全无关，只能靠跳转拿）。
        return f"{m.group(1)}/campus-recruitment/{m.group(3)}"

    return None


def moka_tenant(source_url: str) -> Optional[str]:
    m = _MOKA_RE.match(source_url or "")
    return m.group(3) if m else None


def hotjob_tenant(source_url: str) -> Optional[tuple]:
    m = _HOTJOB_RE.match(source_url or "")
    return (m.group(1), m.group(2)) if m else None


def classify_empty_result(crawl_result) -> str:
    """抓完一个岗都没有时，这是「板块空着」还是「抓坏了」？返回台账 state。

    ⚠️ 这个区分栽过三次（阿里校招频道 / 校招板块验收 / run_crawl 的 empty 状态），
    根子是同一条：**在「等开闸」这类场景里，「什么都没等到」是正常态、不是故障态**。
    判错的代价不对称——把「板块空着」当故障会吃长退避、错过整个开闸窗口；
    反过来只是多探一次。

    判据取 run_crawl 的返回：
      failed ≥ 1                     → 真失败（no_healthy_jobs，长退避）
      success/empty 至少处理过 1 个   → 板块空着（empty_board，短退避，开闸后复查）
      两者皆无（如 robots skipped）   → 当失败处理，长退避
    """
    result = crawl_result or {}
    if (result.get("failed") or 0) >= 1:
        return "no_healthy_jobs"
    processed = (result.get("success") or 0) + (result.get("empty") or 0)
    return "empty_board" if processed >= 1 else "no_healthy_jobs"
