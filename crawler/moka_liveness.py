"""Moka 撤岗核验：「最近一轮抓全了的列表里没有」+「逐岗问详情请求两次都回已停」双条件判死。

为什么单独一条链（2026-10-12，库里 6,934 行逐岗真渲染核过，报告 docs/reviews/2026-10-12-moka-list-absent-active-rows.md）：
  · Moka 没开「列表缺席即撤岗」，岗从门户列表里消失后只能等浏览器巡检轮到它。巡检按源平摊名额
    （每条源每晚约 7 行，必投公司约 11 行），而 Moka 一个工作日约有 240 行掉出列表——
    宁德时代社招 2,712 行转一圈要八个月，库里攒了 6,879 行页面写着「已停止招聘」的在招岗。
  · 只凭列表缺席就下架（run.py 的 list-absence）证据上站得住：四轮完整列表、7,118 行缺席的岗全部已停、反例 0。
    但那是不可逆操作（expired 次日被 purge 永久删除），而「抓全」这个判断 2026-10-12 才有，占比安全闸在存量清掉后
    又基本不起作用（一个工作日里掉出最多的源是 13.5%，离 50% 很远）。所以缺席只当候选，再逐岗确认一次。

逐岗确认用的是详情页自己发的那个请求：POST {门户域名}/api/outer/ats-apply/website/job，
body {orgId, jobId, siteId, locale}，匿名可发。回包是 {data: 密文, necromancer: …}，**不解密，只看密文长度**：
  已停 / 不存在的岗 = 152 个字符；在招 = 1,708 个字符以上（中位 4,204）；其它长度、其它信封一律判不了。
  （英文 locale 的已停回包是 172、门户 id 不存在是 108——我们固定问中文，读到这些说明对方回包变了，不许当成已停。）
2026-10-12 拿 7,558 行（6,934 行缺席的 + 388 行在列的 + 239 行当天才掉出列表的）与逐岗真渲染的页面对拍：
页面写着已停的 7,118 行全部回 152，页面有申请按钮的 433 行全部回长密文，冲突 0。
这个请求按门户算：同一个岗换另一个门户 id 去问，回的也是 152（对用户来说这个链接就是打不开的）。

每条源的处置（逐岗，不抽样）：
  最近一轮抓取没抓全 / 失败 / 还在跑 / 太旧、库里这一轮见到的行数比抓取记录少一截、源地址带列表筛选、
  这一轮一个岗都没见到（没有阳性对照）                              → 整条源跳过（记原因，不算异常；留给浏览器巡检）
  行的链接不在这条源自己的门户下 / 认不出是 Moka 岗位链接          → 不动
  这一轮没见到 & 详情两次都读到已停                               → expire
  这一轮没见到 & 读到在招（对方重新开放了 / 在列表里但我们按口径不收） → 不动，单独计数
  这一轮没见到 & 判不了                                           → 不动

安全闸（任何一道不过，这条源本轮一行都不下架；有源被拦 → 进程退出码 2 → workflow 变红）：
  · 对照：这条源这一轮见到的岗里取 CONTROL_SAMPLE 个（只取它自己门户下的），必须全读到在招；再问一个不存在的岗位 id，
    必须读到已停。开头过一遍、每探 PROBE_CHUNK 个之后再过一遍——接口中途退化时它对在招岗也可能回短密文。
    读到已停的阳性对照可以换备用行顶上，最多 MAX_CONTROL_GONE 个（昨晚在列、白天刚关的岗，2026-10-21 起）；判不了的不换。
  · 「没见到却读到在招」的行 ≤ max(LIVE_UNLISTED_MIN, 在招行数 × MAX_LIVE_UNLISTED_FRACTION)：多了说明这条源的列表
    不是全集（没抓全却记了抓全 / 源地址带了我们没认出来的筛选）。2026-10-12 特斯拉一个白天重新开放了 12 个岗（在招 1,161）。
  · 占比闸：拟下架 > 在招行数 × --max-expire-fraction（默认 0.5，与 jobs_db.plan_absence_sweep 同一个函数、同一个下限）
    就不下架；清存量那一次由人显式放宽（当时李宁 168 / 328）。
  · 下架语句自带 last_seen_at < 那一轮开始时刻：核验期间又被抓取刷新过的行不动。
  · 整轮：能用的源一条都没有、或不到一半 → 退出码 2（抓取记录读空 / 昨晚重档没跑时，不许安静地报成功）；
    跑过总时限（--deadline-minutes）还没轮到的源记 deadline、同样变红——总时限早于 workflow 超时，报告和台账写得出来。
  · 默认 dry-run；--apply 才写库。只动 status='active' 的行。
  · 下架与巡检同口径：status=expired + confirmed_closed_at + CLOSED 事件；purge 删行前会立墓碑。
    对方日后把同一个岗重新开放，它会作为新岗重新入库（2026-10-12 一个白天就有 25 个岗这样）。

用法：python3 crawler/moka_liveness.py [--apply] [--max-expire-fraction 0.5] [--only <源地址里的一段>] [--out report.json]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import uuid
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import jobs_db  # noqa: E402
import ops_runs  # noqa: E402
import robots  # noqa: E402
from adapters.base import BaseAdapter  # noqa: E402
from adapters.china_ats import _moka_list_filter  # noqa: E402

MODULE = "moka_liveness"
DETAIL_PATH = "/api/outer/ats-apply/website/job"
GONE_LEN = 152
LIVE_MIN_LEN = 1000
CONTROL_SAMPLE = 3
MAX_CONTROL_GONE = 1
PROBE_CHUNK = 500
MAX_RUN_AGE_HOURS = 36
MIN_SEEN_FRACTION = 0.9
MIN_USABLE_FRACTION = 0.5
LIVE_UNLISTED_MIN = 5
MAX_LIVE_UNLISTED_FRACTION = 0.05
DEFAULT_MAX_EXPIRE_FRACTION = 0.5
DEFAULT_DEADLINE_MINUTES = 120
REQUESTS_PER_SECOND = float(os.environ.get("MOKA_LIVENESS_RPS", "4"))   # 2026-10-12 按 4 个 / 秒连发 7,800 个没被限
THREADS = int(os.environ.get("MOKA_LIVENESS_THREADS", "8"))            # 真正的速率由上面那个限速管，线程只是让等回包不排队
EXIT_BLOCKED = 2
# 只被这些原因拦下的 dry-run 不算失败：它们只是在报「按默认口径这一轮不会下架」。
_REPORT_ONLY_BLOCKS = ("too_many",)

DetailRef = namedtuple("DetailRef", "origin org site_id job_id")
# 一次从库里取回来的东西，都按 source_id 分组：在招行数 / 这一轮见到的在招行数 / 没见到的行 [(行 id, jd_url)] / 对照行 [jd_url]
Loaded = namedtuple("Loaded", "active seen candidates controls")

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_PORTAL_RE = re.compile(r"^(https?://[^/#?]+)/[^/#?]+/([^/#?]+)/(\d+)(?=[/#?]|$)")
_JOB_RE = re.compile(r"#/job/(" + _UUID + r")(?:[/?&].*)?$")


def portal_ref(url):
    """门户地址 → (域名, 租户, 门户 id)；认不出返回 None。"""
    m = _PORTAL_RE.match(url or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def detail_ref(jd_url):
    """岗位链接 → DetailRef；不是 Moka 岗位链接返回 None。"""
    portal = portal_ref(jd_url)
    m = _JOB_RE.search(jd_url or "")
    return DetailRef(*portal, m.group(1)) if portal and m else None


def fake_ref(ref):
    """同一个门户下一个不存在的岗位 id（阴性对照用）。由真 id 推出来，每次相同，便于复现。"""
    return ref._replace(job_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "jobradar-negative-control/" + ref.job_id)))


def answer_state(status_code, body):
    """详情请求的回答 → 'live' / 'gone' / 'unknown'。只认实测过的信封和两种长度，其余一律判不了。"""
    if status_code != 200 or not isinstance(body, dict):
        return "unknown"
    data = body.get("data")
    if not isinstance(data, str) or not isinstance(body.get("necromancer"), str):
        return "unknown"
    if len(data) == GONE_LEN:
        return "gone"
    if len(data) >= LIVE_MIN_LEN:
        return "live"
    return "unknown"


def _ts(value):
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def latest_runs(runs):
    """每条源开始时间最晚的那条抓取记录（不管收没收尾——还在跑的那一轮不能被上一轮盖住）。"""
    latest = {}
    for run in runs:
        sid = run.get("source_id")
        if sid and run.get("started_at") and (
                sid not in latest or _ts(run["started_at"]) > _ts(latest[sid]["started_at"])):
            latest[sid] = run
    return latest


def run_skip_reason(run, now):
    """这条源最近一轮抓取能不能当「完整列表」用；不能返回原因，能返回 None。"""
    if not run:
        return "no_run"
    if not run.get("finished_at") or run.get("status") == "running":
        return "run_in_progress"
    if run.get("status") not in ("success", "partial_success"):
        return "run_failed"
    if run.get("coverage_complete") is not True:
        return "list_incomplete"
    if _ts(run["started_at"]) < now - dt.timedelta(hours=MAX_RUN_AGE_HOURS):
        return "run_stale"
    return None


def usable_blocked_reason(n_sources, n_usable):
    """整轮闸：能核的源太少 = 这一轮基本没干活，不许报成功。"""
    if n_usable == 0:
        return f"no_usable_sources:0/{n_sources}"
    if n_usable < n_sources * MIN_USABLE_FRACTION:
        return f"few_usable_sources:{n_usable}/{n_sources}"
    return None


def controls_ok(control_refs, probe_fn, misses=None, swapped=None):
    """阳性：按顺序从这一轮见到的岗里凑 CONTROL_SAMPLE 个读到在招的（池子不足 CONTROL_SAMPLE 个就要池子全部）；
    阴性：同门户下不存在的岗位 id 必须读到已停。没有阳性对照 → False。

    读到「已停」的阳性对照可以换池子里的备用行顶上，最多 MAX_CONTROL_GONE 个、没有备用行就不换：昨晚还在列表、白天刚被
    关掉的岗会读成已停，这不是接口坏了（2026-10-21 森马实测）。接口真坏了时在招岗普遍读成短密文，换一个救不回来，照样拦。
    读到判不了的一个都不换。
    swapped 跨多次检查传同一个 list（一轮里开头 + 每块之后各查一遍）：一轮里换掉的必须始终是同一个岗——真关掉的岗不会
    忽而在招忽而已停，换来换去说明接口不可靠。misses 记没过的那一个（日志 / 报告用）。"""
    if not control_refs:
        return False
    need = min(CONTROL_SAMPLE, len(control_refs))
    swaps_left = min(MAX_CONTROL_GONE, len(control_refs) - need)
    earlier = set(swapped or ())
    live = 0
    for ref in control_refs:
        if live == need:
            break
        state = probe_fn(ref)
        if state == "live":
            live += 1
        elif state == "gone" and swaps_left and (ref.job_id in earlier or len(earlier) < MAX_CONTROL_GONE):
            swaps_left -= 1
            earlier.add(ref.job_id)
            if swapped is not None:
                swapped.append(ref.job_id)
        else:
            if misses is not None:
                misses.append(f"{ref.job_id}={state}")
            return False
    state = probe_fn(fake_ref(control_refs[0]))
    if state != "gone" and misses is not None:
        misses.append(f"negative={state}")
    return state == "gone"


def probe_all(refs, probe_fn, control_fn, *, chunk=PROBE_CHUNK, check_first=True, threads=THREADS):
    """分块探；开头过一遍对照（check_first=False = 上一遍刚过完，不重复），每块探完再过一遍。
    任何一遍不过 → (已探到的, False)，这一轮读到的都不算数。比亚迪那条（byd_liveness）是同一个做法。"""
    ids, states = sorted(set(refs)), {}
    if check_first and not control_fn():
        return states, False
    for start in range(0, len(ids), chunk):
        part = ids[start:start + chunk]
        if threads <= 1:
            states.update((ref, probe_fn(ref)) for ref in part)
        else:
            with ThreadPoolExecutor(threads) as ex:
                states.update(zip(part, ex.map(probe_fn, part)))
        if not control_fn():
            return states, False
    return states, True


def settle(first, second):
    """两次都读到 gone 才是 gone；第一次读到 live 就是 live；其余一律判不了。"""
    out = {}
    for ref, state in first.items():
        if state == "live":
            out[ref] = "live"
        elif state == "gone" and second.get(ref) == "gone":
            out[ref] = "gone"
        else:
            out[ref] = "unknown"
    return out


def plan(candidates, states):
    """纯函数。candidates=[(行 id, jd_url)]；states={DetailRef: 'gone'/'live'/'unknown'}。返回 [(action, 行 id)]。"""
    actions = []
    for row_id, jd_url in candidates:
        ref = detail_ref(jd_url)
        if ref is None:
            actions.append(("keep_unparsed", row_id))
            continue
        state = states.get(ref, "unknown")
        if state == "gone":
            actions.append(("expire", row_id))
        elif state == "live":
            actions.append(("keep_live_unlisted", row_id))
        else:
            actions.append(("keep_unknown", row_id))
    return actions


def live_unlisted_blocked_reason(n_live_unlisted, n_active):
    if n_live_unlisted > max(LIVE_UNLISTED_MIN, n_active * MAX_LIVE_UNLISTED_FRACTION):
        return f"list_not_full_set:{n_live_unlisted}/{n_active}"
    return None


def expire_blocked_reason(n_expire, n_active, max_fraction):
    """占比闸：与 run.py 的列表缺席撤岗用同一个判定（在招不足 8 行的小门户不设这道闸，否则它们永远下不了架）。"""
    action, reason = jobs_db.plan_absence_sweep(n_active, n_expire, apply=True, max_expire_fraction=max_fraction)
    return reason if action == "skip" else None


def reconcile_source(source, run, *, active, seen, candidates, controls, probe_fn, expire_fn, apply, max_fraction, now,
                     threads=THREADS):
    """单源：过抓取记录 → 对照 → 逐岗问两次 → 过闸 → （都过且 apply 时）写库。返回 (报告, 是否被闸拦下)。

    active / seen = 这条源在招行数 / 其中这一轮见到的；candidates=[(行 id, jd_url)] 这一轮没见到的在招行；
    controls=[jd_url] 这一轮见到的行；expire_fn(source_id, 行 id 列表, 那一轮开始时刻) → 真被改到的行数。"""
    rec = {"source_id": source["id"], "company": source.get("company")}
    reason = run_skip_reason(run, now)
    portal = portal_ref(source.get("source_url"))
    if not reason and portal is None:
        reason = "portal_unparsed"
    if not reason and _moka_list_filter(source.get("source_url") or ""):
        reason = "filtered_list"   # 源只接门户里筛出来的一部分：列表本来就不是全集
    if reason:
        rec["skipped"] = reason
        return rec, False
    rec["candidates"] = len(candidates)
    if not candidates:
        return rec, False
    rec["active"] = active
    found = run.get("jobs_found") or 0
    if seen < found * MIN_SEEN_FRACTION:
        # 抓取记录说这一轮入库了 found 行，库里这一轮被刷新的在招行却少一截：这条记录描述的不是库里的状态。
        # 留一成余量：这一轮之后被巡检下架的行不算在 seen 里。
        rec["skipped"] = f"seen_lt_found:{seen}/{found}"
        return rec, False

    own = [(row_id, url) for row_id, url in candidates
           if (detail_ref(url) or portal)[:3] == portal]   # 认不出的链接留给 plan 记成 keep_unparsed
    if len(own) < len(candidates):
        rec["keep_other_portal"] = len(candidates) - len(own)
    to_probe = sorted({ref for ref in (detail_ref(url) for _row_id, url in own) if ref})
    states = {}
    if to_probe:
        # 多带 MAX_CONTROL_GONE 行备用：读到已停的对照换下一行顶上（controls_ok 只在凑够之前才往后探，平时不多发请求）
        control_refs = [ref for ref in (detail_ref(url) for url in controls)
                        if ref and ref[:3] == portal][:CONTROL_SAMPLE + MAX_CONTROL_GONE]
        if not control_refs:
            rec["skipped"] = "no_listed_rows"   # 这一轮一个岗都没见到（门户清空了）：没有阳性对照，不替它下结论
            return rec, False

        misses, swapped = [], []

        def control():
            return controls_ok(control_refs, probe_fn, misses, swapped)

        first, ok = probe_all(to_probe, probe_fn, control, threads=threads)
        second = {}
        gone_once = [ref for ref, state in first.items() if state == "gone"]
        if ok and gone_once:
            second, ok = probe_all(gone_once, probe_fn, control, check_first=False, threads=threads)
        if swapped:
            rec["control_swapped"] = sorted(set(swapped))   # 换掉过的对照：频繁出现要回头看是不是接口在退化
        if not ok:
            rec["blocked"] = "control_failed"
            if misses:
                rec["control_miss"] = misses[-1]
            return rec, True
        states = settle(first, second)

    actions = plan(own, states)
    for action, _row_id in actions:
        rec[action] = rec.get(action, 0) + 1
    expire_ids = [row_id for action, row_id in actions if action == "expire"]
    rec["expire_ids"] = expire_ids

    reason = (live_unlisted_blocked_reason(rec.get("keep_live_unlisted", 0), active)
              or expire_blocked_reason(len(expire_ids), active, max_fraction))
    if reason:
        rec["blocked"] = reason
        return rec, True
    if apply and expire_ids:
        rec["expired"] = expire_fn(source["id"], expire_ids, _ts(run["started_at"]))
    return rec, False


def reconcile_all(sources, runs, loaded, *, probe_fn, expire_fn, robots_allowed, apply, max_fraction, now,
                  past_deadline, threads=THREADS):
    """逐源核。一条源出错 / 被拦不影响别的源；过了总时限还有候选没核的源记 deadline（会让整轮变红）。"""
    report = []
    for source in sources:
        sid = source["id"]
        rec = {"source_id": sid, "company": source.get("company")}
        candidates = loaded.candidates.get(sid, [])
        try:
            portal = portal_ref(source.get("source_url"))
            if candidates and past_deadline():
                rec["blocked"] = "deadline"
            elif candidates and portal and not robots_allowed(portal[0]):
                rec["skipped"] = "robots"
            else:
                rec, _blocked = reconcile_source(
                    source, runs.get(sid), active=loaded.active.get(sid, 0), seen=loaded.seen.get(sid, 0),
                    candidates=candidates, controls=loaded.controls.get(sid, []), probe_fn=probe_fn,
                    expire_fn=expire_fn, apply=apply, max_fraction=max_fraction, now=now, threads=threads)
        except Exception as exc:  # noqa: BLE001 - 这条源联网 / 写库任何一步挂了都算它本轮没核成
            rec["blocked"] = f"error:{type(exc).__name__}"
            sys.stderr.write(f"[moka-liveness] 核验失败 {source.get('company')}：{type(exc).__name__}: "
                             f"{jobs_db.redact_conn_error(exc)!s:.200}\n")
        report.append(rec)
        if rec.get("candidates") or rec.get("blocked"):
            print(f"  {rec.get('company')}: " + json.dumps(
                {k: v for k, v in rec.items() if k not in ("source_id", "company", "expire_ids")},
                ensure_ascii=False), flush=True)
    return report


def expire_rows(conn, source_id, ids, not_seen_since, record_events=None):
    """下架 + CLOSED 事件。只动这条源名下、仍是 active、且那一轮之后没再被抓取刷新过的行；返回真被改到的行数。"""
    if not ids:
        return 0
    now = jobs_db._now()
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set status='expired', confirmed_closed_at=%s, enrich_checked_at=%s "
            "where id = any(%s::uuid[]) and source_id = %s and status='active' and last_seen_at < %s "
            "returning id::text", (now, now, list(ids), source_id, not_seen_since))
        gone = [r[0] for r in cur.fetchall()]
    day = jobs_db._day(now)
    (record_events or jobs_db.record_job_events)(conn, [jobs_db.plan_close_event(j, source_id, day) for j in gone])
    return len(gone)


def exit_code(report, *, apply, run_blocked=None):
    """没有源被拦、整轮也没被拦 → 0。否则 2（CI 变红，要人看）；例外：dry-run 里只被占比闸拦——那只是报数。"""
    blocked = [r for r in report if r.get("blocked")]
    if blocked:
        print("::warning::[moka-liveness] 这些源被安全闸拦下，本轮没有下架它们的岗："
              + "; ".join(f"{r.get('company')}={r['blocked']}" for r in blocked), flush=True)
    if not report:
        print("::warning::[moka-liveness] 没有 enabled 的 moka 源", flush=True)
        return EXIT_BLOCKED
    if run_blocked:
        print(f"::warning::[moka-liveness] 整轮没核成：{run_blocked}（抓取记录读空 / 昨晚重档没跑 / 抓全率判定出了问题）",
              flush=True)
        return EXIT_BLOCKED
    if not blocked:
        return 0
    report_only = all(str(r["blocked"]).split(":")[0] in _REPORT_ONLY_BLOCKS for r in blocked)
    return 0 if (report_only and not apply) else EXIT_BLOCKED


class _Pacer:
    """全局限速：所有线程合起来每秒不超过 rate 个请求。"""

    def __init__(self, rate, clock=time.monotonic, sleep=time.sleep):
        self._gap, self._next, self._lock = 1.0 / rate, 0.0, threading.Lock()
        self._clock, self._sleep = clock, sleep

    def wait(self):
        with self._lock:
            now = self._clock()
            delay = self._next - now
            self._next = max(now, self._next) + self._gap
        if delay > 0:
            self._sleep(delay)


def probe(client, pacer, ref):
    """问一次详情请求 → 'live' / 'gone' / 'unknown'。网络错误和判不了的回答各重试，仍不行 = unknown。"""
    for attempt in range(3):
        pacer.wait()
        try:
            r = client.post(ref.origin + DETAIL_PATH,
                            json={"orgId": ref.org, "jobId": ref.job_id, "siteId": ref.site_id, "locale": "zh-CN"})
            try:
                body = r.json()
            except ValueError:
                body = None
            state = answer_state(r.status_code, body)
            if state != "unknown":
                return state
        except httpx.HTTPError:
            pass
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return "unknown"


# ── 以下是取数与编排里连库 / 连 Supabase 的部分：单测只钉 SQL 里不许丢的条件，真跑靠 dry-run 回读 ──────────

def load_sources(sb, only=""):
    rows = db.fetch_all_rows(
        lambda: sb.table("sources").select("id,company,source_url,adapter_name,enabled").eq("adapter_name", "moka"))
    return [r for r in rows if r.get("enabled") and (not only or only in (r.get("source_url") or ""))]


def load_runs(sb, source_ids, since):
    cols = "id,source_id,started_at,finished_at,status,jobs_found,reported_total,coverage_complete,coverage_stop_reason"
    runs = []
    for start in range(0, len(source_ids), 80):   # 源 id 走查询串，分批免得超长
        chunk = source_ids[start:start + 80]
        runs += db.fetch_all_rows(
            lambda: sb.table("crawl_runs").select(cols).in_("source_id", chunk).gte("started_at", since.isoformat()))
    return runs


# jobs 上按 source_id 的索引只有 jobs_active_liveness_by_source_idx (source_id, enrich_checked_at nulls first)
# where status='active' 这一条：三条 SQL 的 status 条件都要和 source_id 条件在一起，否则是全表扫。
_CANDIDATES_SQL = """
    select j.source_id::text, j.id::text, j.jd_url
    from unnest(%s::uuid[], %s::timestamptz[]) as r(source_id, run_start)
    join jobs j on j.source_id = r.source_id
    where j.status = 'active' and j.last_seen_at < r.run_start
    order by j.source_id, j.id
"""
_STATS_SQL = """
    select r.source_id::text,
           count(j.id) as active,
           count(j.id) filter (where j.last_seen_at >= r.run_start) as seen
    from unnest(%s::uuid[], %s::timestamptz[]) as r(source_id, run_start)
    left join jobs j on j.source_id = r.source_id and j.status = 'active'
    group by 1
"""
_CONTROLS_SQL = """
    select r.source_id::text, c.jd_url
    from unnest(%s::uuid[], %s::timestamptz[]) as r(source_id, run_start)
    cross join lateral (
        select jd_url from jobs j
        where j.source_id = r.source_id and j.status = 'active' and j.last_seen_at >= r.run_start
        order by j.enrich_checked_at asc nulls first limit %s) c
"""


def load_rows(conn, run_starts):
    """run_starts={source_id: 那一轮开始时刻}。先取没见到的行；行数统计和对照行只给有候选的源取。"""
    loaded = Loaded({}, {}, {}, {})
    ids = list(run_starts)
    if not ids:
        return loaded
    with conn.cursor() as cur:
        cur.execute(_CANDIDATES_SQL, (ids, [run_starts[s] for s in ids]))
        for sid, row_id, url in cur.fetchall():
            loaded.candidates.setdefault(sid, []).append((row_id, url))
        with_cand = [s for s in ids if s in loaded.candidates]
        if with_cand:
            starts = [run_starts[s] for s in with_cand]
            cur.execute(_STATS_SQL, (with_cand, starts))
            for sid, n_active, n_seen in cur.fetchall():
                loaded.active[sid], loaded.seen[sid] = int(n_active), int(n_seen)
            # 多取几行：对照只认这条源自己门户下的行，过滤之后再取前 CONTROL_SAMPLE 个
            cur.execute(_CONTROLS_SQL, (with_cand, starts, CONTROL_SAMPLE * 3))
            for sid, url in cur.fetchall():
                loaded.controls.setdefault(sid, []).append(url)
    return loaded


def _with_conn(fn):
    """库连接用完即关：逐岗问要几分钟到一小时，连接不留着空等（留着会被对端掐掉）。"""
    conn = jobs_db.get_conn()
    try:
        return fn(conn)
    finally:
        conn.close()


def _fraction(text):
    value = float(text)
    if not 0 <= value <= 1:   # nan 也过不了这个比较
        raise argparse.ArgumentTypeError("必须在 0~1 之间")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-expire-fraction", type=_fraction, default=DEFAULT_MAX_EXPIRE_FRACTION)
    ap.add_argument("--only", default="", help="只核源地址里含这一段的源")
    ap.add_argument("--deadline-minutes", type=float, default=DEFAULT_DEADLINE_MINUTES)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    started_at = jobs_db._now()
    now = dt.datetime.now(dt.timezone.utc)
    deadline = time.monotonic() + args.deadline_minutes * 60

    sb = db.get_supabase()
    sources = load_sources(sb, args.only)
    runs = latest_runs(load_runs(sb, [s["id"] for s in sources],
                                 now - dt.timedelta(hours=MAX_RUN_AGE_HOURS + 12)))
    usable = {s["id"]: _ts(runs[s["id"]]["started_at"]) for s in sources
              if not run_skip_reason(runs.get(s["id"]), now)}
    run_blocked = usable_blocked_reason(len(sources), len(usable)) if sources else None
    loaded = _with_conn(lambda conn: load_rows(conn, usable))
    print(f"[moka-liveness] enabled 源 {len(sources)} 个，最近一轮抓全可用 {len(usable)} 个，"
          f"这些源里没见到的在招行 {sum(len(v) for v in loaded.candidates.values())} 行 "
          f"(apply={args.apply}, max_expire_fraction={args.max_expire_fraction})", flush=True)

    pacer = _Pacer(REQUESTS_PER_SECOND)
    with httpx.Client(timeout=20, follow_redirects=False,
                      headers={"User-Agent": BaseAdapter.user_agent}) as client:
        report = reconcile_all(
            sources, runs, loaded, probe_fn=lambda ref: probe(client, pacer, ref),
            expire_fn=lambda sid, ids, since: _with_conn(lambda conn: expire_rows(conn, sid, ids, since)),
            robots_allowed=lambda origin: robots.check_robots(origin + DETAIL_PATH)["allowed"],
            apply=args.apply, max_fraction=args.max_expire_fraction, now=now,
            past_deadline=lambda: time.monotonic() > deadline)

    totals, skipped = {}, {}
    for rec in report:
        for k, v in rec.items():
            if isinstance(v, int) and not isinstance(v, bool):
                totals[k] = totals.get(k, 0) + v
        if rec.get("skipped"):
            reason = str(rec["skipped"]).split(":")[0]
            skipped[reason] = skipped.get(reason, 0) + 1
    totals.update(sources=len(report), usable=len(usable),
                  sources_blocked=sum(1 for r in report if r.get("blocked")))
    blocked_any = bool(totals["sources_blocked"]) or bool(run_blocked) or not sources
    print("[moka-liveness] 合计:", json.dumps(totals, ensure_ascii=False), "| 跳过的源:",
          json.dumps(skipped, ensure_ascii=False), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"apply": args.apply, "max_expire_fraction": args.max_expire_fraction, "blocked": blocked_any,
                       "run_blocked": run_blocked, "totals": totals, "skipped": skipped, "sources": report},
                      f, ensure_ascii=False, indent=1)
    if args.apply:
        metrics = dict(totals)
        metrics["skipped"] = skipped
        metrics["blocked"] = ",".join(sorted({str(r["blocked"]).split(":")[0] for r in report if r.get("blocked")}
                                             | ({run_blocked.split(":")[0]} if run_blocked else set())))
        if not ops_runs.record_ops_run(sb, MODULE, metrics, status="failed" if blocked_any else "success",
                                       started_at=started_at, finished_at=jobs_db._now()):
            print("::warning::[moka-liveness] 台账没写成（库已按上面的数字改过）", flush=True)
    return exit_code(report, apply=args.apply, run_blocked=run_blocked)


if __name__ == "__main__":
    sys.exit(main())
