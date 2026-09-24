"""脚本直连 jobs 库的 psql 调用助手（JS 侧同口径：scripts/lib/psql.js）。

🚫 连接串绝不放进 psql 的命令行参数（2026-09-24 立）：
❌ 旧写法 ``subprocess.run(["psql", URL, ...], check=True)``：带密码的连接串出现在 ``ps`` 里；
   psql 一失败，``CalledProcessError`` 的报错就是 ``Command '['psql', 'postgresql://…', …]' returned …``，
   密码跟着 traceback 进日志 / 会话记录。
✅ 拆成 libpq 环境变量（PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE，查询参数按 libpq 官方对照表
   转成 PGSSLMODE 等）经 env 传给 psql；失败只用**脱敏后的 stderr** 另造异常，并 ``from None`` 切断异常链。

语义与「把 URL 当第一个参数」一致：URL 里写了的项覆盖环境里的同名 PG* 变量，没写的项仍由环境兜底。
认不出的查询参数直接报错（只报参数名），不悄悄丢——丢掉 sslmode 这类参数会静默降低连接的安全级别。
"""
from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import unquote, urlsplit

# 与 scripts/lib/psql.js 的 PARAM_ENV 逐条一致（test_psql_env 会读 JS 文件比对）。
PARAM_ENV = {
    "host": "PGHOST",
    "hostaddr": "PGHOSTADDR",
    "port": "PGPORT",
    "dbname": "PGDATABASE",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "passfile": "PGPASSFILE",
    "require_auth": "PGREQUIREAUTH",
    "channel_binding": "PGCHANNELBINDING",
    "service": "PGSERVICE",
    "options": "PGOPTIONS",
    "application_name": "PGAPPNAME",
    "sslmode": "PGSSLMODE",
    "requiressl": "PGREQUIRESSL",
    "sslnegotiation": "PGSSLNEGOTIATION",
    "sslcompression": "PGSSLCOMPRESSION",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslcertmode": "PGSSLCERTMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL",
    "sslcrldir": "PGSSLCRLDIR",
    "sslsni": "PGSSLSNI",
    "requirepeer": "PGREQUIREPEER",
    "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION",
    "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
    "min_protocol_version": "PGMINPROTOCOLVERSION",
    "max_protocol_version": "PGMAXPROTOCOLVERSION",
    "gssencmode": "PGGSSENCMODE",
    "krbsrvname": "PGKRBSRVNAME",
    "gsslib": "PGGSSLIB",
    "gssdelegation": "PGGSSDELEGATION",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "client_encoding": "PGCLIENTENCODING",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
    "load_balance_hosts": "PGLOADBALANCEHOSTS",
}

_SCHEMES = ("postgres", "postgresql")


class PsqlError(RuntimeError):
    """psql 失败。message 只含脱敏后的 stderr，不含 argv / 连接串。"""


def libpq_env_from_url(url: str) -> dict[str, str]:
    """连接串 → {PGHOST: …, PGPORT: …}，只含 URL 里真写了的项。"""
    if not isinstance(url, str):
        raise ValueError("数据库连接串必须是字符串")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ValueError("数据库连接串解析失败（格式不对）") from None
    if parts.scheme.lower() not in _SCHEMES:
        raise ValueError("数据库连接串必须是 postgres:// 或 postgresql:// 开头")
    env: dict[str, str] = {}
    # 不用 parts.hostname / parts.port：前者会转小写（Unix socket 路径大小写敏感），后者报错时带原值。
    userinfo, has_at, hostport = parts.netloc.rpartition("@")
    if not has_at:
        userinfo, hostport = "", parts.netloc
    if "," in hostport:
        raise ValueError("数据库连接串是多主机写法，请改用 PGHOST 环境变量")
    user, has_colon, password = userinfo.partition(":")
    if user:
        env["PGUSER"] = unquote(user)
    if has_colon and password:
        env["PGPASSWORD"] = unquote(password)
    if hostport.startswith("["):
        host, _, rest = hostport[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif ":" in hostport:
        host, _, port = hostport.rpartition(":")
    else:
        host, port = hostport, ""
    if host:
        env["PGHOST"] = unquote(host)
    if port:
        if not port.isdigit():
            raise ValueError("数据库连接串的端口不是数字")
        env["PGPORT"] = port
    db = parts.path.lstrip("/")
    if db:
        env["PGDATABASE"] = unquote(db)
    # 不用 parse_qsl：它把 + 解成空格，libpq 只做百分号解码。
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        key = unquote(key)
        name = PARAM_ENV.get(key)
        if not name:
            raise ValueError(f"数据库连接串里的参数 {key} 没有对应的 libpq 环境变量，请从连接串里去掉或改用环境变量")
        env[name] = unquote(value)
    return env


def _secrets_of(url: str) -> list[str]:
    out = {url}
    try:
        userinfo = urlsplit(url).netloc.rpartition("@")[0]
        raw_pw = userinfo.partition(":")[2]
        if raw_pw:
            out.add(raw_pw)
        env = libpq_env_from_url(url)
        for k in ("PGPASSWORD", "PGHOST", "PGHOSTADDR"):
            if env.get(k):
                out.add(env[k])
    except ValueError:
        pass  # 解析不了的连接串在 run_psql 入口已经报过错，这里只尽力而为。
    return sorted((s for s in out if s), key=len, reverse=True)


def redact(text: str | None, url: str | None) -> str:
    """把文本里的连接串 / 密码 / 主机替换成占位符（主机 IP 同样不许进公开仓的 CI 日志）。"""
    s = text or ""
    if not url:
        return s
    for secret in _secrets_of(url):
        s = s.replace(secret, "<redacted>")
    return s


def run_psql(args: list[str], url: str | None = None, *, input: str | None = None,
             base_env: dict[str, str] | None = None, bin: str = "psql") -> str:
    """跑一次 psql，返回 stdout 文本。url 默认取 JOBS_DATABASE_URL；bin 只给测试用。"""
    url = url if url is not None else os.environ.get("JOBS_DATABASE_URL")
    if not url:
        raise PsqlError("JOBS_DATABASE_URL 未配置（先 source .env.local）")
    pg_env = libpq_env_from_url(url)
    pw = pg_env.get("PGPASSWORD")
    pw = pw if pw and len(pw) >= 8 else None  # 密码太短时不按子串查（会误伤正常 SQL）
    for a in args:
        if isinstance(a, str) and (a.lower().startswith(tuple(s + "://" for s in _SCHEMES))
                                   or url in a or (pw and pw in a)):
            raise PsqlError("psql 参数里不许出现连接串或密码（连接信息已经通过环境变量传入）")
    env = {**(base_env if base_env is not None else os.environ), **pg_env}
    try:
        proc = subprocess.run([bin, *args], env=env, input=input, capture_output=True, text=True)
    except OSError as e:
        # e 自身不带连接串（argv 里已经没有），但仍只取错误号，别把整个异常对象往外抛。
        raise PsqlError(f"psql 没能启动：errno={e.errno}（本机没装 psql？）") from None
    stderr = redact(proc.stderr, url).strip()
    if proc.returncode != 0:
        raise PsqlError(f"psql 失败（退出码 {proc.returncode}）" + (f"：\n{stderr}" if stderr else ""))
    if stderr:
        sys.stderr.write(stderr + "\n")
    return proc.stdout
