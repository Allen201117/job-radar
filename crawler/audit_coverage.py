"""覆盖率差集：没有声明期望的东西，本身就是告警。

`audit_runner.py` 只跑 `audit_contract.yaml` 里已经写好的检查项——它回答不了
「有没有东西根本没被纳入期望清单」。本模块回答的是这个问题，做法是三组差集，
每组左边都是**自动枚举**（不靠人维护清单，代码/配置改了差集自己会变），右边是
「期望清单里声明覆盖了的」∪「显式豁免」：

  1. 链路层：定时 workflow ∖ contract layer=pipeline 的 owner；
     以及 ops_runs 的 module 字面量 ∖ ops_watchdog.py 的 MODULE_OUTPUT/NO_OUTPUT_MODULES。
  2. 数据层：jobs 表全部列（纯解析 jobs-db/schema.sql，不连库）∖ contract layer=data
     且 db=jobs 的 SQL 里出现过的列名。
  3. 体验层：scripts/ux-walkthrough/walkthrough.js 写进 ops_runs 的指标键
     ∖ contract layer=experience 的检查项 SQL/文本里出现过的指标键。

豁免必须带非空 reason（`audit_exemptions.yaml`），没有理由的豁免在 `load_exemptions` 里
直接抛错——拿不出理由就不许消音这条差集。

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
    """
    found = []
    if not workflows_dir.is_dir():
        return found
    for path in sorted(workflows_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*-\s*cron\s*:\s*['\"]", text, re.M):
            found.append(f".github/workflows/{path.name}")
    return found


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
# 解析「模块名不是字面量、是一个变量」时，去同文件里找这个变量到底绑定过哪些字面量。
# 覆盖两种写法：`module = "x"`（含函数默认参数 `module: str = "x"`）与三元表达式
# `module = "x" if cond else "y"`。找不到任何绑定就诚实报「读不出来」，不许猜。
def _resolve_identifier_literals(text, ident):
    literals = set()
    esc = re.escape(ident)
    # 普通赋值 `module = "x"`，或带类型标注的函数默认参数 `module: str = "x"`。
    for m in re.finditer(rf"\b{esc}\b\s*(?::\s*\w+\s*)?=\s*[\"']({_IDENT})[\"']", text):
        literals.add(m.group(1))
    # 三元表达式 `module = "x" if cond else "y"`——两个分支都要收。
    for m in re.finditer(
        rf"\b{esc}\s*=\s*[\"']({_IDENT})[\"']\s+if\b[^\n]*?\belse\s+[\"']({_IDENT})[\"']",
        text,
    ):
        literals.add(m.group(1))
        literals.add(m.group(2))
    return literals


def find_ops_run_modules(crawler_dir=CRAWLER_DIR, scripts_dir=None):
    """左边：代码里实际写进 ops_runs.module 的字面量集合 + 读不出来的调用点清单。

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

    覆盖两种来源：`create table ... jobs (...)` 主体里的列定义，以及后续
    `alter table jobs add column if not exists <col> ...` 增量列（schema.sql 自己写明
    这类 alter 是「既有库 create-if-not-exists 不会补列」的幂等补丁，两处经常重复登记
    同一列——用 set 天然去重）。
    """
    text = schema_path.read_text(encoding="utf-8")

    columns = set()

    create_match = re.search(r"create\s+table\s+if\s+not\s+exists\s+jobs\s*\((.*?)\n\);", text, re.S | re.I)
    if not create_match:
        raise ValueError("没找到 `create table if not exists jobs (...)`，schema.sql 格式变了？")
    body = create_match.group(1)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if re.match(r"^constraint\b", stripped, re.I):
            continue  # 表级约束，不是列
        m = re.match(rf"^({_IDENT})\s+\S", stripped)
        if m:
            columns.add(m.group(1))

    for m in re.finditer(
        rf"alter\s+table\s+jobs\s+add\s+column\s+if\s+not\s+exists\s+({_IDENT})",
        text, re.I,
    ):
        columns.add(m.group(1))

    return columns


def _data_jobs_column_refs(checks):
    """contract 里 layer=data 且 db=jobs 的检查项，SQL 文本里按词边界出现过的列名。"""
    referenced = set()
    for c in checks:
        if c.get("layer") != "data" or c.get("db") != "jobs":
            continue
        sql = c.get("sql") or ""
        for word in re.findall(_IDENT, sql):
            referenced.add(word)
    return referenced


# ══════════════════ 3. 体验层指标键 ══════════════════

def parse_walkthrough_metrics(path=WALKTHROUGH_PATH):
    """左边：walkthrough.js 写进 ops_runs.metrics 的所有指标键。

    只解析 `const summary = { ... };` 这个对象字面量的**顶层**键（嵌套对象如
    `latency` 内部的每接口耗时不算「指标键」，那是明细不是台账口径）。用括号计深度
    做逗号切分，而不是简单 split(",")，因为字面量里有 `Math.max(1, ...)` 这类嵌套逗号。
    """
    text = path.read_text(encoding="utf-8")
    m = re.search(r"const\s+summary\s*=\s*\{", text)
    if not m:
        raise ValueError("没找到 `const summary = {...}`，walkthrough.js 结构变了？")
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if i >= len(text):
            raise ValueError("summary 对象字面量没有匹配的右括号")
        ch = text[i]
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        i += 1
    body = text[start:i - 1]

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

    keys = set()
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        m2 = re.match(rf"^({_IDENT})\s*:", entry)
        if m2:
            keys.add(m2.group(1))
        else:
            m3 = re.match(rf"^({_IDENT})\s*$", entry)
            if m3:
                keys.add(m3.group(1))  # 简写属性 `latency,` == `latency: latency,`
    return keys


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
    pipeline_owners = _pipeline_owners(checks) | _exempt_names(exemptions, "pipeline_workflows")
    pipeline_workflows_gap = sorted(cron_workflows - pipeline_owners)

    ops_modules, unreadable = find_ops_run_modules(crawler_dir, scripts_dir)
    module_registry = _module_registry() | _exempt_names(exemptions, "pipeline_modules")
    pipeline_modules_gap = sorted(ops_modules - module_registry)

    jobs_columns = parse_jobs_columns(schema_path)
    covered_columns = _data_jobs_column_refs(checks) | _exempt_names(exemptions, "data_columns")
    data_columns_gap = sorted(jobs_columns - covered_columns)

    metrics = parse_walkthrough_metrics(walkthrough_path)
    covered_metrics = _experience_metric_refs(checks) | _exempt_names(exemptions, "experience_metrics")
    experience_metrics_gap = sorted(metrics - covered_metrics)

    return {
        "pipeline_workflows": pipeline_workflows_gap,
        "pipeline_modules": pipeline_modules_gap,
        "data_columns": data_columns_gap,
        "experience_metrics": experience_metrics_gap,
        "unreadable": sorted(unreadable),
    }


def render(gaps):
    labels = {
        "pipeline_workflows": "定时任务没有对应的链路期望（contract layer=pipeline 的 owner）",
        "pipeline_modules": "ops_runs 里出现的模块没有声明产出口径（ops_watchdog.MODULE_OUTPUT）",
        "data_columns": "jobs 表的列没有任何数据层检查项引用",
        "experience_metrics": "体验走查的指标没有任何体验层检查项引用",
    }
    lines = []
    for key, label in labels.items():
        items = gaps.get(key) or []
        lines.append(f"【{label}】{len(items)} 条")
        for item in items:
            lines.append(f"  - {item}")
    unreadable = gaps.get("unreadable") or []
    lines.append(f"【读不出来的调用点（module 是变量，同文件里找不到字面量绑定）】{len(unreadable)} 条")
    for item in unreadable:
        lines.append(f"  - {item}")
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
        total = sum(len(v) for v in gaps.values())
        print(f"\n[audit-coverage] 差集共 {total} 条（含 unreadable）——非空不代表进程失败，这是发现不是错误")
    return 0  # 差集非空是「发现」，不是「错误」，永远退出 0（同 audit_runner 的 exit 语义）


if __name__ == "__main__":
    sys.exit(main())
