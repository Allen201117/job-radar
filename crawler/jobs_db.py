"""crawler/jobs_db.py — Phase 1：jobs 热表读写直连自建香港 PostgreSQL（JOBS_DATABASE_URL）。

为何独立于 crawler/db.py：jobs 已从 Supabase(PostgREST) 迁到自建 PG，jobs 的读写改用直连 SQL(psycopg2)。
sources / crawl_runs / discovery_runs 仍留 Supabase，继续用 crawler/db.py（不动）。

canonical_jd_url 由 HK 库的 BEFORE INSERT/UPDATE 触发器自动维护（与 normalizer.canonicalize_jd_url 同口径），
写入端无需带。这里用同口径函数算 canon 来**查既有行**，行为与旧 db.py 完全一致：
  跨状态查 canonical、优先 active、命中即按 **同一行 id** update（复活 removed 漏看岗、保住 job_actions 外键引用；
  但 expired=detail 探活确认撤岗的强信号，列表重抓不复活它 → 见 _update_set_clause 的 status CASE）。

性能：直连 SQL 没有 PostgREST 的 URI 长度限制 → 一次 `WHERE canonical = ANY(%s)` 查全批；
  写入 INSERT 用 execute_values、UPDATE 用 execute_batch，均按 page 合并往返（爬虫在 GitHub Actions
  跨境连香港库，最小化往返是关键）。psycopg2 自动做 Python→PG 类型适配，无需手写 cast。
"""
import os
import atexit
import ipaddress
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from normalizer import canonicalize_jd_url, posting_identity
from recruitment_classify import annotate as _annotate_recruitment

# jobs 可写列（与 jobs-db/schema.sql 对齐）。canonical_jd_url 由触发器维护、search_doc v1 不填 → 都不在写入列。
_INSERT_COLS = (
    "id", "source_id", "company", "title", "location", "country_code", "job_scope",
    "job_type", "grad_class", "summary", "jd_url", "apply_url", "salary_text", "posted_at",
    "first_seen_at", "last_seen_at", "status", "content_hash", "experience", "education",
    "deadline", "sponsorship_signal", "enrich_fail_count", "enrich_checked_at",
    # 招聘类型物化（2026-09-03）：入库时就由 JS 权威规则算好，检索直接查这两列，
    # 不再让 SQL 用「正向信号并集」去近似（那套与 JS 的分层裁决结构不同，必然捞进注定被否决的岗）。
    "recruitment_category", "recruitment_explicit",
    # 职能物化（2026-09-15）：入库时由 classifyJobFunction（带 summary）算好，校招看板读列不再拉正文现算。
    # 与上面两列由同一次 _annotate_recruitment 调用产出。UPDATE 时归数据库触发器 jobs_guard_job_function 管。
    "job_function",
)
# update 时不动：主键 id / 首见时间 first_seen_at / enrich 子系统独占的 enrich_checked_at·enrich_fail_count。
# 后两者由 enrich_backlog 死活巡检+富化**直接 UPDATE**（非本 upsert）：列表重抓若把 enrich_checked_at 抹回
# NULL，而巡检按 enrich_checked_at nulls first 轮转 → 被抹的岗反复插队、sweep 永远追不上（81% never-checked 真因）。
_UPDATE_COLS = tuple(
    c for c in _INSERT_COLS
    if c not in ("id", "first_seen_at", "enrich_checked_at", "enrich_fail_count")
)

# 富化/抽取得到、但「列表重抓」常缺的内容字段：UPDATE 时新值为空则**保留旧值**，杜绝
# 「浏览器逐岗富化补好的 summary 被下一次列表重抓的空值抹掉」——moka 1% 覆盖根因（2026-06-20 查实：
# 每晚 backfill 补 ~8800 条，次日列表重爬 summary=None 全抹回 NULL，count_valid_active_jobs 永远上不去）。
# 仅当新值非空才覆盖（fresh 数据仍优先，如 beisen 列表自带 Duty/Require、httpx 大厂内联正文）。
_PRESERVE_IF_EMPTY = ("summary", "job_type", "experience", "education", "deadline", "salary_text",
                      # 分类降级时是 None（不是「判定为空」）——必须保留上一次算好的值，
                      # 否则一次 node 不可用就把全库这一列抹成 NULL（同 summary 被重抓抹掉的老坑）。
                      # job_function 同理（同一次 annotate 产出，同样会降级成 None）；UPDATE 最终仍归
                      # jobs_guard_job_function 触发器裁决，这里的 COALESCE 是与 recruitment_category 一致的第一层防护。
                      "recruitment_category", "job_function")

# 同样要防「重抓抹掉」，但列是**非文本类型**，不能套 NULLIF(%s,'')：
# NULLIF(2027, '') 会让 Postgres 把 '' 往 integer 强转 → invalid input syntax，整源写库炸掉。
# 非文本列的「空」就是 NULL，直接 COALESCE(%s, 列) 即可。
# grad_class：届别从标题/正文抽，列表页文本比详情页短，重抓时常抽不出来（None）。不保护的话，
# 富化阶段从完整 JD 抽到的「2027 届」会被次日列表重抓的 None 抹掉——与 summary 被抹的老坑同形态。
# recruitment_explicit 是 boolean，不能套 NULLIF(%s,'')（会触发 '' → boolean 强转报错），
# 与 grad_class 同走 COALESCE(%s, 列)。保护理由同 recruitment_category。
_PRESERVE_IF_NULL = ("grad_class", "recruitment_explicit")


def _update_set_clause(cols=_UPDATE_COLS) -> str:
    """构造 UPDATE 的 SET 子句。每列恰好消费一个 %s，占位符顺序与 _row_tuple(job, cols) 一致。
    - status：detail 探活确认撤岗（expired）的岗**黏住不复活**——wt~52%/hotjob~71% 的列表仍夹带已关闭岗
      （除身份字段外与在招岗无异），裸 status=%s 会把 sweep 判死的岗每天刷回 active（点开 404/已下线）。
      expired 留 expired、其余（removed/active）走 ELSE 仍刷 active（复活漏看岗、保 job_actions 外键）；
      ELSE 仍占一个 %s，故占位符总数不变。
    - 保留型富化字段：文本列走 COALESCE(NULLIF(%s,''), 列)，非文本列走 COALESCE(%s, 列)
      （NULLIF(整数, '') 会触发 '' → integer 强转报错，见 _PRESERVE_IF_NULL 注释）。防空值抹掉既有内容。
    - 其余字段：直接 %s 覆盖。"""
    def _one(c):
        if c == "status":
            return "status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE %s END"
        if c in _PRESERVE_IF_EMPTY:
            return f"{c} = COALESCE(NULLIF(%s, ''), {c})"
        if c in _PRESERVE_IF_NULL:
            return f"{c} = COALESCE(%s, {c})"
        return f"{c} = %s"
    return ", ".join(_one(c) for c in cols)


def _load_env():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env.local", override=False)
    load_dotenv(root / ".env", override=False)


_ssl_root_cert_file = None


def _materialize_ssl_root_cert() -> str:
    """将受控 CA 写入仅当前进程可读的临时文件，供 libpq verify-full 使用。"""
    global _ssl_root_cert_file
    if _ssl_root_cert_file:
        return _ssl_root_cert_file
    raw_ca = (os.environ.get("JOBS_DATABASE_SSL_CA") or "").strip()
    if not raw_ca:
        raise RuntimeError("JOBS_DATABASE_SSL_CA 未配置：拒绝不校验证书身份的 jobs 数据库连接。")
    pem = raw_ca.replace("\\n", "\n")
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="job-radar-jobs-db-ca-", suffix=".pem", delete=False
    )
    try:
        handle.write(pem)
        handle.flush()
        os.chmod(handle.name, 0o600)
    finally:
        handle.close()
    _ssl_root_cert_file = handle.name
    atexit.register(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
    return handle.name


def strict_tls_kwargs(dsn: str, root_cert_path: str, certificate_servername: str = None) -> dict:
    """生成 psycopg2/libpq 严格 TLS 参数；IP 端点用 hostaddr 连接、host 校验证书名。"""
    parsed = urlparse(dsn)
    endpoint_host = parsed.hostname
    if not endpoint_host:
        raise RuntimeError("JOBS_DATABASE_URL 缺少数据库主机。")
    servername = (certificate_servername or "").strip() or endpoint_host
    kwargs = {"sslmode": "verify-full", "sslrootcert": root_cert_path}
    if servername != endpoint_host:
        try:
            ipaddress.ip_address(endpoint_host)
        except ValueError as exc:
            raise RuntimeError(
                "JOBS_DATABASE_TLS_SERVERNAME 与 DNS host 不一致；请让数据库证书 SAN 匹配连接地址。"
            ) from exc
        kwargs.update({"host": servername, "hostaddr": endpoint_host})
    return kwargs


# ── 跨境链路自愈（2026-07-26 加）────────────────────────────────────────────
# 爬虫跑在 GitHub Actions（Azure 海外）连腾讯云香港库，这条跨境链路会偶发丢包/被中间设备掐断。
# 连接层不自愈就会放大成两类 CI 失败（均已实测）：
#   ① 建连时一次 TLS 握手抖动 → `server closed the connection unexpectedly` → 整片 exit 1。
#      enrich-backlog 12 片矩阵里每天有 1 片这样挂（同一时刻其余 11 片连得好好的 = 不是库的问题）。
#   ② 长跑任务的连接被静默掐断后，psycopg2 把 conn 标 closed，后续每次写都 InterfaceError。
#      enrichment-crawl 实测连接 20:09 断掉后，剩余 ~1h50m 一行都没写进去，还烧满 180min 超时。
# 对策：建连重试（治①）+ TCP keepalive（治②的成因）+ 调用方持有的连接断了要重连（治②的后果）。
_CONNECT_ATTEMPTS = 7
_CONNECT_BACKOFF = (2, 5, 10, 20, 30, 60)  # 第 n 次失败后等几秒再试；长度 = _CONNECT_ATTEMPTS - 1（合计 127s）

# 跨境建连报错里带香港库的公网 IP + 端口（psycopg2 原文形如
# `connection to server at "<公网IP>", port <端口> failed: ...`）。本仓库是 PUBLIC，
# Actions 日志全网可读 → 打印/抛出前必须脱敏（红线见 CLAUDE.md「公开仓库红线」）。
_REDACTIONS = (
    (re.compile(r'(\bat )"[^"]*"'), r'\1"<jobs-db>"'),
    (re.compile(r'(\bhost name )"[^"]*"'), r'\1"<jobs-db>"'),
    (re.compile(r'(\bport )\d+'), r'\1<redacted>'),
)


class JobsDbUnreachable(psycopg2.OperationalError):
    """重试预算烧光仍连不上香港库 —— 「够不着库」，不是「库里出错」。

    单列一个类型，是为了让调用方能把这两件事分开处置：
      · 够不着库：CI 矩阵里多半是**单个 runner 的出口 IP 被路径上掐掉**（2026-08-08 实测
        同一轮 12 个分片里 11 个连得好好的，只有 1 片全程 RST），重试再久也没用，
        而队列是幂等的、下一轮自然补上 → 该记台账、不该把整轮 CI 拖红。
      · 库里出错（SQL 错、约束冲突…）：真 bug，必须炸。
    继承 psycopg2.OperationalError，所以既有的 `except OperationalError` 全部照常工作。
    """


def redact_conn_error(exc):
    """把建连异常里的主机/端口抹掉，返回同类型的新异常（类型不变，调用方的 except 不受影响）。"""
    message = str(exc)
    for pattern, replacement in _REDACTIONS:
        message = pattern.sub(replacement, message)
    return type(exc)(message)

# libpq TCP keepalive：空闲时让内核主动探活，抢在跨境 NAT/防火墙表项超时前把连接刷活；
# 真断了也能在 ~80s 内报错，而不是卡到 TCP 默认的十几分钟（实测出现过 Connection timed out 长挂）。
_KEEPALIVE_KWARGS = {
    "connect_timeout": 15,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}


def get_conn():
    """直连自建香港 jobs 库。autocommit=True（与 supabase-py 每请求即提交语义一致；爬虫多为单条/批写）。

    建连失败按 _CONNECT_BACKOFF 重试——跨境链路抖一下不该让整个 CI 分片挂掉。
    只重试 OperationalError（网络/握手类）；配置错、认证失败等直接抛，不做无意义重试。"""
    _load_env()
    dsn = os.environ.get("JOBS_DATABASE_URL")
    if not dsn:
        raise RuntimeError("JOBS_DATABASE_URL 未配置（自建香港 jobs 库连接串）。")
    root_cert_path = _materialize_ssl_root_cert()
    tls_kwargs = strict_tls_kwargs(
        dsn,
        root_cert_path,
        os.environ.get("JOBS_DATABASE_TLS_SERVERNAME"),
    )
    tls_kwargs.update(_KEEPALIVE_KWARGS)

    last_exc = None
    for attempt in range(_CONNECT_ATTEMPTS):
        try:
            conn = psycopg2.connect(dsn, **tls_kwargs)
            conn.autocommit = True
            if attempt:
                print(f"[jobs_db] 建连第 {attempt + 1} 次尝试成功（前 {attempt} 次跨境抖动已重试）")
            return conn
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt >= _CONNECT_ATTEMPTS - 1:
                break
            wait = _CONNECT_BACKOFF[attempt]
            print(f"[jobs_db] 建连失败({type(exc).__name__}: {redact_conn_error(exc)})，{wait}s 后重试 "
                  f"({attempt + 2}/{_CONNECT_ATTEMPTS})")
            time.sleep(wait)
    raise JobsDbUnreachable(str(redact_conn_error(last_exc))) from None


def conn_alive(conn) -> bool:
    """连接是否还可用。psycopg2 在链路断掉后把 conn.closed 置非 0，之后任何 cursor() 都抛
    `InterfaceError: connection already closed` —— 缓存长连接的调用方据此判断该不该重连。
    注意：closed==0 但对端已消失的窗口仍存在（那一次操作会抛 OperationalError 并把 closed 置位），
    下一次调用即可自愈；keepalive 负责把这个窗口压到最小。"""
    return conn is not None and getattr(conn, "closed", 1) == 0


def live_conn(conn, make_conn=None):
    """返回一个可用连接：给定的 conn 还活着就复用，断了就重新建一条（长跑任务的自愈入口）。"""
    if conn_alive(conn):
        return conn
    if conn is not None:
        print("[jobs_db] 检测到连接已断，重连香港库")
        try:
            conn.close()
        except Exception:
            pass
    return (make_conn or get_conn)()


def enabled() -> bool:
    """配了 JOBS_DATABASE_URL 即用自建香港库；否则各 consumer 回退 Supabase。"""
    _load_env()
    return bool(os.environ.get("JOBS_DATABASE_URL"))


def fetch_all(conn, sql, params=None) -> list:
    """只读查询 → dict 行列表（供爬虫各 consumer 写自己的 jobs SQL；sources/crawl_runs 仍走 Supabase）。"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def execute(conn, sql, params=None) -> int:
    """写语句 → 受影响行数。"""
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def _now():
    return datetime.now(timezone.utc)


# ── 岗位生命周期事件（job_events，02 spec §5）──────────────────────────────
# append-only 里程碑：只记关键转折，不记心跳。事件 best-effort——写失败只 warning，绝不影响 jobs upsert。
# event_key 幂等去重（FIRST_SEEN/OFFICIAL_POSTED 一辈子一条；CONFIRMED_OPEN/CLOSED/REAPPEARED 按天）。

def _day(now=None):
    return (now or _now()).date().isoformat()


def plan_upsert_events(*, job_id, source_id, old_status, old_posted_at, new_status, new_posted_at, day):
    """纯函数：据 list upsert 前后状态算应记的里程碑（FIRST_SEEN/OFFICIAL_POSTED/REAPPEARED）。
    old_status=None ⇒ 本次是 insert（新岗）。返回 [(event_key, event_type, job_id, source_id, payload)]。
    规则（02 spec §5.1）：
      · insert → FIRST_SEEN（一辈子一条）；若已拿到官方发布时间 → OFFICIAL_POSTED。
      · update 且旧无 posted_at、新有 → OFFICIAL_POSTED（一辈子一条）。
      · update 且 old_status=='removed' 且 new_status=='active' → REAPPEARED（按天）。
        ⚠️ old_status=='expired' 一律不产生 REAPPEARED（保 expired sticky 不变量）。"""
    events = []
    if old_status is None:
        events.append((f"FIRST_SEEN:{job_id}", "FIRST_SEEN", job_id, source_id, {}))
        if new_posted_at:
            events.append((f"OFFICIAL_POSTED:{job_id}", "OFFICIAL_POSTED", job_id, source_id, {}))
        return events
    if (not old_posted_at) and new_posted_at:
        events.append((f"OFFICIAL_POSTED:{job_id}", "OFFICIAL_POSTED", job_id, source_id, {}))
    if old_status == "removed" and new_status == "active":
        events.append((f"REAPPEARED:{job_id}:{day}", "REAPPEARED", job_id, source_id, {}))
    return events


def plan_close_event(job_id, source_id, day):
    """探活/巡检确认撤岗 → CLOSED（按天，一次下架一条）。"""
    return (f"CLOSED:{job_id}:{day}", "CLOSED", job_id, source_id, {})


def plan_confirm_event(job_id, source_id, day):
    """逐岗核验确认仍在招 → CONFIRMED_OPEN（按天去重，不每次心跳都写）。"""
    return (f"CONFIRMED_OPEN:{job_id}:{day}", "CONFIRMED_OPEN", job_id, source_id, {})


# ── list-absence 探活（02 spec / 2026-06-28 编排改造 §4 A2）────────────────────
# 思路：某源本次**抓全**(adapter.fetch_complete=True)后，仍 active 但 last_seen_at < 本次开抓时刻 cutoff
# 的岗 = 本次全量列表里没出现 = 已下架。比逐岗 detail 探活省（一次列表抓取顺带探活），但**只对返全量
# 在招岗、且确实翻到底的源安全**（截断/夹带已关闭岗的源会误杀 → 见 §5 不变量1、记忆 job-radar-job-
# expiry-closed-detection「通用 staleness sweep 不可行」）。故双闸：① adapter 显式 supports_absence_
# liveness 且 fetch_complete ② 占比安全闸（plan_absence_sweep）③ env LIVENESS_ABSENCE_APPLY 默认 dry-run。

def plan_absence_sweep(active_count, candidate_count, *, apply, max_expire_fraction=0.5, min_active_floor=8):
    """纯函数：据「本源 active 总数 / 拟下架(列表缺席)数 / 是否落库」决定这轮怎么走。
    返回 (action, reason)，action ∈ {'noop','skip','dry_run','apply'}。
    安全闸：拟下架占比 > max_expire_fraction 且 active 可观(≥min_active_floor) → 'skip'
    （防 httpx 偶发空/半量数据把整源误判下架；宁可这轮不动，下次抓全再说）。"""
    if candidate_count <= 0:
        return ("noop", "no_absent")
    if active_count >= min_active_floor and candidate_count > active_count * max_expire_fraction:
        return ("skip", f"too_many:{candidate_count}/{active_count}")
    return (("apply" if apply else "dry_run"), "ok")


def sweep_absent_jobs(conn, source_id, cutoff, *, apply=True, max_expire_fraction=0.5):
    """list-absence 探活：active 且 last_seen_at < cutoff（本源开抓前时刻）的岗 → expired + CLOSED 事件。
    本次 upsert 把所有再见到的岗 last_seen_at 刷成 > cutoff，故 < cutoff 的即「本次列表缺席」。
    仅 run.py 在 adapter.fetch_complete 时调用；apply=False 为 dry-run（只数不改）。
    返回 {'active','candidates','expired','action'}。"""
    sid = str(source_id)
    with conn.cursor() as cur:
        cur.execute("select count(*) from jobs where source_id = %s and status = 'active'", (sid,))
        active = cur.fetchone()[0]
        cur.execute(
            "select id from jobs where source_id = %s and status = 'active' and last_seen_at < %s",
            (sid, cutoff))
        cand_ids = [str(r[0]) for r in cur.fetchall()]
    action, _reason = plan_absence_sweep(
        active, len(cand_ids), apply=apply, max_expire_fraction=max_expire_fraction)
    result = {"active": active, "candidates": len(cand_ids), "expired": 0, "action": action}
    if action != "apply":
        return result
    now = _now()
    day = _day(now)
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set status = 'expired', confirmed_closed_at = %s, enrich_checked_at = %s "
            "where id = any(%s::uuid[]) and status = 'active'", (now, now, cand_ids))
        result["expired"] = cur.rowcount
    record_job_events(conn, [plan_close_event(jid, source_id, day) for jid in cand_ids])
    return result


def retire_posted_before(conn, source_id, cutoff_date) -> int:
    """按租户年限口径下架：本源 active 且发布日（北京时间）早于 cutoff_date 的岗 → removed。
    不是撤岗（岗可能还在招，只是超出口径），所以用可逆的 removed、不写 expired：expired 会被
    purge-expired 次日永久删除。日后同一行又被抓回（口径变了）时 upsert 会把它置回 active。
    发布日为空的行不动（口径在入库时已挡掉这种行，这里不替它下结论）。返回受影响行数。"""
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set status = 'removed' where source_id = %s and status = 'active' "
            "and posted_at is not null and (posted_at at time zone 'Asia/Shanghai')::date < %s",
            (str(source_id), cutoff_date))
        return cur.rowcount


def retire_out_of_policy(conn, jd_urls) -> int:
    """按抓取口径下架：adapter 这一轮在对方列表里见到、但按口径不再收的岗（如 moka 超过发布年限的），
    库里还是 active 的 → removed。返回受影响行数。

    和 retire_posted_before 是同一件事的另一个入口：那个按库里的 posted_at 认，这个按链接认——moka 不写
    posted_at，发布日期只在卡片上，只有 adapter 知道哪些岗超龄。
    用可逆的 removed、不写 expired（岗多半还在招，只是超出口径；expired 次日会被 purge-expired 永久删除）。
    日后岗被重新发布、adapter 又收它时，upsert 会把同一行置回 active。
    只动 active 行（走 canonical 的 active 唯一索引）；这些链接这一轮没进 upsert，不存在先下架又被写回。"""
    canons = sorted({canonicalize_jd_url(u) for u in jd_urls if u})
    if not canons:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set status = 'removed' where status = 'active' and canonical_jd_url = any(%s)",
            (canons,))
        return cur.rowcount


def clear_deadlines(conn, jd_urls) -> int:
    """把这些岗在库里的截止日清掉，返回受影响行数。只给「对方明确没有截止日」的岗用
    （RawJob.deadline_absent，见 adapters/base.py）。

    为什么要单独一步：deadline 在 _PRESERVE_IF_EMPTY 里，upsert 时新值为空会保留旧值——那是为了不让
    一次瘦 payload 抹掉更完整的正文里抽出的截止日；代价是 adapter 永远撤不回一个旧值。wt / hotjob
    2026-10-10 手工清掉的 41,605 行假截止日就是这么攒出来的。
    只动 active 行（走 canonical 的 active 唯一索引）；下架行日后复活，下一轮抓取再清。
    平时没有旧值可清，`deadline is not null` 让它是 0 行更新。"""
    canons = sorted({canonicalize_jd_url(u) for u in jd_urls if u})
    if not canons:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set deadline = null where status = 'active' and deadline is not null "
            "and canonical_jd_url = any(%s)",
            (canons,))
        return cur.rowcount


def record_job_events(conn, events) -> int:
    """best-effort 批量插 job_events（event_key 幂等 → on conflict do nothing）。
    写失败只 warning、返回 0，**绝不抛**（事件失败不许影响 jobs upsert，02 spec §5.3）。"""
    if not events:
        return 0
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "insert into job_events (event_key, event_type, job_id, source_id, payload) values %s "
                "on conflict (event_key) do nothing",
                [(k, t, jid, sid, psycopg2.extras.Json(p or {})) for (k, t, jid, sid, p) in events],
            )
        return len(events)
    except Exception as e:  # noqa: BLE001 — 事件 best-effort，任何错都不许炸穿 upsert
        print(f"  [job_events] 写入失败(忽略,不影响 upsert): {e}")
        return 0


def mark_reopened_from_closures(cur, canons) -> int:
    """把「刚以新 uuid 插进来、但 canonical 在墓碑里」的岗记一笔，返回命中条数。

    这是 F1 的**度量**那一半（2026-09-08）：purge 每天物理删掉约 2,871 行，删掉的同时
    `job_events` 的 CLOSED 事件被 CASCADE 一起带走 → 按 canonical 查不到任何东西 →
    列表下次再见到同一个链接就当新岗插入。job_closures 保住了关闭证据，这里负责数「它真的回来了几次」。

    ⚠️ 刻意**只记不拦**：公司确实会重开同一个岗位链接，命中墓碑就拒收 = 把真机会永久删掉，
    违反「宁可漏判不可错杀」。先拿到真实复活率，再谈要不要拦——没有数字的拦截策略都是拍脑袋。
    ⚠️ fail-open：墓碑表还没建（迁移未跑）或写失败一律吞掉，绝不能因为一个观测功能拖垮入库主链路。
    """
    canons = [c for c in (canons or []) if c]
    if not canons:
        return 0
    try:
        cur.execute(
            "update job_closures set reopened_at = now(), reopen_count = reopen_count + 1 "
            "where canonical_jd_url = any(%s) returning canonical_jd_url", (canons,))
        hits = cur.fetchall()
    except Exception as e:
        print(f"[job_closures] 复活标记跳过（不影响入库）：{type(e).__name__}: {str(e)[:80]}")
        return 0
    if hits:
        print(f"::warning::[job_closures] {len(hits)} 个已确认撤岗的链接又被当新岗插入 "
              f"（F1 复活；例：{hits[0][0][:110]}）")
    return len(hits)


def _find_existing_id_by_canonical(cur, canon):
    """按 canonical_jd_url 跨状态查既有行 id；多行优先 active（同旧 db.py，保复活语义）。"""
    cur.execute("select id, status from jobs where canonical_jd_url = %s", (canon,))
    rows = cur.fetchall()
    if not rows:
        return None
    for jid, status in rows:
        if status == "active":
            return jid
    return rows[0][0]


# ── 同一个帖子换了链接（2026-10-12）────────────────────────────────────────────
# ❌ Workday 改了帖子的主地点，链接里的地点段跟着变，旧链接照样能开（对方只按最后一段找帖子）。
#    列表重抓按新链接查 canonical 查不到 → 插一行新的；旧链接那一行再也不被列表看到，逐岗探活却每次都回 200
#    → 同一个岗两行都在招。清存量之前全库在招里这样的有 587 组 / 多出 610 行，最早的挂了三个半月。
# ✅ 写库时多问一句「本源在招行里有没有同一个帖子的旧链接」（帖子身份见 normalizer.posting_identity）：
#    · 新链接还没有行 → 把最早的那条旧行**原地**换成新链接（保住 id / first_seen_at / 用户的收藏与投递）；
#    · 新链接已经有行 → 旧行下架成 removed，最早的 first_seen_at 记到留下的那一行上。
# 判「旧」只凭一条：同一个帖子、这一轮列表给的是另一个链接。不看 fetch_complete——帖子身份在对方站内唯一，
# 列表没翻全也不影响「这个帖子现在的链接是哪一个」。

def _posting_last_segment(canon):
    return str(canon).split("?", 1)[0].rsplit("/", 1)[-1]


def _fetch_posting_siblings(cur, items) -> list:
    """本批里认得出帖子身份的岗，在库里同源、在招、链接末段相同的行（含它自己）。认不出身份的批次不发查询。"""
    want = {}  # source_id → 末段集合
    for canon, job in items:
        sid = job.get("source_id")
        if canon and sid and posting_identity(canon):
            want.setdefault(str(sid), set()).add(_posting_last_segment(canon))
    if not want:
        return []
    segments = sorted(set().union(*want.values()))
    # 末段只是粗筛（走 source_id 的在招部分索引，单源至多几千行），是不是同一个帖子由 plan_moved_postings 拿同一个函数再判。
    cur.execute(
        "select id, canonical_jd_url, first_seen_at, posted_at from jobs "
        "where status = 'active' and source_id = any(%s::uuid[]) "
        "and split_part(split_part(canonical_jd_url, '?', 1), '/', -1) = any(%s)",
        (sorted(want), segments))
    return [{"id": r[0], "canonical_jd_url": r[1], "first_seen_at": r[2], "posted_at": r[3]} for r in cur.fetchall()]


def plan_moved_postings(items, existing, siblings) -> dict:
    """纯函数：这一批里哪些岗在库里留着旧链接的行，各自怎么处置。

    items     [(canon, job)]——本批（已按 canonical 去重）
    existing  {canon: {"id", "status", ...}}——按 canonical 查到的既有行（任何状态）
    siblings  _fetch_posting_siblings 的结果
    返回 {"relink": {canon: 旧行}, "retire": [旧行 id], "first_seen": {留下那行的 id: 最早的 first_seen_at}}。

    不处置的三种情况（都留给下一轮）：
      · 同一个帖子这一轮出现了两个链接（并集查询之间对方正好改了地点）——分不出哪个是现在的；
      · 库里那一行的链接这一轮列表里还在——它不是旧链接；
      · 新链接上的行是 expired——探活刚判它撤了、列表重抓不复活它（见 _update_set_clause），
        这时把旧行也下架，这个帖子就一行在招的都没有了。
    """
    plan = {"relink": {}, "retire": [], "first_seen": {}}
    batch_canons = {c for c, _ in items if c}
    canons_of = {}  # 帖子身份 → 本批里它的链接
    for canon, _job in items:
        ident = posting_identity(canon) if canon else None
        if ident:
            canons_of.setdefault(ident, []).append(canon)
    stale = {}  # 帖子身份 → 库里的旧链接行
    for row in siblings:
        if row["canonical_jd_url"] in batch_canons:
            continue
        ident = posting_identity(row["canonical_jd_url"])
        if ident in canons_of:
            stale.setdefault(ident, []).append(row)
    for ident, rows in stale.items():
        canons = canons_of[ident]
        if len(canons) != 1:
            continue
        canon = canons[0]
        # 最早首见的在前；first_seen_at 为空的排最后（当不了「最早」的证据），再按 id 定序保证每次算出同一个结果。
        rows = sorted(rows, key=lambda r: (r["first_seen_at"] is None, r["first_seen_at"] or 0, str(r["id"])))
        ex = existing.get(canon)
        if ex is None:
            plan["relink"][canon] = rows[0]
            plan["retire"] += [r["id"] for r in rows[1:]]
        elif ex.get("status") != "expired":
            plan["retire"] += [r["id"] for r in rows]
            if rows[0]["first_seen_at"] is not None:
                plan["first_seen"][ex["id"]] = rows[0]["first_seen_at"]
    return plan


def _apply_moved_postings(cur, plan) -> None:
    """落 plan_moved_postings 里「下架旧行 / 带上最早首见」两步（原地换链接那一步走正常的 UPDATE）。
    放在本批 upsert 成功之后：upsert 失败时旧行原样留着，不会出现新行没写成、旧行先下架。"""
    if plan["retire"]:
        # removed 可逆、不进 purge（同 retire_out_of_policy）：岗没撤，只是这一行的链接不是它现在的链接。
        cur.execute("update jobs set status = 'removed' where status = 'active' and id = any(%s::uuid[])",
                    ([str(i) for i in plan["retire"]],))
    for jid, first_seen in plan["first_seen"].items():
        cur.execute("update jobs set first_seen_at = least(first_seen_at, %s) where id = %s", (first_seen, jid))
    if plan["relink"] or plan["retire"]:
        example = next(iter(plan["relink"].values()), None)
        print(f"    [posting-move] relinked={len(plan['relink'])} retired={len(plan['retire'])}"
              + (f"（例：{str(example['canonical_jd_url'])[-90:]}）" if example else ""))


def _row_tuple(job: dict, cols, **overrides):
    """把 job dict 投影成 cols 顺序的元组（缺列补默认）；overrides 覆盖具体列值。"""
    d = dict(job)
    d.setdefault("status", "active")
    d.setdefault("enrich_fail_count", 0)
    d.update(overrides)
    return tuple(d.get(c) for c in cols)


def upsert_job(conn, job: dict) -> str:
    """单条 upsert，冲突键 canonical_jd_url；返回 'created' | 'updated'。"""
    # 入库前算好招聘类型（失败静默留空，绝不阻断写入）。批量路径已算过的行会被跳过。
    _annotate_recruitment([job])
    canon = canonicalize_jd_url(job.get("jd_url"))
    now = _now()
    with conn.cursor() as cur:
        existing_id = _find_existing_id_by_canonical(cur, canon)
        moved = None
        if not existing_id:
            # 新链接没有行：先看是不是同一个帖子换了链接，是就把旧行原地换过来（见 plan_moved_postings）。
            # 单条入口只管这一种——它是逐岗调用的，每个岗都多问一次库不划算；
            # 「新链接已有行、旧行还挂着」留给批量入口（每个源每轮抓取都会过一遍）。
            items = [(canon, job)]
            moved = plan_moved_postings(items, {}, _fetch_posting_siblings(cur, items))
            if canon in moved["relink"]:
                existing_id = moved["relink"][canon]["id"]
        if existing_id:
            sets = _update_set_clause()
            vals = _row_tuple(job, _UPDATE_COLS, last_seen_at=now)
            cur.execute(f"update jobs set {sets} where id = %s", (*vals, existing_id))
            if moved:
                _apply_moved_postings(cur, moved)
            return "updated"
        jid = str(uuid.uuid4())
        cols = ", ".join(_INSERT_COLS)
        ph = ", ".join(["%s"] * len(_INSERT_COLS))
        vals = _row_tuple(job, _INSERT_COLS, id=jid, first_seen_at=now, last_seen_at=now)
        try:
            cur.execute(f"insert into jobs ({cols}) values ({ph})", vals)
            return "created"
        except psycopg2.errors.UniqueViolation:
            # 并发下撞 4 元组/active-canonical 唯一键 → 按 canonical 重查 update（幂等兜底）
            again = _find_existing_id_by_canonical(cur, canon)
            if not again:
                raise
            sets = _update_set_clause()
            vals = _row_tuple(job, _UPDATE_COLS, last_seen_at=now)
            cur.execute(f"update jobs set {sets} where id = %s", (*vals, again))
            return "updated"


def upsert_jobs_batch(conn, jobs: list, page_size: int = 500) -> tuple:
    """批量 upsert，返回 (created, updated)。冲突键 canonical_jd_url，复活语义同 upsert_job。

    ① 批内按 canonical 去重 last-wins；② 一次 ANY() 查全批既有行（canonical→id，多行优先 active）；
    ③ 命中→批量 UPDATE（execute_batch）、未命中→批量 INSERT（execute_values）；撞唯一键退回逐行 upsert_job。"""
    if not jobs:
        return (0, 0)

    # ⓪ 入库前批量算好招聘类型。按批调（一批 500 条约 6ms），绝不能逐条调——进程启动才是大头。
    #    失败一律静默留空，岗位照常入库，由 backfill-recruitment-category 补漏。
    _annotate_recruitment(jobs)

    # ① 批内去重
    deduped = {}
    for job in jobs:
        deduped[canonicalize_jd_url(job.get("jd_url"))] = job
    items = list(deduped.items())  # [(canon, job)]
    now = _now()

    day = _day(now)
    update_events, insert_events = [], []

    with conn.cursor() as cur:
        # ② 一次查全批既有行（带 status/posted_at 供事件判定：REAPPEARED 看 status、OFFICIAL_POSTED 看旧 posted_at）
        canons = [c for c, _ in items if c is not None]
        existing = {}
        if canons:
            cur.execute(
                "select id, canonical_jd_url, status, posted_at from jobs where canonical_jd_url = any(%s)", (canons,))
            for jid, canon, status, posted_at in cur.fetchall():
                if canon not in existing or status == "active":
                    existing[canon] = {"id": jid, "status": status, "posted_at": posted_at}

        # ②b 同一个帖子换了链接：新链接没有行的，拿库里最早那条旧行顶上（下面按既有行原地 UPDATE，jd_url 一起换）；
        #     其余旧行等本批写完再下架（见 plan_moved_postings）。
        moved = plan_moved_postings(items, existing, _fetch_posting_siblings(cur, items))
        for canon, row in moved["relink"].items():
            existing[canon] = {"id": row["id"], "status": "active", "posted_at": row["posted_at"]}

        to_insert, to_update = [], []
        for canon, job in items:
            ex = existing.get(canon)
            if ex:
                jid = ex["id"]
                to_update.append(_row_tuple(job, _UPDATE_COLS, last_seen_at=now) + (jid,))
                # 有效新状态：expired 黏住（不复活）、其余刷 active——与 _update_set_clause 同口径。
                eff_status = "expired" if ex["status"] == "expired" else "active"
                update_events += plan_upsert_events(
                    job_id=jid, source_id=job.get("source_id"),
                    old_status=ex["status"], old_posted_at=ex.get("posted_at"),
                    new_status=eff_status, new_posted_at=job.get("posted_at"), day=day)
            else:
                jid = str(uuid.uuid4())
                to_insert.append(_row_tuple(job, _INSERT_COLS, id=jid, first_seen_at=now, last_seen_at=now))
                insert_events += plan_upsert_events(
                    job_id=jid, source_id=job.get("source_id"),
                    old_status=None, old_posted_at=None,
                    new_status="active", new_posted_at=job.get("posted_at"), day=day)

        created = updated = 0
        insert_ok = False

        # ③a 既有行批量 UPDATE（execute_batch 合并往返，psycopg2 自动类型适配）
        if to_update:
            sets = _update_set_clause()
            psycopg2.extras.execute_batch(
                cur, f"update jobs set {sets} where id = %s", to_update, page_size=page_size)
            updated = len(to_update)

        # ③b 新行批量 INSERT；撞唯一键 → 退回逐行 upsert_job（含按 canonical 重查 update 的兜底）
        if to_insert:
            cols = ", ".join(_INSERT_COLS)
            try:
                psycopg2.extras.execute_values(
                    cur, f"insert into jobs ({cols}) values %s", to_insert, page_size=page_size)
                created = len(to_insert)
                insert_ok = True
                # 这批新岗里有多少其实是「已确认撤岗、被 purge 删过身份」的老岗又回来了（只记不拦）
                mark_reopened_from_closures(cur, [c for c, _j in items if not existing.get(c)])
            except psycopg2.errors.UniqueViolation:
                # 极少见（并发插同一新 canonical / 撞 4 元组唯一键）→ 逐行 upsert_job 兜底（幂等：
                # 已提交的页重查命中转 update，不会重插）。autocommit 下失败语句自身已回滚。
                # 此分支生成的新 uuid 未真正落库 → 丢弃 insert_events（避免 FK 违例；事件 best-effort 可缺）。
                created = 0
                insert_events = []
                for _canon, job in items:
                    if existing.get(_canon):
                        continue  # 这些走 UPDATE 分支，已计入 updated
                    if upsert_job(conn, job) == "created":
                        created += 1
                    else:
                        updated += 1

        _apply_moved_postings(cur, moved)

    # 事件 best-effort 落库（jobs 已 autocommit 提交；事件失败只 warning，不影响计数/返回）。
    # 仅记 job_id 确实已落库的事件：update_events（既有 id）+ insert_events（仅 bulk insert 成功时）。
    events = list(update_events)
    if insert_ok:
        events += insert_events
    record_job_events(conn, events)

    return (created, updated)
