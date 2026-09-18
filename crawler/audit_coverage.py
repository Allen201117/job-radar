"""覆盖率差集：没有声明期望的东西，本身就是告警。

`audit_runner.py` 只跑 `audit_contract.yaml` 里已经写好的检查项——它回答不了
「有没有东西根本没被纳入期望清单」。本模块回答的是这个问题，做法是四组差集，
每组左边都是**自动枚举**（不靠人维护清单，代码/配置改了差集自己会变），右边是
「期望清单里声明覆盖了的」∪「显式豁免」：

  1. 链路层·workflow：定时 workflow ∖ contract layer=pipeline 的 owner。
  2. 链路层·module：ops_runs 的 module 字面量 ∖ ops_watchdog.py 的
     MODULE_OUTPUT/NO_OUTPUT_MODULES。**只扫 `*.py` / `*.js` 源码里的调用点**——
     workflow yml 里用 shell/psql 直接 `insert into ops_runs` 的写法（如
     purge-expired.yml）不在这个枚举范围内，会漏报，不是这条差集的盲区就是漏了它。
  3. 数据层：jobs 表全部列（纯解析 jobs-db/schema.sql，不连库）∖ contract 里
     `covers` 字段声明覆盖的列。**故意不再用「列名出现在 SQL 里」判覆盖**——
     `status` 几乎出现在每条检查的 where 里，按出现判会把「从没被真正度量」的列
     全部误判成「已覆盖」（真假绿）。`covers` 必须显式声明，且经
     `_validate_covers` 校验「真出现在该条 SQL 里」+「真是 schema 里的列」，
     声明不了的列不让声明（防止绕过校验空口喊「我覆盖了」）。
  4. 体验层：scripts/ux-walkthrough/walkthrough.js **真正写进 `ops_runs.metrics`**
     的那个表达式的全部顶层键 ∖ contract layer=experience 的检查项引用到的指标键。

豁免必须带非空 reason（`audit_exemptions.yaml`），没有理由的豁免在 `load_exemptions` 里
直接抛错——拿不出理由就不许消音这条差集。豁免清单本身也会腐烂（左边枚举变了、
豁免的名字不存在了），`compute_gaps` 额外算一份 `stale_exemptions`：豁免了一个
早就不在左边集合里的名字，说明这条豁免该删了（不删不影响判定结果，但会误导
下一个读这份清单的人以为「这东西还存在、只是被豁免」）。

差集非空不代表这个进程该失败：**它是「发现」，不是「错误」**（同 audit_runner 的 exit
code 语义），main() 固定返回 0；调用方（人或 CI）自己决定要不要为某条差集补检查项。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CRAWLER_DIR = ROOT / "crawler"
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
SCHEMA_PATH = ROOT / "jobs-db" / "schema.sql"
WALKTHROUGH_PATH = ROOT / "scripts" / "ux-walkthrough" / "walkthrough.js"
EXEMPTIONS_PATH = Path(__file__).with_name("audit_exemptions.yaml")

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


# ══════════════════ 通用小工具：括号深度解析 ══════════════════
# JS/SQL 里的对象字面量、列定义都可能横跨多行、内部还嵌着括号（`Math.max(1, ...)`、
# `generated always as (case ... end) stored`），简单正则截断或按行处理都会在这种地方
# 断错。统一用「找匹配括号 + 按顶层逗号切分」两个函数，各处复用，别再各写一份。

def _match_bracket(text, open_idx):
    """`text[open_idx]` 必须是 `{`/`[`/`(` 之一，返回其匹配右括号的下标（闭区间）。"""
    opening = text[open_idx]
    if opening not in "{[(":
        raise ValueError(f"下标 {open_idx} 处不是左括号: {opening!r}")
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"括号从下标 {open_idx} 开始没有找到匹配")


def _strip_sql_line_comments(text):
    """去掉 `-- 注释到行尾`，逐行处理、保留换行（不动括号深度计数）。

    必须在 `_split_top_level` 切分列定义之前做——不然一行末尾的行内注释（本仓库
    schema.sql 里到处都是，比如 `grad_class smallint,   -- 届别…`）会跟下一列的
    定义被顶层逗号切分算法揽进同一个「entry」，而这个 entry 因为以 `--` 开头被当
    注释整段丢弃，**连带把紧跟在注释后面那一列也丢了**（这正是曾经真的把 `summary`
    列漏掉的根因，2026-09-18 复审时抓到）。用行级 truncate 而不是正则去全文匹配
    `--.*$`，因为多行模式下 `$` 的语义容易在这类场景里被用错。
    """
    return "\n".join(line.split("--", 1)[0] for line in text.split("\n"))


def _split_top_level(body):
    """按「深度为 0 的逗号」切分，深度由 `{[(` / `}])` 计——嵌套括号里的逗号不切。"""
    entries = []
    depth = 0
    current = []
    for ch in body:
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            entries.append("".join(current))
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        entries.append("".join(current))
    return entries


# ══════════════════ 豁免清单 ══════════════════

def load_exemptions(path=EXEMPTIONS_PATH):
    """`{category: {name: reason}}`。豁免必须带非空 reason，缺了直接抛错——不许静默消音。"""
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    out = {}
    for category, entries in doc.items():
        if not isinstance(entries, dict):
            raise ValueError(f"豁免分类 {category!r} 必须是 name: reason 的映射")
        for name, reason in entries.items():
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"豁免 {category}.{name} 缺 reason（拿不出理由就不许豁免）")
        out[category] = dict(entries)
    return out


def _exempt_names(exemptions, category):
    return set((exemptions or {}).get(category) or {})


# ══════════════════ 1a. 定时 workflow ══════════════════

def find_cron_workflows(workflows_dir=WORKFLOWS_DIR):
    """左边：所有带 `schedule: cron` 触发器的 workflow 文件相对路径。

    有意用纯文本正则而不是完整 yaml 解析触发器结构：PyYAML 会把裸的 `on:` 键当成
    YAML 1.1 布尔值 `True` 解析（这是 GitHub Actions workflow 文件的经典坑），
    纯文本找 `cron:` 字面量更直接也更不容易被这个坑绊倒。

    不强制要求引号——`cron: 0 3 * * *` 不加引号也是合法 YAML（星号在这个位置不触发
    YAML 的 flow 语法），只要求那一行确实以 `- cron:` 起头、后面跟着非空内容；
    行首（去掉前导空白后）是 `#` 的注释行天然不会匹配这个「以 `-` 起头」的锚点，
    所以「被注释掉的 cron」不会被算进来，不需要额外排除逻辑。
    """
    found = []
    if not workflows_dir.is_dir():
        return found
    for path in sorted(list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*-\s*cron\s*:\s*\S", text, re.M):
            found.append(f".github/workflows/{path.name}")
    return sorted(set(found))


def _pipeline_owners(checks):
    return {c["owner"] for c in checks if c.get("layer") == "pipeline"}


# ══════════════════ 1b. ops_runs 的 module 字面量 ══════════════════

# `record_ops_run(supabase_or_client, <第二个位置参数>, ...)`——第二个参数就是 module。
# 允许中间换行（\s 本来就匹配换行），所以多行调用（本仓库大多数调用点都是多行）也能命中。
# `(?<!def )` 排除 `def record_ops_run(...)` 这个函数定义本身（crawler/ops_runs.py 里
# 定义处的形参列表长得跟调用一模一样，不排除会把「定义」误判成一次「调用」）。
_RECORD_CALL_RE = re.compile(
    rf"(?<!def ){re.escape('record_ops_run')}\(\s*[\w.]+\s*,\s*(?:[\"']({_IDENT})[\"']|({_IDENT}))",
)
# JS 侧：`.from("ops_runs").insert({ ... module: "xxx" ... })`。跨行、非贪婪地找到 insert 块
# 里最先出现的 module 字面量即可——本仓库里每处 insert 只写一个 module。
_JS_OPS_RUNS_RE = re.compile(
    r"\.from\(\s*[\"']ops_runs[\"']\s*\)[\s\S]{0,400}?module\s*:\s*[\"'](" + _IDENT + r")[\"']",
)


def _resolve_identifier_literals(text, ident):
    """「模块名不是字面量、是一个变量」时，去同文件里找这个变量到底绑定过哪些字面量。

    覆盖三种写法：`module = "x"`、带类型标注的函数默认参数 `module: str = "x"`、
    三元表达式 `module = "x" if cond else "y"`（两个分支都收）。找不到任何绑定就
    返回空集合，调用方据此诚实报「读不出来」，不许猜。
    """
    literals = set()
    esc = re.escape(ident)
    for m in re.finditer(rf"\b{esc}\b\s*(?::\s*\w+\s*)?=\s*[\"']({_IDENT})[\"']", text):
        literals.add(m.group(1))
    for m in re.finditer(
        rf"\b{esc}\s*=\s*[\"']({_IDENT})[\"']\s+if\b[^\n]*?\belse\s+[\"']({_IDENT})[\"']",
        text,
    ):
        literals.add(m.group(1))
        literals.add(m.group(2))
    return literals


def find_ops_run_modules(crawler_dir=CRAWLER_DIR, scripts_dir=None):
    """左边：代码里实际写进 ops_runs.module 的字面量集合 + 读不出来的调用点清单。

    只扫 `*.py`（crawler 下）与 `*.js`（scripts 下）两类源码文件里能匹配到的调用
    点；用 shell/psql 直接拼 SQL `insert into ops_runs` 的写法（workflow yml 里
    内联的那种）不在扫描范围内，这类模块永远不会出现在左边、也就永远不会被
    这条差集揪出来——这是本函数明确划定的盲区，不是 bug。

    返回 `(modules, unreadable)`；`unreadable` 里的每条是 "文件路径:标识符"，
    表示这处调用把 module 存进了一个变量，而这个变量在同文件里找不到任何字面量绑定。
    """
    scripts_dir = scripts_dir or (ROOT / "scripts")
    display_root = crawler_dir.parent
    modules = set()
    unreadable = []

    for path in sorted(crawler_dir.rglob("*.py")):
        if path.name.startswith("test_"):
            continue  # 单测里出现的 "module" 字符串是断言用的假数据，不是真实调用点
        text = path.read_text(encoding="utf-8")
        for m in _RECORD_CALL_RE.finditer(text):
            literal, ident = m.group(1), m.group(2)
            if literal:
                modules.add(literal)
                continue
            resolved = _resolve_identifier_literals(text, ident)
            if resolved:
                modules |= resolved
            else:
                rel = path.relative_to(display_root)
                unreadable.append(f"{rel}:{ident}")

    for path in sorted(scripts_dir.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for m in _JS_OPS_RUNS_RE.finditer(text):
            modules.add(m.group(1))

    return modules, unreadable


def _module_registry():
    """晚导入：ops_watchdog 依赖较重，只有真跑到这一步才拉进来。"""
    import ops_watchdog
    return set(ops_watchdog.MODULE_OUTPUT) | set(ops_watchdog.NO_OUTPUT_MODULES)


# ══════════════════ 2. jobs 表列 ══════════════════

def parse_jobs_columns(schema_path=SCHEMA_PATH):
    """左边：jobs 表全部列名，纯文件解析（不连库）。

    覆盖两种来源：
      · `create table if not exists jobs (...)` 主体——用括号深度切分顶层逗号
        （不是按行/非贪婪正则截断），这样 `generated always as (case ... end)
        stored` 或多行 `check (... , ...)` 这类内部带逗号、跨多行的列定义不会被
        切错、后面的列也不会被误吞或丢掉。
      · `alter table (public.)?jobs add column if not exists <col> ...` 增量列
        （schema.sql 自己写明这类 alter 是「既有库 create-if-not-exists 不会补列」
        的幂等补丁，两处经常重复登记同一列——用 set 天然去重）。一条 `alter table`
        语句里可以连续写多个 `add column if not exists`（用逗号分隔多个子句），
        按语句切出来后对每条语句里的每个 `add column` 都收，不是只收第一个。
      · 显式排除 `job_events` / `job_closures` 等其它表——alter 的表名锚点用
        `\bjobs\b`（单词边界），"job_events"/"job_closures" 不含独立的 "jobs" 子串，
        不会被误当成本表的列。
    """
    text = schema_path.read_text(encoding="utf-8")

    columns = set()

    create_match = re.search(r"create\s+table\s+if\s+not\s+exists\s+jobs\s*(\()", text, re.I)
    if not create_match:
        raise ValueError("没找到 `create table if not exists jobs (...)`，schema.sql 格式变了？")
    open_idx = create_match.start(1)
    close_idx = _match_bracket(text, open_idx)
    body = _strip_sql_line_comments(text[open_idx + 1:close_idx])

    for entry in _split_top_level(body):
        stripped = entry.strip()
        if not stripped:
            continue
        if re.match(r"^constraint\b", stripped, re.I):
            continue  # 表级约束，不是列
        m = re.match(rf"^({_IDENT})\s+\S", stripped)
        if m:
            columns.add(m.group(1))

    for stmt in re.findall(r"alter\s+table\s+(?:public\.)?jobs\b.*?;", text, re.I | re.S):
        stmt = _strip_sql_line_comments(stmt)
        for m in re.finditer(
            rf"add\s+column\s+if\s+not\s+exists\s+({_IDENT})", stmt, re.I,
        ):
            columns.add(m.group(1))

    return columns


def _covers_columns(checks):
    """contract 里 layer=data 且 db=jobs 的检查项，`covers` 字段声明覆盖的列的并集。

    没写 `covers`（包括老检查项、以及像 `valid_active_total` 这种走函数、根本
    填不出具体列的检查）= 什么都没覆盖，只会让差集多报、不会漏报——这是故意的：
    宁可让人去核实一条「其实已经覆盖」的假阳性，也不许一条真的从没被度量的列
    因为「SQL 里凑巧出现过这个词」被判定成已覆盖（后者才是真正的假绿，也是
    这次返工要修的问题）。
    """
    referenced = set()
    for c in checks:
        if c.get("layer") != "data" or c.get("db") != "jobs":
            continue
        for col in (c.get("covers") or []):
            referenced.add(col)
    return referenced


def validate_covers(checks, jobs_columns):
    """`covers` 不能空口喊——每个声明的列必须：① 按词边界真出现在该条检查的 SQL 里；
    ② 真是 schema 解析出来的 jobs 列。两条任一不满足就抛错，逼着写检查项的人
    照实填、不能拿一个查询顺手多声明几个列骗过这个差集。

    故意放在这里而不是 `audit_runner.validate_contract` 里：`covers` 是本模块
    专属的扩展字段，`audit_runner` 的既有校验行为不该因为这个新字段而变化。
    """
    for c in checks:
        if c.get("layer") != "data" or c.get("db") != "jobs":
            continue
        covers = c.get("covers") or []
        if not isinstance(covers, list):
            raise ValueError(f"{c.get('id')}: covers 必须是列表")
        sql = c.get("sql") or ""
        sql_words = set(re.findall(_IDENT, sql))
        for col in covers:
            if col not in sql_words:
                raise ValueError(
                    f"{c.get('id')}: covers 声明了 {col!r}，但这个词没有按词边界出现在它的 sql 里"
                )
            if col not in jobs_columns:
                raise ValueError(
                    f"{c.get('id')}: covers 声明了 {col!r}，但 schema.sql 解析出的 jobs 列里没有它"
                    "（是不是列名拼错了，或者 schema 已经改过？）"
                )


# ══════════════════ 3. 体验层指标键 ══════════════════

def resolve_object_keys(text, ident, _seen=None):
    """在 `text` 里找 `const <ident> = { ... };` 这个对象字面量的顶层键。

    支持字面量内部再 `...other` 展开另一个同文件的 `const` 对象——递归解析、
    用 `_seen` 防环。解析不出来（没找到这个 `const` 声明，或者展开源不是一个
    能解析的普通对象字面量）返回 `None`，调用方据此诚实报 unreadable，不许猜。
    """
    seen = set(_seen or ())
    if ident in seen:
        return set()
    seen = seen | {ident}

    m = re.search(rf"\bconst\s+{re.escape(ident)}\s*=\s*(\{{)", text)
    if not m:
        return None
    open_idx = m.start(1)
    close_idx = _match_bracket(text, open_idx)
    body = text[open_idx + 1:close_idx]

    keys = set()
    for entry in _split_top_level(body):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("..."):
            sub_m = re.match(rf"^\.\.\.\s*({_IDENT})", entry)
            if not sub_m:
                return None
            resolved = resolve_object_keys(text, sub_m.group(1), seen)
            if resolved is None:
                return None
            keys |= resolved
            continue
        key_m = re.match(rf"^({_IDENT})\s*:", entry) or re.match(rf"^({_IDENT})\s*$", entry)
        if not key_m:
            return None
        keys.add(key_m.group(1))
    return keys


def _metrics_value_span(text):
    """定位 `.from("ops_runs").insert({ ... metrics: <值> ... })` 里 `metrics:` 后面
    那个值表达式的起止下标，连同它的形态（`"object"` 字面量 / `"ident"` 裸标识符）
    一起返回；找不到返回 `None`。

    只在 `.insert({...})` 调用自己的顶层括号内找 `metrics:`，不是全文搜——避免
    文件里其它地方偶然出现的同名字段把这个定位带偏。
    """
    call_m = re.search(r'\.from\(\s*["\']ops_runs["\']\s*\)\s*\.insert\(\s*(\{)', text)
    if not call_m:
        return None
    call_open = call_m.start(1)
    call_close = _match_bracket(text, call_open)
    body_start, body_end = call_open + 1, call_close

    field_m = re.search(r"\bmetrics\s*:\s*", text[body_start:body_end])
    if not field_m:
        return None
    value_start = body_start + field_m.end()

    i = value_start
    while i < body_end and text[i].isspace():
        i += 1
    if i >= body_end:
        return None
    if text[i] == "{":
        return (i, "object")
    ident_m = re.match(rf"({_IDENT})", text[i:body_end])
    if ident_m:
        return (i, "ident", ident_m.group(1))
    return None


def parse_walkthrough_metrics(path=WALKTHROUGH_PATH):
    """左边：walkthrough.js **真正写进 `ops_runs.metrics`** 的那个表达式的全部顶层键。

    这不等于 `const summary = {...}` 的键——实际写法是
    `metrics: { ...summary, issue_samples: issues.slice(0, 20) }`，`summary` 之外
    还显式塞了一个 `issue_samples`。展开 `...summary` 拿到它的顶层键，加上
    `issue_samples` 这个显式键，两者的并集才是真正落库的指标集合。嵌套对象
    （如 `latency`、`issues_by_type`）只算它们自己这一个顶层键，内部字段不算——
    那是台账里的明细，不是「指标口径」本身。

    返回 `(keys, unreadable)`；`unreadable` 是人话描述的解析失败点（例如 spread
    的来源不是本文件里能找到的普通对象字面量），不静默丢弃任何解析不了的键。
    """
    text = path.read_text(encoding="utf-8")
    span = _metrics_value_span(text)
    if span is None:
        raise ValueError(
            '没找到 `.from("ops_runs").insert({ metrics: ... })`，walkthrough.js 结构变了？'
        )

    keys = set()
    unreadable = []

    if span[1] == "object":
        open_idx = span[0]
        close_idx = _match_bracket(text, open_idx)
        body = text[open_idx + 1:close_idx]
        for entry in _split_top_level(body):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith("..."):
                sub_m = re.match(rf"^\.\.\.\s*({_IDENT})", entry)
                if not sub_m:
                    unreadable.append(f"metrics 里的 spread 解析不出标识符: {entry[:60]!r}")
                    continue
                resolved = resolve_object_keys(text, sub_m.group(1))
                if resolved is None:
                    unreadable.append(
                        f'metrics 里的 `...{sub_m.group(1)}` 不是本文件里能解析的 `const {sub_m.group(1)} = {{...}}`'
                    )
                else:
                    keys |= resolved
                continue
            key_m = re.match(rf"^({_IDENT})\s*:", entry) or re.match(rf"^({_IDENT})\s*$", entry)
            if key_m:
                keys.add(key_m.group(1))
            else:
                unreadable.append(f"metrics 对象里有一项解析不出键名: {entry[:60]!r}")
    else:  # ident：metrics 直接等于一个变量，不是内联对象字面量
        ident = span[2]
        resolved = resolve_object_keys(text, ident)
        if resolved is None:
            unreadable.append(f'metrics: {ident} 不是本文件里能解析的 `const {ident} = {{...}}`')
        else:
            keys |= resolved

    return keys, unreadable


def _experience_metric_refs(checks):
    """contract 里 layer=experience 的检查项，name/why/action/sql 文本里出现过的指标键。"""
    referenced = set()
    for c in checks:
        if c.get("layer") != "experience":
            continue
        blob = " ".join(str(c.get(f, "")) for f in ("sql", "name", "why", "action"))
        for word in re.findall(_IDENT, blob):
            referenced.add(word)
    return referenced


# ══════════════════ 汇总 ══════════════════

def _load_checks():
    import audit_runner
    return audit_runner.load_contract()


def compute_gaps(root=ROOT, checks=None, exemptions=None, exemptions_path=EXEMPTIONS_PATH):
    """核心差集计算。`checks`/`exemptions` 留了注入口子给单测用假数据，默认读真实文件。"""
    if checks is None:
        checks = _load_checks()
    if exemptions is None:
        exemptions = load_exemptions(exemptions_path)

    workflows_dir = root / ".github" / "workflows"
    crawler_dir = root / "crawler"
    scripts_dir = root / "scripts"
    schema_path = root / "jobs-db" / "schema.sql"
    walkthrough_path = root / "scripts" / "ux-walkthrough" / "walkthrough.js"

    cron_workflows = set(find_cron_workflows(workflows_dir))
    pipeline_exempt = _exempt_names(exemptions, "pipeline_workflows")
    pipeline_owners = _pipeline_owners(checks) | pipeline_exempt
    pipeline_workflows_gap = sorted(cron_workflows - pipeline_owners)

    ops_modules, module_unreadable = find_ops_run_modules(crawler_dir, scripts_dir)
    module_exempt = _exempt_names(exemptions, "pipeline_modules")
    module_registry = _module_registry() | module_exempt
    pipeline_modules_gap = sorted(ops_modules - module_registry)

    jobs_columns = parse_jobs_columns(schema_path)
    validate_covers(checks, jobs_columns)  # covers 里的每个列名都要经得起核对，不许空口声明
    column_exempt = _exempt_names(exemptions, "data_columns")
    covered_columns = _covers_columns(checks) | column_exempt
    data_columns_gap = sorted(jobs_columns - covered_columns)

    metrics, metrics_unreadable = parse_walkthrough_metrics(walkthrough_path)
    metric_exempt = _exempt_names(exemptions, "experience_metrics")
    covered_metrics = _experience_metric_refs(checks) | metric_exempt
    experience_metrics_gap = sorted(metrics - covered_metrics)

    # 陈旧豁免：豁免了一个已经不在左边枚举里的名字，说明这条豁免早就没有对应的东西了
    # （左边枚举变了——列被删、workflow 被删、指标改名），该删掉，免得误导下一个读者。
    stale = {}
    for category, left in (
        ("pipeline_workflows", cron_workflows),
        ("pipeline_modules", ops_modules),
        ("data_columns", jobs_columns),
        ("experience_metrics", metrics),
    ):
        exempt = _exempt_names(exemptions, category)
        gone = sorted(exempt - left)
        if gone:
            stale[category] = gone

    return {
        "pipeline_workflows": pipeline_workflows_gap,
        "pipeline_modules": pipeline_modules_gap,
        "data_columns": data_columns_gap,
        "experience_metrics": experience_metrics_gap,
        "unreadable": sorted(set(module_unreadable) | set(metrics_unreadable)),
        "stale_exemptions": stale,
    }


def render(gaps):
    labels = {
        "pipeline_workflows": "定时任务没有对应的链路期望（contract layer=pipeline 的 owner）",
        "pipeline_modules": "ops_runs 里出现的模块没有声明产出口径（ops_watchdog.MODULE_OUTPUT）",
        "data_columns": "jobs 表的列没有 covers 声明覆盖",
        "experience_metrics": "体验走查的指标没有任何体验层检查项引用",
    }
    lines = []
    for key, label in labels.items():
        items = gaps.get(key) or []
        lines.append(f"【{label}】{len(items)} 条")
        for item in items:
            lines.append(f"  - {item}")
    unreadable = gaps.get("unreadable") or []
    lines.append(f"【读不出来的调用点/表达式（同文件里找不到字面量绑定，不许猜）】{len(unreadable)} 条")
    for item in unreadable:
        lines.append(f"  - {item}")
    stale = gaps.get("stale_exemptions") or {}
    stale_total = sum(len(v) for v in stale.values())
    lines.append(f"【陈旧豁免（豁免的名字已经不在左边枚举里，该删了）】{stale_total} 条")
    for category, names in stale.items():
        for name in names:
            lines.append(f"  - {category}: {name}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，不打印人话报告")
    args = parser.parse_args(argv)

    gaps = compute_gaps()
    if args.json:
        print(json.dumps(gaps, ensure_ascii=False, indent=2))
    else:
        print(render(gaps))
        total = len(gaps["pipeline_workflows"]) + len(gaps["pipeline_modules"]) \
            + len(gaps["data_columns"]) + len(gaps["experience_metrics"]) \
            + len(gaps["unreadable"]) + sum(len(v) for v in gaps["stale_exemptions"].values())
        print(f"\n[audit-coverage] 差集共 {total} 条（含 unreadable/stale_exemptions）"
              "——非空不代表进程失败，这是发现不是错误")
    return 0  # 差集非空是「发现」，不是「错误」，永远退出 0（同 audit_runner 的 exit 语义）


if __name__ == "__main__":
    sys.exit(main())
