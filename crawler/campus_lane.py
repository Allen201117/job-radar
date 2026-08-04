"""校招高频车道的纯判据层。

2027 届秋招正式批的特点：一家公司**一次性放出全部校招岗**，开闸即从几十涨到几百上千。
本模块只放不打网络、不碰 DB 的纯函数，供 campus-crawl 车道与开闸检测共用、可单测：

  · is_campus_season      —— 淡季不跑高频车道
  · select_campus_sources —— 选源（board 静态分类 ∪ 实际产出，交必投清单）
  · detect_surge          —— 开闸判据
  · coverage_ratio / is_undercrawled —— 抓全自检（拿不到官网自报总数时诚实返回「测不了」）

编排与 IO 在 campus_crawl.py，这里保持零副作用。
"""

from typing import Callable, Iterable, Optional

# 覆盖校招的板块值，与 lib/source-board.ts 的 CAMPUS_BOARDS 同口径（跨端契约，改动须两边同改）。
CAMPUS_BOARDS = frozenset({"campus", "mixed"})

# 秋招 8-11 月 / 春招 2-4 月。淡季车道直接早退，避免全年无谓请求目标站点。
# 用「判月份早退」而不是删 cron，是为了随时还能 workflow_dispatch 手动跑。
AUTUMN_MONTHS = frozenset({8, 9, 10, 11})
SPRING_MONTHS = frozenset({2, 3, 4})

# 开闸默认判据：两条取其一即算开闸。
#   倍数 —— 抓「17 → 800」这种正式批放量；
#   增量 —— 抓「0 → 60」这种零基线开闸（倍数规则在 prev=0 时恒成立，会把每个新源都误报一次）。
SURGE_MULTIPLE = 3
SURGE_DELTA = 50

# 抓全判据：入库数 / adapter 自报官网总数 低于此值即认为没抓全。
COVERAGE_THRESHOLD = 0.9

# 开闸检测用的「校招岗」SQL 判据（香港 jobs 库）。
#
# ⚠️ 这是**抓取运维信号**，不是用户看到的那个数。用户侧走 lib/campus-zone.ts 的 campusAdmission
# （精度优先、弱词不判校招、≥2 年经验强制社招），口径更严；这里要的是**跨快照稳定可比**：
# 开闸判据比的是同一把尺子量出来的前后两个数，尺子粗一点不影响倍数/增量的判断，
# 但尺子如果跟着产品口径漂移，历史快照就不可比了。所以这把尺子刻意独立、且刻意保持简单。
# 两边都变严/变松时不需要同步——它们回答的是不同问题。
CAMPUS_JOB_SQL_PREDICATE = (
    "(job_type ~ '校|应届|campus|Campus|graduate|Graduate' "
    "or title ~ '校招|校园招聘|应届|秋招|春招')"
)


def is_campus_season(month: Optional[int]) -> bool:
    """当前月份是否处于校招季（秋招或春招）。"""
    if not isinstance(month, int):
        return False
    return month in AUTUMN_MONTHS or month in SPRING_MONTHS


def select_campus_sources(
    sources: Iterable[dict],
    producing_source_ids: Iterable[str],
    must_apply_matcher: Optional[Callable[[str], bool]] = None,
) -> list[dict]:
    """挑出该进校招高频车道的源，保持 `sources` 的原有顺序、结果去重。

    选源 = (board ∈ {campus, mixed}  ∪  近期真产过校招岗的源)  ∩  enabled  ∩  必投清单

    ⚠️ 为什么必须并上「实际产出」而不能只信 board：
    board 由 (adapter_name, source_url) 静态派生，判不出把校招社招混在**同一个列表**里的自建门户。
    2026-08-04 live 实测：430 个真产校招岗的源里 board 只覆盖 281 个，漏掉的 149 个包括
    比亚迪(2053 岗) / 小红书(585) / Citi(267) / 华为(198) / 米哈游(119) / 蚂蚁(109) —— 全是大户。
    只按 board 选源 = 高频车道把最能产校招岗的公司全漏在外面。

    ⚠️ 为什么要交必投清单：
    本车道是叠加在 daily-crawl 之上的**加密轮次**，不是全库提频。限定在必投清单（几十个源）
    才跑得快、也不会把无关站点打出限流。清单外的源照常走 daily-crawl，覆盖面不减。
    """
    producing = {str(x) for x in (producing_source_ids or [])}
    out: list[dict] = []
    for s in sources or []:
        if not s.get("enabled"):
            continue
        sid = str(s.get("id") or "")
        if s.get("board") not in CAMPUS_BOARDS and sid not in producing:
            continue
        if must_apply_matcher is not None and not must_apply_matcher(s.get("company") or ""):
            continue
        out.append(s)
    return out


def detect_surge(
    prev_count: Optional[int],
    curr_count: Optional[int],
    *,
    multiple: int = SURGE_MULTIPLE,
    delta: int = SURGE_DELTA,
) -> bool:
    """该源的校招岗数是否发生「开闸级」突增。

    `prev_count is None`（该源第一条快照）一律返回 False —— 没有基线就没有「突增」可言，
    否则每接入一个新源都会在当天误报一次开闸并触发无谓的全量重抓。
    """
    if prev_count is None or curr_count is None:
        return False
    if curr_count <= prev_count:
        return False
    # ⚠️ 倍数规则必须先挡住 prev_count == 0：`curr >= 0 * multiple` 恒成立，
    # 会把「0 → 3」这种毫无意义的抖动也判成开闸。零基线一律交给增量规则判。
    if prev_count > 0 and curr_count >= prev_count * multiple:
        return True
    return curr_count >= prev_count + delta


def coverage_ratio(inserted: Optional[int], reported_total: Optional[int]) -> Optional[float]:
    """入库数 / adapter 自报的官网总数。**拿不到自报总数时返回 None（测不了），不是 0。**

    诚实红线：不是所有 adapter 都自报总数（腾讯 Count / 美团 totalCount / 网易 total /
    阿里 totalCount 有，很多没有）。此时必须承认「无法校验」，绝不能拿 0 冒充「未抓全」
    或拿 1.0 冒充「已抓全」—— 前者制造假警报，后者把没校验说成校验过了。
    """
    if inserted is None or not reported_total or reported_total <= 0:
        return None
    return inserted / reported_total


def is_undercrawled(
    inserted: Optional[int],
    reported_total: Optional[int],
    threshold: float = COVERAGE_THRESHOLD,
) -> Optional[bool]:
    """是否没抓全。返回 None 表示无法校验（见 coverage_ratio 的诚实红线）。"""
    ratio = coverage_ratio(inserted, reported_total)
    if ratio is None:
        return None
    return ratio < threshold
