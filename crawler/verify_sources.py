#!/usr/bin/env python3
"""
verify_sources.py — 「已入源」质量验证器（只验质量，不扩量）。

背景：大规模扩源后全库累计数百个公司招聘源，但扩源阶段只做了「发现+confirm 抓到岗位」的单点验证，
未系统验证每个源在 daily-crawl 时是否**真稳定产出过质量门的逐岗 jd_url**。本脚本做这层质量兜底：
批量跑全部源 → adapter.fetch → adapter.parse → 逐岗 normalizer.validate_job_quality →
统计 {总岗位数, 过质量门数, 失败原因分布}，揪出空源 / 失效源 / 张冠李戴，给出可执行清单。

设计要点（见文件顶 docstring 注释逐条说明）：
  - 复用 crawler/run.py 的 ADAPTERS + crawler/normalizer.validate_job_quality（与生产同口径）。
  - **多进程并发**（参考 confirm_beisen_parallel.py）：china_ats / feishu / bytedance 等浏览器 adapter 是
    共享单例 + 模块级路由缓存，线程并发会串状态导致**假**张冠张冠李戴；进程隔离每进程独立单例，安全。
    httpx adapter 同样进程隔离（网络绑定，进程开销可忽略），统一一条代码路径。
  - **沙箱不可达 ≠ 源失效**：只有「拿到 HTTP 响应」的判定才可信。连接层错误（DNS/reset/timeout）
    一律归 `blocked`（沙箱受限，需线上 GitHub Actions 复验）；真 404/410（网络通、页面没了）才算 `fail`。
  - **永不抛异常**：每源 catch 记根因，输出 JSONL，可断点续跑、单源 hang 不拖垮整批。

用法：
  python3 verify_sources.py --list                 # 只解析+打印源清单统计（纯离线，不联网）
  python3 verify_sources.py --tier httpx            # 验 httpx 档（快，几分钟）
  python3 verify_sources.py --tier browser          # 验 playwright 档（慢，建议后台跑）
  python3 verify_sources.py --tier all              # 两档全验
  python3 verify_sources.py --adapter hotjob        # 只验某 adapter
  python3 verify_sources.py --tier httpx --workers 10 --out verify_httpx.jsonl
  python3 verify_sources.py --analyze verify_httpx.jsonl   # 对已有 JSONL 出汇总报告（不联网）
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS_DIR = os.path.normpath(os.path.join(HERE, "..", "supabase", "migrations"))


# ───────────────────────── SQL 解析（从 *seed*.sql 提取已入源）─────────────────────────
# 迁移里 insert into sources 有两种形态、列顺序还不固定，必须按每条语句自带的列清单做**位置映射**：
#   ① insert into sources (cols) values (row),(row),... ;            （手写多行，如 003/010/011）
#   ② insert into sources (cols) select v,v,... where not exists(..) ;（probe 生成，绝大多数）
# update/dedup 迁移（004/037/105/108…）是 UPDATE，不在此解析（只解析 INSERT 的初始登记 URL）。

def _strip_sql_comments(sql: str) -> str:
    """去掉 -- 行注释（不在字符串内的）。块注释项目里没用，不处理。"""
    out = []
    for line in sql.splitlines():
        in_str = False
        i, n = 0, len(line)
        cut = n
        while i < n:
            ch = line[i]
            if ch == "'":
                # 处理 '' 转义
                if in_str and i + 1 < n and line[i + 1] == "'":
                    i += 2
                    continue
                in_str = not in_str
            elif ch == "-" and i + 1 < n and line[i + 1] == "-" and not in_str:
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def _split_top_level(s: str):
    """按**顶层**逗号切分，尊重 '...'（含 '' 转义）字符串与 (...) 嵌套。"""
    parts, buf = [], []
    depth, in_str = 0, False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":  # 转义引号
                    buf.append("''")
                    i += 2
                    continue
                in_str = False
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts


def _find_kw_toplevel(s: str, kw: str) -> int:
    """返回关键词 kw 在 s 中**顶层**（depth==0、不在字符串内）首次出现的下标；找不到 -1。"""
    kw = kw.lower()
    klen = len(kw)
    depth, in_str = 0, False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and s[i:i + klen].lower() == kw:
            return i
        i += 1
    return -1


def _match_paren(s: str, open_idx: int) -> int:
    """给定 '(' 下标，返回配对 ')' 下标（尊重字符串）。失败返回 -1。"""
    depth, in_str = 0, False
    i, n = open_idx, len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _unquote(tok: str):
    """SQL 标量字面量 → Python 值。'...'→去引号解转义；null→None；其余原样（数字/关键字）。"""
    t = tok.strip()
    if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
        return t[1:-1].replace("''", "'")
    if t.lower() == "null":
        return None
    return t


def parse_inserts(sql_text: str):
    """解析一个 SQL 文本里所有 `insert into sources` 语句，返回 [dict(col_lower -> value), ...]。"""
    sql = _strip_sql_comments(sql_text)
    rows = []
    low = sql.lower()
    start = 0
    while True:
        idx = low.find("insert into sources", start)
        if idx == -1:
            break
        # 该语句到下一个分号（分号不会出现在本项目的字符串值里；emit_sql/手写均无内嵌 ';'）
        semi = sql.find(";", idx)
        stmt = sql[idx:semi if semi != -1 else len(sql)]
        start = (semi + 1) if semi != -1 else len(sql)

        # 1) 列清单：into sources 后第一个 (...)
        paren = stmt.find("(")
        if paren == -1:
            continue
        close = _match_paren(stmt, paren)
        if close == -1:
            continue
        cols = [c.strip().strip('"').lower() for c in _split_top_level(stmt[paren + 1:close])]
        rest = stmt[close + 1:].lstrip()
        rlow = rest.lower()

        if rlow.startswith("values"):
            body = rest[len("values"):]
            for grp in _split_top_level(body):
                g = grp.strip()
                if not (g.startswith("(") and g.endswith(")")):
                    continue
                vals = [_unquote(v) for v in _split_top_level(g[1:-1])]
                if len(vals) == len(cols):
                    rows.append(dict(zip(cols, vals)))
        elif rlow.startswith("select"):
            body = rest[len("select"):]
            wpos = _find_kw_toplevel(body, "where not exists")
            vals_str = body[:wpos] if wpos != -1 else body
            vals = [_unquote(v) for v in _split_top_level(vals_str)]
            if len(vals) == len(cols):
                rows.append(dict(zip(cols, vals)))
        # 其它形态（如 insert ... select from 子查询）本项目没有，跳过
    return rows


def load_sources_from_migrations(dirpath: str = MIGRATIONS_DIR):
    """扫描全部迁移，提取 (company, url, adapter, crawl_method, segment, industry)，按 url 去重。
    记录每个 url 出现的迁移文件，方便后续给「下架/改正」清单指到具体文件。"""
    by_url = {}
    files = sorted(f for f in os.listdir(dirpath) if f.endswith(".sql"))
    for fname in files:
        try:
            with open(os.path.join(dirpath, fname), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if "insert into sources" not in text.lower():
            continue
        for r in parse_inserts(text):
            url = (r.get("source_url") or "").strip()
            if not url:
                continue
            if url not in by_url:
                by_url[url] = {
                    "company": r.get("company") or "",
                    "url": url,
                    "adapter": r.get("adapter_name") or "",
                    "crawl_method": r.get("crawl_method") or "",
                    "segment": r.get("segment") or "",
                    "industry": r.get("industry") or "",
                    "files": [fname],
                }
            else:
                by_url[url]["files"].append(fname)
    return list(by_url.values())


def load_sources_from_db():
    """可选：从生产库读 enabled sources（daily-crawl 真正会跑的那一份）。
    需环境已注入 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY（不在此读取/打印 .env）。失败返回 None。"""
    try:
        sys.path.insert(0, HERE)
        import db  # noqa: E402
        sb = db.get_supabase()
        rows = db.get_sources(sb)
    except Exception as e:
        print(f"[verify] DB 不可用（{type(e).__name__}: {e}），回退迁移解析。", file=sys.stderr)
        return None
    out = []
    for r in rows:
        url = (r.get("source_url") or "").strip()
        if not url:
            continue
        out.append({
            "company": r.get("company") or "",
            "url": url,
            "adapter": r.get("adapter_name") or "",
            "crawl_method": r.get("crawl_method") or "",
            "segment": r.get("segment") or "",
            "industry": r.get("industry") or "",
            "files": ["<db:enabled>"],
        })
    return out


# ───────────────────────── adapter 分档（与 run.py 同口径）─────────────────────────
# 权威集合从 run.py 取（_HTTPX_SAFE_ADAPTERS）；导入失败用同步副本兜底。
_HTTPX_FALLBACK = {
    "apple", "apple_cn", "baidu", "jd", "haier", "siemens", "tencent",
    "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "eightfold",
    "oracle", "amazon", "phenom", "microsoft", "hotjob", "wt",
    "netease", "oppo", "xiaohongshu", "alibaba", "huawei", "ctrip",
}


def _httpx_safe_set():
    try:
        sys.path.insert(0, HERE)
        from run import _HTTPX_SAFE_ADAPTERS  # noqa: E402
        return set(_HTTPX_SAFE_ADAPTERS)
    except Exception:
        return set(_HTTPX_FALLBACK)


def adapter_tier(adapter_name: str, httpx_set=None) -> str:
    httpx_set = httpx_set if httpx_set is not None else _httpx_safe_set()
    return "httpx" if (adapter_name or "") in httpx_set else "browser"


# ───────────────────────── 单源验证（worker，进程内执行）─────────────────────────
# 多进程 spawn 会在每个子进程重新 import 本模块 → import run → 实例化全部 adapter 单例（一次性成本）。
# 同进程内顺序复用 adapter 安全：china_ats.fetch 每次重绑 _host/_origin/list_urls（见 china_ats.py:75）。
#
# 张冠李戴严格 host 检查**只对 beisen+moka**：这两类 jd_url 由 adapter 按「源 origin/base」构造，
# 与源 host 必然同租户子域（beisen: {origin}/zwxq?jobAdId=；moka: {base}#/job/{uuid}），
# 故 host 不一致 = 真串源。其余源（外企 ATS 的 api-host vs careers-host 是结构性不同；wt/hotjob/
# 自建站的 jd 常落在独立 m./jobs. 子域）host 不等是正常的，不能据此报警——靠抽样标题人工眼检。
_STRICT_HOST_SLDS = {"zhiye.com", "italent.cn", "mokahr.com"}


def _sld(host: str) -> str:
    """取注册域（最后两段）。够用：本项目 host 都是 a.b.com / a.b.cn 形态。"""
    host = (host or "").lower().split(":")[0]
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _classify_exc(exc) -> tuple:
    """异常 → (error_class, status, reason)。核心原则：拿到 HTTP 响应才可信，连接层错误归 blocked。"""
    name = type(exc).__name__
    msg = str(exc)
    low = msg.lower()

    # 环境缺失（playwright/chromium 没装）→ 不是源的问题，单列
    if ("playwright" in low and ("not installed" in low or "no module" in low)) \
            or "executable doesn't exist" in low or "browsertype.launch" in low \
            or "modulenotfounderror" in name.lower() and "playwright" in low:
        return "env", "blocked", f"环境缺失（playwright/chromium 未装）: {msg[:160]}"

    # 真 HTTP 响应（httpx.HTTPStatusError）：网络是通的 → 判定可信
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code in (404, 410):
                return "http_gone", "fail", f"HTTP {code}（页面不存在/已下架，网络通）"
            if code in (401, 403, 429):
                return "antibot", "blocked", f"HTTP {code}（反爬/鉴权；线上 IP 可能不同，需复验）"
            if code >= 500:
                return "http_5xx", "blocked", f"HTTP {code}（服务端错误，多为瞬时，需复验）"
            return "http", "fail", f"HTTP {code}"
    except Exception:
        pass

    # 连接层 / DNS / 超时 / SSL / reset → 沙箱可能就是挡这些，**一律 blocked**，不当失效
    net_markers = (
        "getaddrinfo", "name or service", "nodename nor servname", "temporary failure in name",
        "connecterror", "connecttimeout", "readtimeout", "readerror", "writeerror", "pooltimeout",
        "connection reset", "reset by peer", "errno 35", "errno 54", "errno 60", "errno 61",
        "errno 51", "errno 65", "connection refused", "network is unreachable", "timed out",
        "timeout", "eof occurred", "ssl", "remoteprotocolerror", "proxyerror", "all connection attempts failed",
    )
    if any(m in low for m in net_markers) or any(m in name.lower() for m in (
            "timeout", "connect", "readerror", "network", "ssl", "protocol")):
        dns = any(m in low for m in ("getaddrinfo", "name or service", "nodename", "name resolution"))
        return ("dns" if dns else "network"), "blocked", f"{name}: {msg[:160]}"

    # adapter 主动报「被拦截」（RuntimeError blocked / anti_bot）→ 反爬，blocked
    if "blocked" in low or "anti_bot" in low or "访问受限" in msg or "请求过于频繁" in msg:
        return "antibot", "blocked", f"{name}: {msg[:160]}"

    # 其余（解析/结构/KeyError 等）→ 真问题，fail
    return "parse", "fail", f"{name}: {msg[:200]}"


def _reachable(url: str, timeout: int = 8):
    """browser 档可达性预检。返回 None=可达（拿到任意 HTTP 响应）；返回 (error_class, reason)=连接层失败。
    只看「能否拿到 HTTP 响应」：拿到（含 4xx/5xx）即网络通；连接失败才判沙箱够不到。"""
    try:
        import httpx
        headers = {"User-Agent": "Mozilla/5.0 (compatible; JobRadarVerify/0.1)",
                   "Accept": "text/html,application/json,*/*"}
        # 不 raise_for_status：任意状态码都说明 host 可达。HEAD 常被禁 → 用 GET 但不读体。
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as c:
            c.get(url)
        return None
    except Exception as e:
        ec, _status, reason = _classify_exc(e)
        # 预检阶段只把「连接层/网络」失败当 blocked；其它（理论少见）也归 blocked 让 chromium 不空耗。
        return (ec if ec in ("network", "dns", "antibot", "http_5xx") else "network",
                f"可达性预检失败 {reason}")


def verify_one(cand: dict, timeout: int = 20) -> dict:
    """对单个源跑 fetch→parse→逐岗质量门，返回富诊断结果。**永不抛异常**。"""
    import normalizer
    from run import ADAPTERS

    base = {
        "company": cand.get("company", ""), "url": cand.get("url", ""),
        "adapter": cand.get("adapter", ""), "crawl_method": cand.get("crawl_method", ""),
        "segment": cand.get("segment", ""), "industry": cand.get("industry", ""),
        "files": cand.get("files", []),
        "parsed": 0, "valid": 0, "china": 0,
        "invalid_reasons": {}, "samples": [], "parsed_companies": {},
        "error_class": None, "reason": "",
    }
    src_host = urlparse(cand.get("url", "")).netloc.lower()
    base["src_host"] = src_host

    adapter = ADAPTERS.get(cand.get("adapter"))
    if adapter is None:
        base.update(status="fail", error_class="unknown_adapter",
                    reason=f"未知 adapter '{cand.get('adapter')}'")
        return base
    try:
        adapter.timeout = timeout
    except Exception:
        pass

    # 健康探针快模式：beisen/moka 内部会全量翻页（最慢的两类，占 browser 档 90%）。
    # 质量验证只需确认「页1 产出 ≥1 过质量门岗位」即可判健康，故封顶分页省时——
    # 不改变 ok/empty 判定（页1 渲染出岗 = 健康；页1 空 = 后续页也不会凭空出岗）。
    # 在实例上设属性（覆盖类属性），仅影响本进程后续复用，正合所需。
    if os.environ.get("VERIFY_QUICK") == "1":
        a = cand.get("adapter")
        if a == "beisen":
            adapter._MAX_JOBS = 60     # _PAGE_SIZE=50 → 1-2 页
        elif a == "moka":
            adapter._page_cap = 1      # 仅首页（~30 卡）

    # browser 档先做廉价可达性预检：playwright goto 超时硬编码 35s，被沙箱挡的源会 35s×N 空耗。
    # 用一次 httpx 探测：**连接层失败**（DNS/reset/timeout=沙箱够不到）→ 直接判 blocked，省下昂贵 chromium；
    # 拿到任意 HTTP 响应（即便 403 反爬）→ host 可达 → 照常起 chromium（浏览器可能能过反爬）。
    if cand.get("tier") == "browser":
        reach = _reachable(cand["url"], timeout=8)
        if reach is not None:  # 连接层失败
            base.update(status="blocked", error_class=reach[0], reason=reach[1], elapsed=8.0)
            return base

    t0 = time.time()
    try:
        html = adapter.fetch(cand["url"])
        raw_jobs = adapter.parse(html)
    except Exception as e:
        ec, status, reason = _classify_exc(e)
        base.update(status=status, error_class=ec, reason=reason,
                    elapsed=round(time.time() - t0, 1))
        return base

    base["parsed"] = len(raw_jobs)
    base["raw_len"] = len(html) if isinstance(html, str) else 0  # 内容信号：parse=0 时大=可解析失败/结构变, 小=空看板/错误页
    base["elapsed"] = round(time.time() - t0, 1)

    invalid = Counter()
    parsed_companies = Counter()
    jd_hosts = Counter()
    valid = china = 0
    samples = []
    for raw in raw_jobs:
        orig_company = (raw.company or "").strip()
        if orig_company:
            parsed_companies[orig_company] += 1
        if not raw.company:
            raw.company = cand.get("company", "")
        is_valid, reason = normalizer.validate_job_quality(raw, cand["url"])
        if not is_valid:
            invalid[reason] += 1
            continue
        valid += 1
        jd_host = urlparse((raw.jd_url or "")).netloc.lower()
        if jd_host:
            jd_hosts[jd_host] += 1
        if normalizer.is_china_location(raw.location):
            china += 1
        if len(samples) < 4:
            samples.append({
                "title": (raw.title or "")[:80],
                "jd_url": raw.jd_url or "",
                "company": orig_company,
                "location": raw.location or "",
            })

    base["valid"] = valid
    base["china"] = china
    base["invalid_reasons"] = dict(invalid)
    base["samples"] = samples
    base["parsed_companies"] = dict(parsed_companies.most_common(5))

    # 张冠李戴信号：valid 岗位的主导 jd_url host vs 源 host。
    # 仅对 beisen/moka（jd 按源 origin/base 构造，必同租户子域）做严格全 host 报警；
    # 其余源记录 host 信息但不报警（结构性不同，详见 _STRICT_HOST_SLDS 注释）。
    base["host_suspect"] = False
    if jd_hosts:
        dom_host, dom_n = jd_hosts.most_common(1)[0]
        base["dom_jd_host"] = dom_host
        base["host_match"] = (dom_host == src_host)
        base["sld_match"] = (_sld(dom_host) == _sld(src_host))
        if valid > 0 and _sld(src_host) in _STRICT_HOST_SLDS and dom_host != src_host:
            base["host_suspect"] = True

    if valid > 0:
        base["status"] = "ok"
        base["error_class"] = None
    elif len(raw_jobs) > 0:
        base["status"] = "empty"   # 抓到行但 0 过质量门（多为 jd_url 是导航/搜索/首页）
        base["error_class"] = "no_valid"
        base["reason"] = "解析到行但无一过质量门：" + ", ".join(
            f"{k}×{v}" for k, v in invalid.most_common(5))
    else:
        base["status"] = "empty"
        base["error_class"] = "zero_parsed"
        base["reason"] = "fetch 成功但 parse 出 0 行（接口结构变了？空看板？）"
    return base


# 多进程入口需顶层可 pickle 的函数
def _worker(args):
    cand, timeout = args
    try:
        return verify_one(cand, timeout=timeout)
    except Exception as e:  # 兜底：理论上 verify_one 不抛，这里再保一层
        return {**cand, "status": "fail", "error_class": "worker_crash",
                "reason": f"{type(e).__name__}: {e}", "parsed": 0, "valid": 0, "china": 0}


# ───────────────────────── 运行 & 汇总 ─────────────────────────
def run_verification(sources, workers, timeout, out_path):
    from multiprocessing import Pool

    t0 = time.time()
    results = []
    done = 0
    total = len(sources)
    print(f"[verify] 开始验证 {total} 源 × {workers} 进程（timeout={timeout}s）→ {out_path}", flush=True)
    with open(out_path, "w", encoding="utf-8") as fout:
        with Pool(workers) as pool:
            for r in pool.imap_unordered(_worker, [(s, timeout) for s in sources], chunksize=1):
                results.append(r)
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                fout.flush()
                done += 1
                st = r.get("status", "?")
                flag = {"ok": "✓", "empty": "∅", "fail": "✗", "blocked": "~net"}.get(st, "?")
                if done <= 10 or done % 25 == 0 or st in ("fail", "empty"):
                    detail = (f"valid={r.get('valid',0)} china={r.get('china',0)} parsed={r.get('parsed',0)}"
                              if st == "ok" else (r.get("reason", "") or "")[:70])
                    suspect = " ⚠张冠李戴?" if r.get("host_suspect") else ""
                    print(f"  [{done:>4}/{total}] {flag:8} [{r.get('adapter',''):12}] "
                          f"{(r.get('company','') or '')[:18]:20} {detail}{suspect}", flush=True)
    print(f"[verify] 完成 {total} 源，用时 {round(time.time()-t0)}s。结果 → {out_path}\n", flush=True)
    return results


def summarize(results, show_samples=True):
    buckets = defaultdict(list)
    for r in results:
        buckets[r.get("status", "?")].append(r)
    ok, empty, fail, blocked = (buckets["ok"], buckets["empty"], buckets["fail"], buckets["blocked"])

    print("=" * 78)
    print("【健康度汇总】")
    print(f"  总验证源        : {len(results)}")
    print(f"  ✓ 健康(ok)      : {len(ok)}   （valid>0，真返回过质量门的逐岗 jd_url）")
    print(f"  ∅ 空源(empty)   : {len(empty)}   （fetch 成功但 0 岗过质量门）")
    print(f"  ✗ 失效(fail)    : {len(fail)}   （网络通但 404/解析错/未知 adapter）")
    print(f"  ▶ 沙箱受限      : {len(blocked)}   （连接层错/反爬，沙箱判不了，需线上复验）")
    valid_total = sum(r.get("valid", 0) for r in ok)
    china_total = sum(r.get("china", 0) for r in ok)
    print(f"  健康源累计 valid 岗位: {valid_total}（其中在华 {china_total}）")

    # 按 adapter 分布
    print("\n【按 adapter 分档】 ok / empty / fail / blocked  （valid 岗位合计）")
    per = defaultdict(lambda: Counter())
    per_valid = defaultdict(int)
    for r in results:
        a = r.get("adapter", "?")
        per[a][r.get("status", "?")] += 1
        per_valid[a] += r.get("valid", 0)
    for a in sorted(per, key=lambda x: -(per[x]["ok"])):
        c = per[a]
        print(f"  {a:14} ok={c['ok']:>3} empty={c['empty']:>3} fail={c['fail']:>3} "
              f"blocked={c['blocked']:>3}   岗位={per_valid[a]}")

    # 失效源清单（fail）+ 根因
    if fail:
        print("\n" + "=" * 78)
        print(f"【失效源清单 (fail) — {len(fail)} 个，建议 disable 或修复】")
        by_cls = defaultdict(list)
        for r in fail:
            by_cls[r.get("error_class", "?")].append(r)
        for cls, rows in sorted(by_cls.items(), key=lambda kv: -len(kv[1])):
            print(f"\n  ── 根因={cls}（{len(rows)} 个）──")
            for r in rows:
                f0 = (r.get("files") or ["?"])[0]
                print(f"    ✗ [{r.get('adapter',''):11}] {(r.get('company','') or '')[:20]:22} "
                      f"{r.get('url','')}")
                print(f"        └ {(r.get('reason','') or '')[:110]}  [{f0}]")

    # 空源清单（empty）+ 主导失败原因
    if empty:
        print("\n" + "=" * 78)
        print(f"【空源清单 (empty) — {len(empty)} 个，抓到页但 0 岗过质量门】")
        for r in sorted(empty, key=lambda x: x.get("adapter", "")):
            f0 = (r.get("files") or ["?"])[0]
            print(f"    ∅ [{r.get('adapter',''):11}] {(r.get('company','') or '')[:20]:22} "
                  f"parsed={r.get('parsed',0)}  {r.get('url','')}")
            print(f"        └ {(r.get('reason','') or '')[:110]}  [{f0}]")

    # 张冠李戴疑似（host 不一致）
    suspects = [r for r in results if r.get("host_suspect")]
    print("\n" + "=" * 78)
    print(f"【张冠李戴复核 — jd_url host 与源 host 不一致疑似：{len(suspects)} 个】")
    if suspects:
        for r in suspects:
            print(f"    ⚠ [{r.get('adapter',''):11}] {(r.get('company','') or '')[:18]:20} "
                  f"源host={r.get('src_host','')} → jd_host={r.get('dom_jd_host','')}")
            for s in (r.get("samples") or [])[:2]:
                print(f"        例: {s.get('title','')[:40]} | {s.get('jd_url','')[:70]}")
    else:
        print("    （无：所有健康源的 jd_url host 与源 host 同租户/同域，未见串源）")

    # 沙箱受限清单（需线上复验）
    if blocked:
        print("\n" + "=" * 78)
        print(f"【沙箱受限 (blocked) — {len(blocked)} 个，需线上 GitHub Actions 复验，勿当失效】")
        by_cls = defaultdict(list)
        for r in blocked:
            by_cls[r.get("error_class", "?")].append(r)
        for cls, rows in sorted(by_cls.items(), key=lambda kv: -len(kv[1])):
            sample_hosts = Counter(r.get("src_host", "") for r in rows)
            print(f"  ── {cls}（{len(rows)} 个）host 分布 top: "
                  f"{', '.join(f'{h}×{n}' for h,n in sample_hosts.most_common(6))}")

    # 健康源里抽样（供人工眼检张冠李戴的标题线索）
    if show_samples and ok:
        print("\n" + "=" * 78)
        print("【健康源抽样（每 adapter 取 valid 最多的 1 个，看标题是否与公司相符）】")
        best_per = {}
        for r in ok:
            a = r.get("adapter", "?")
            if a not in best_per or r.get("valid", 0) > best_per[a].get("valid", 0):
                best_per[a] = r
        for a in sorted(best_per):
            r = best_per[a]
            print(f"  [{a:12}] {(r.get('company','') or '')[:18]:20} valid={r.get('valid',0)} "
                  f"china={r.get('china',0)}")
            for s in (r.get("samples") or [])[:2]:
                print(f"      · {s.get('title','')[:46]:48} {s.get('location','') or ''}")
    print("=" * 78)


# ───────────────────────── CLI ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="已入源质量验证器（只验质量，不扩量）")
    ap.add_argument("--list", action="store_true", help="只解析+打印源清单统计（纯离线）")
    ap.add_argument("--tier", choices=["httpx", "browser", "all"], default="httpx",
                    help="验哪一档：httpx(快) / browser(playwright，慢) / all")
    ap.add_argument("--adapter", type=str, default=None, help="只验某 adapter（如 hotjob/beisen）")
    ap.add_argument("--from", dest="source_of_truth", choices=["migrations", "db"],
                    default="migrations", help="源清单来源：migrations(默认离线) / db(enabled sources)")
    ap.add_argument("--workers", type=int, default=None, help="并发进程数（默认 httpx=10 / browser=4）")
    ap.add_argument("--timeout", type=int, default=None, help="单源 fetch 超时秒（默认 httpx=15 / browser=45）")
    ap.add_argument("--limit", type=int, default=0, help="只验前 N 个（调试）")
    ap.add_argument("--out", type=str, default=None, help="JSONL 输出路径")
    ap.add_argument("--analyze", type=str, default=None, help="对已有 JSONL 出汇总（不联网）")
    ap.add_argument("--reverify", type=str, default=None,
                    help="复验模式：读已有 JSONL，只重跑 status≠ok 的源（配 --tier 可只跑某档）")
    args = ap.parse_args()

    # 离线：对已有 JSONL 出报告
    if args.analyze:
        with open(args.analyze, encoding="utf-8") as f:
            results = [json.loads(ln) for ln in f if ln.strip()]
        summarize(results)
        return

    # 载入源清单
    sources = None
    if args.source_of_truth == "db":
        sources = load_sources_from_db()
    if sources is None:
        sources = load_sources_from_migrations()
        sot = "migrations"
    else:
        sot = "db(enabled)"

    # 复验模式：用上次结果里 status≠ok 的源覆盖清单（配 --tier/--adapter 可再收窄）
    if args.reverify:
        prior = [json.loads(ln) for ln in open(args.reverify, encoding="utf-8") if ln.strip()]
        sources = [{
            "company": r.get("company", ""), "url": r.get("url", ""),
            "adapter": r.get("adapter", ""), "crawl_method": r.get("crawl_method", ""),
            "segment": r.get("segment", ""), "industry": r.get("industry", ""),
            "files": r.get("files", []),
        } for r in prior if r.get("status") != "ok" and r.get("url")]
        sot = f"reverify({os.path.basename(args.reverify)}, {len(sources)} 个 non-ok)"

    httpx_set = _httpx_safe_set()
    for s in sources:
        s["tier"] = adapter_tier(s["adapter"], httpx_set)

    # --list：纯离线统计
    if args.list:
        print(f"[verify] 源清单来源 = {sot}；去重后 {len(sources)} 个源\n")
        by_adapter = Counter(s["adapter"] for s in sources)
        by_tier = Counter(s["tier"] for s in sources)
        by_seg = Counter(s["segment"] or "(无)" for s in sources)
        print("【按 tier】", dict(by_tier))
        print("【按 segment】", dict(by_seg))
        print("\n【按 adapter】（源数）")
        for a, n in by_adapter.most_common():
            print(f"  {a:14} {n:>4}   [{adapter_tier(a, httpx_set)}]")
        # 无 adapter / 未知 adapter 提示
        unknown = [s for s in sources if not s["adapter"]]
        if unknown:
            print(f"\n⚠ 有 {len(unknown)} 个源缺 adapter_name")
        return

    # 过滤 tier / adapter
    if args.adapter:
        sources = [s for s in sources if s["adapter"] == args.adapter]
    elif args.tier != "all":
        sources = [s for s in sources if s["tier"] == args.tier]

    if not sources:
        print("[verify] 没有匹配的源，退出。")
        return
    if args.limit:
        sources = sources[:args.limit]

    # 默认参数按档调
    is_browser_run = args.tier == "browser" or (args.adapter and sources and sources[0]["tier"] == "browser")
    workers = args.workers or (4 if is_browser_run else 10)
    timeout = args.timeout or (45 if is_browser_run else 15)
    out_path = args.out or os.path.join(
        HERE, f"verify_{'reverify_' if args.reverify else ''}{args.adapter or args.tier}.jsonl")

    results = run_verification(sources, workers=workers, timeout=timeout, out_path=out_path)
    summarize(results)


if __name__ == "__main__":
    main()
