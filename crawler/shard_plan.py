"""重档 enrich-crawl 的分片计划：按「预计耗时」装箱，由 plan job 算**一次**、各片共用同一份。

用法（enrich-crawl.yml 的 plan job）：
  python crawler/shard_plan.py --shard-count 6 --tier all --out shard-plan.json
各片：python crawler/run.py --shard-index N --shard-count 6 --shard-plan shard-plan.json

为什么不再按源数装箱（run._shard_by_host）：一片的墙钟 ≠ 源数，而是
    线程池墙钟（并发档：同主机一队串行、跨主机 6 线程并行） + 串行浏览器档逐个累加。
国聘 www.iguopin.com 28 个源同主机 → 一队、一个线程串行，这片线程池要 91~134 分钟；按源数它只
「重 28」，装箱器照样往这片塞 72 个浏览器源，而浏览器档要等线程池整体结束才开跑 → 跑完的晚上 136~176
分钟，2026-09-08/10/11/12 撞 180 被 GitHub 取消：浏览器档只开跑 35~45 个，27~37 个当晚一行 crawl_runs
都没有（moka 没卡住的晚上，其余 5 片 40~84 分钟就跑完闲着）。以上全部来自 crawl_runs 的 started_at/finished_at，
不来自 CI 日志——日志 stdout 块缓冲，被杀的片尾巴会丢，时间戳也是成批落的。

为什么必须 plan job 算一次、不能各片自己算：耗时来自 crawl_runs 历史，而那张表别的车道
（campus-crawl 每小时、daily-crawl）一直在写、gap_funnel 还会删行。6 个 runner 各自在不同时刻
读历史，算出的计划可能不一样 → 有的源两片都不抓、有的两片重抓。计划落成一个文件分发给各片，
「每个 key 恰好属于一片」才是构造上成立的，而不是赌 6 次读到的数据恰好一样。

不变量（与 run._shard_by_host 相同，别破坏）：
- 同一分片单位（run._shard_key_of：默认 host，多租户 moka 细到租户）的所有源落同一片，**不分档**；
- 映射只由计划文件 + crc32 决定，**禁止 Python hash()**（每进程加盐不同）；
- 计划里没有的 key（plan 之后才新增的源）按 crc32(key) 兜底，各片算出来一致。
"""
from __future__ import annotations

import argparse
import datetime as dt
import heapq
import json
import os
import re
import statistics
import sys
import zlib

PLAN_VERSION = 1

# 「一晚」= started_at 往前推 12 小时的 UTC 日期：重档 cron 在 UTC 18:00、实际常拖到 20~21 点才起、
# 跑到次日 0 点前后，这样同一轮不会被 UTC 零点劈成两晚。
NIGHT_SHIFT_HOURS = 12

# 取最近几晚的历史：每晚取「最长那次」，再取这几晚的上分位（理由见 estimate_source_seconds）。
HISTORY_NIGHTS = 7
ESTIMATE_QUANTILE = 0.75

# 完全没有历史、同 adapter 也没有可参照的源（新 adapter 的第一个源）。
DEFAULT_SOURCE_SECONDS = 60.0

# 预计墙钟超过它就在 CI 里打 ::warning::。估算刻意偏高：前向回测正常晚上 实际/预计 = 0.59~0.83
# （见 estimate_source_seconds），预计 170 ≈ 实际 100~140；再往上就是在 180 分钟超时边上了。
WARN_SHARD_MINUTES = 170.0

_TS_RE = re.compile(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d(?::?\d\d)?)?$")


def night_of(started_at: dt.datetime) -> dt.date:
    return (started_at - dt.timedelta(hours=NIGHT_SHIFT_HOURS)).date()


def _parse_ts(value) -> dt.datetime | None:
    """PostgREST 给的 timestamptz。⚠️ Postgres 会去掉小数尾零（`21:18:31.33364+00:00`），
    Python 3.9 的 fromisoformat 只认 3/6 位小数 → 这里先补齐再解析（CI 3.11 无所谓，本地测试是 3.9）。"""
    if isinstance(value, dt.datetime):
        ts = value
    else:
        m = _TS_RE.match(str(value or "").strip())
        if not m:
            return None
        date_s, time_s, frac, tz = m.groups()
        tz = tz or "+00:00"
        if tz == "Z":
            tz = "+00:00"
        elif len(tz) == 3:
            tz += ":00"
        elif ":" not in tz:
            tz = f"{tz[:3]}:{tz[3:]}"
        try:
            ts = dt.datetime.fromisoformat(f"{date_s}T{time_s}.{(frac or '0')[:6].ljust(6, '0')}{tz}")
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts


def nightly_max_seconds(rows) -> dict:
    """crawl_runs 行 → {source_id: {night: 当晚该源最长的一次耗时(秒)}}。

    同一晚同一个源常有好几行：重档全量富化那一次最长，campus-crawl / daily-crawl 只抓列表
    （CRAWL_DETAIL_CAP=0，国聘直接 skipped 1 秒）。取当晚最长的那次 = 取重档那次。
    没 finished_at（进程被杀留下的 running 占位符）的行不算：它不代表这个源要跑多久。"""
    out: dict = {}
    for r in rows:
        sid = r.get("source_id")
        st, fi = _parse_ts(r.get("started_at")), _parse_ts(r.get("finished_at"))
        if not sid or st is None or fi is None or fi < st:
            continue
        secs = (fi - st).total_seconds()
        nights = out.setdefault(sid, {})
        night = night_of(st)
        if secs > nights.get(night, -1.0):
            nights[night] = secs
    return out


def upper_quantile(values, q: float) -> float:
    """最近秩法分位数：第 ceil(q·n) 小的值。n=2 取大的那个、n=7 取第 6 个（去掉最大的一次）。
    不用线性插值那种会往小值偏的写法——这里低估比高估贵。"""
    ordered = sorted(values)
    rank = -(-int(round(q * 1000)) * len(ordered) // 1000)  # ceil(q·n)，避开浮点误差
    return ordered[min(max(rank, 1), len(ordered)) - 1]


def estimate_source_seconds(sources, history: dict, *, current_night: dt.date,
                            nights: int = HISTORY_NIGHTS) -> tuple[dict, dict]:
    """每个源的预计耗时（秒）。返回 (估计值, 统计口径)。

    取「最近 nights 晚里、每晚最长那次」的**上分位**（ESTIMATE_QUANTILE，最近秩法：7 晚取第 6 大）。
    三个口径拿 2026-09-06~09-13 八晚真实数据前向回测过（第 N 晚的计划只用 N 之前的历史，
    用第 N 晚每个源的真实耗时 + 线程池复刻给各片打分）：
    - 中位数：偏低。国聘那片预计 94 分钟、实际 114；被饿死的晚上**根本没有**重档那一行、
      只剩列表车道几秒的短行，中位数恰恰把那批被饿死的源估短；
    - 最大值：偏高约 2 倍（09-06 其余片预计 179、实际 70~82），一次偶发慢跑要记一周；
    - 上分位：09-06/07/09 三个完整晚上 实际/预计 = 0.59~0.83。
    三者装出来的最长片实际耗时相近（差别主要在国聘那片自己），选上分位是因为低估比高估贵：
    低估 = 往那片多塞 → 撞 180 被杀。
    ⚠️ 两个方向的盲区都存在：
    - 新出现的全体变慢预见不了（09-10 moka 刚卡 networkidle 的第一晚 实际/预计 最高 1.66）；
    - 历史里有全体变慢的晚上时会连带高估一周（09-13 预计 181、实际 44~107），那几天的超时预警
      是历史造成的，不是当晚要出事。
    只看 current_night 之前的晚上：当晚白天那些列表车道短行不完整。"""
    earliest = current_night - dt.timedelta(days=nights)
    est: dict = {}
    by_adapter: dict = {}
    for s in sources:
        per_night = history.get(s["id"]) or {}
        window = [v for n, v in per_night.items() if earliest <= n < current_night]
        if window:
            est[s["id"]] = upper_quantile(window, ESTIMATE_QUANTILE)
            by_adapter.setdefault(s.get("adapter_name") or "", []).append(est[s["id"]])
    defaulted_by_adapter = defaulted_global = 0
    for s in sources:
        if s["id"] in est:
            continue
        peers = by_adapter.get(s.get("adapter_name") or "")
        if peers:
            est[s["id"]] = statistics.median(peers)
            defaulted_by_adapter += 1
        else:
            est[s["id"]] = DEFAULT_SOURCE_SECONDS
            defaulted_global += 1
    stats = {"history_nights": nights,
             "with_history": len(sources) - defaulted_by_adapter - defaulted_global,
             "defaulted_by_adapter": defaulted_by_adapter,
             "defaulted_global": defaulted_global}
    return est, stats


def pool_wall_seconds(queue_seconds, workers: int) -> float:
    """复刻 run.run_crawl 的并发档：ThreadPoolExecutor.map 按队序派活，线程空了就领下一队。
    queue_seconds 必须按队序（主机首次出现的顺序）给。
    校验：09-06~09-13 共 38 个跑完的分片，「本函数 + 串行档累加」与真实 job 时长差 1~2 分钟（setup 开销）。"""
    workers = max(1, int(workers))
    free = [0.0] * workers
    for secs in queue_seconds:
        t = heapq.heappop(free)
        heapq.heappush(free, t + secs)
    return max(free) if queue_seconds else 0.0


class _Shard:
    __slots__ = ("index", "queues", "serial", "sources", "concurrent", "work", "pool")

    def __init__(self, index):
        self.index = index
        self.queues: dict = {}   # host -> [首现序号, 秒]
        self.serial = 0.0
        self.sources = 0
        self.concurrent = 0
        self.work = 0.0
        self.pool = 0.0          # 当前队列下的线程池墙钟（缓存，只在加并发档源时重算）

    def pool_with(self, extra_queues: dict, workers: int) -> float:
        if not extra_queues:
            return self.pool
        queues = {h: list(v) for h, v in self.queues.items()}
        _merge_queues(queues, extra_queues)
        return pool_wall_seconds([secs for _idx, secs in sorted(queues.values())], workers)


def _merge_queues(into: dict, extra: dict) -> None:
    for host, (idx, secs) in extra.items():
        if host in into:
            into[host][0] = min(into[host][0], idx)
            into[host][1] += secs
        else:
            into[host] = [idx, secs]


def plan_shards(sources, seconds: dict, *, shard_count: int, workers: int,
                key_fn, host_fn, is_concurrent_fn) -> dict:
    """贪心装箱（LPT 变体）：key 按预计总耗时降序，每个 key 放进「放进去之后预计墙钟最小」的那片。

    sources 必须是 run_crawl 里的顺序（本土优先排序之后），线程池的队序依赖它。
    同一个 key 的并发档与串行档源一起放（不分档），同 host 不会被两个 runner 同时抓。
    放「结果最小」（经典 LPT）而不是「增量最小」：国聘那片线程池里 5 个线程闲着，按增量算往里塞
    并发源「不花钱」，会把别片的活堆过去；国聘一旦跑得比估计慢，整片跟着一起被拖长。"""
    shard_count = max(1, int(shard_count))
    keys: dict = {}
    for idx, s in enumerate(sources):
        k = keys.setdefault(key_fn(s), {"queues": {}, "serial": 0.0, "sources": 0,
                                        "concurrent": 0, "work": 0.0})
        secs = float(seconds.get(s["id"], DEFAULT_SOURCE_SECONDS))
        k["sources"] += 1
        k["work"] += secs
        if is_concurrent_fn(s):
            k["concurrent"] += 1
            _merge_queues(k["queues"], {host_fn(s): [idx, secs]})
        else:
            k["serial"] += secs

    shards = [_Shard(i) for i in range(shard_count)]
    assignment: dict = {}
    for key, k in sorted(keys.items(), key=lambda kv: (-kv[1]["work"], kv[0])):
        best = None
        for sh in shards:
            pool = sh.pool_with(k["queues"], workers)
            rank = (pool + sh.serial + k["serial"], sh.work, sh.index)
            if best is None or rank < best[0]:
                best = (rank, sh, pool)
        _rank, sh, pool = best
        _merge_queues(sh.queues, k["queues"])
        sh.pool = pool
        sh.serial += k["serial"]
        sh.sources += k["sources"]
        sh.concurrent += k["concurrent"]
        sh.work += k["work"]
        assignment[key] = sh.index

    summary = []
    for sh in shards:
        top = sorted(((key, keys[key]["work"]) for key, i in assignment.items() if i == sh.index),
                     key=lambda kv: (-kv[1], kv[0]))[:5]
        summary.append({"index": sh.index, "sources": sh.sources,
                        "concurrent": sh.concurrent, "serial": sh.sources - sh.concurrent,
                        "est_minutes": round((sh.pool + sh.serial) / 60, 1),
                        "est_pool_minutes": round(sh.pool / 60, 1),
                        "est_serial_minutes": round(sh.serial / 60, 1),
                        "top_keys": [[key, round(secs / 60, 1)] for key, secs in top]})
    return {"version": PLAN_VERSION, "shard_count": shard_count, "workers": int(workers),
            "keys": assignment, "shards": summary}


def shard_of_key(key: str, planned: dict, shard_count: int) -> int:
    """key → 片号。计划里有就用计划；没有（plan 之后才加的源）或越界 → crc32 兜底。
    ⚠️ 兜底必须是跨进程确定的函数：别换成 hash()。"""
    shard = planned.get(key)
    if isinstance(shard, int) and not isinstance(shard, bool) and 0 <= shard < shard_count:
        return shard
    return zlib.crc32((key or "").encode("utf-8")) % shard_count


def load_plan(path: str, shard_count: int) -> dict:
    """读计划文件并校验。任何不对都**抛错**，由调用方让这一片直接失败——
    不许悄悄退回按源数分片：只要有一片退回、其余片用计划，映射就不一致（漏抓 + 重抓）。"""
    with open(path, encoding="utf-8") as f:
        plan = json.load(f)
    if not isinstance(plan, dict) or plan.get("version") != PLAN_VERSION:
        got = plan.get("version") if isinstance(plan, dict) else type(plan).__name__
        raise ValueError(f"分片计划版本不对：{got}（期望 {PLAN_VERSION}）")
    if plan.get("shard_count") != shard_count:
        raise ValueError(f"分片计划是按 {plan.get('shard_count')} 片算的，本次 --shard-count={shard_count}")
    if not isinstance(plan.get("keys"), dict) or not plan["keys"]:
        raise ValueError("分片计划里没有任何 key")
    return plan


# ── CLI（plan job）：只读 Supabase 的 sources + crawl_runs，不碰 jobs 库 ─────────────────────

def fetch_history_rows(supabase, since: dt.datetime) -> list:
    import db
    return db.fetch_all_rows(
        lambda: supabase.table("crawl_runs")
        .select("id,source_id,started_at,finished_at")
        .gte("started_at", since.isoformat()))


def build_plan(supabase, *, shard_count: int, workers: int, tier: str,
               now: dt.datetime | None = None) -> dict:
    import db
    import run
    from urllib.parse import urlparse

    now = now or dt.datetime.now(dt.timezone.utc)
    current_night = night_of(now)
    earliest = current_night - dt.timedelta(days=HISTORY_NIGHTS)
    since = dt.datetime.combine(earliest, dt.time(NIGHT_SHIFT_HOURS), tzinfo=dt.timezone.utc)

    concurrent, serial = run.select_tiers(db.get_sources(supabase), tier)
    concurrent_ids = {s["id"] for s in concurrent}
    # 与 run_crawl 同序：并发档与串行档各自保持本土优先后的原顺序；并发档的队序只看并发档内部。
    ordered = concurrent + serial
    rows = fetch_history_rows(supabase, since)
    est, stats = estimate_source_seconds(ordered, nightly_max_seconds(rows), current_night=current_night)
    plan = plan_shards(ordered, est, shard_count=shard_count, workers=workers,
                       key_fn=run._shard_key_of,
                       host_fn=lambda s: urlparse(s.get("source_url") or "").netloc,
                       is_concurrent_fn=lambda s: s["id"] in concurrent_ids)
    plan.update({"generated_at": now.isoformat(timespec="seconds"), "tier": tier,
                 "sources_total": len(ordered), "history_rows": len(rows),
                 "history_since": since.isoformat(timespec="seconds"), "estimate": stats})
    return plan


def render_summary(plan: dict) -> list:
    lines = [f"分片计划 v{plan['version']}：{plan.get('sources_total')} 源 → {plan['shard_count']} 片，"
             f"每片并发 {plan['workers']} 线程；历史 {plan.get('history_rows')} 行 {plan.get('estimate')}",
             "| 片 | 源数(并发/串行) | 预计分钟 | 线程池 | 串行档 | 最重的 key（预计分钟） |",
             "|---|---|---|---|---|---|"]
    for sh in plan["shards"]:
        top = "；".join(f"{k} {m}" for k, m in sh["top_keys"][:3])
        lines.append(f"| {sh['index']} | {sh['sources']} ({sh['concurrent']}/{sh['serial']}) | "
                     f"{sh['est_minutes']} | {sh['est_pool_minutes']} | {sh['est_serial_minutes']} | {top} |")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="重档分片计划（按预计耗时装箱）")
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--tier", choices=["all", "httpx", "browser"], default="all")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    import db
    workers = max(1, int(os.environ.get("CRAWL_CONCURRENCY", "6") or "6"))
    plan = build_plan(db.get_supabase(), shard_count=max(1, args.shard_count),
                      workers=workers, tier=args.tier)
    # 空计划必须让 plan job 自己失败、不产出文件：否则 job 显示成功 → 各片带着计划去 load_plan →
    # 6 片一起抛错、当晚零产出；plan job 失败才会走「各片一起退回按源数装箱」那条路。
    if not plan["keys"]:
        print(f"::error::[shard-plan] 读到 {plan.get('sources_total')} 个源、没有任何 key 可排片，"
              f"不写计划文件（各片将一起退回按源数装箱）。")
        return 1
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1, sort_keys=True)
    load_plan(args.out, plan["shard_count"])  # 各片用的就是这个校验；写出去的文件自己先过一遍

    lines = render_summary(plan)
    print("\n".join(lines))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for warning in plan_warnings(plan):
        print(f"::warning::[shard-plan] {warning}")
    return 0


def plan_warnings(plan: dict, threshold: float = WARN_SHARD_MINUTES) -> list:
    """两种「要撞 180」必须分开说，处置完全相反：
    - 单个 key 自己就超了（国聘一队越来越长）→ 装箱救不了，要提速这个源或放宽它的串行；
    - 没有哪个 key 超、是总量顶满了 → 加片，或者先查是不是某个 adapter 集体变慢了。
      ⚠️ 上分位估计会被近 7 晚里「全体变慢」的晚上拉高（09-10~09-12 moka 卡 networkidle 之后，
      09-14 这份计划 6 片全估 180.7，拿 09-13 各源真实耗时回放同一份计划只要 44~107），
      先看近几晚真实片耗时再决定。"""
    out = []
    for sh in plan["shards"]:
        for key, minutes in sh["top_keys"]:
            if minutes >= threshold:
                out.append(f"第 {sh['index']} 片的 {key} 自己预计就要 {minutes} 分钟（≥{threshold:.0f}，"
                           f"job 超时 180）：装箱救不了，要提速这个源或放宽它的同主机串行。")
    hot = [sh for sh in plan["shards"] if sh["est_minutes"] >= threshold]
    if hot:
        total = round(sum(sh["est_minutes"] for sh in plan["shards"]))
        out.append(f"{len(hot)}/{plan['shard_count']} 片预计 ≥{threshold:.0f} 分钟"
                   f"（最长 {max(sh['est_minutes'] for sh in hot)}，全部片合计 {total} 分钟）。"
                   f"估计取的是近 {HISTORY_NIGHTS} 晚上分位，有全体变慢的晚上会连带高估一周——"
                   f"先对照近几晚 enrich 各片真实耗时：真也在涨就加片，或查哪个 adapter 集体变慢。")
    return out


if __name__ == "__main__":
    sys.exit(main())
