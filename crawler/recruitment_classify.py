"""入库时给岗位补「招聘类型」两列（recruitment_category / recruitment_explicit）。

为什么不在 Python 里重写规则：判「社招/校招/实习」的权威实现只有一份，在 JS
（lib/china-keyword-expansion.js 的七层裁决 + 完整单测）。把它翻译成 Python = 制造第二份
会各自漂移的实现——本仓库在 canonicalize_jd_url 上已经吃过「同一逻辑存三份、改一处忘两处」的亏。
这里隔一个进程调那份 JS，规则始终只有一处。

⚠️ 最重要的不变量：**分类失败绝不能让抓取失败**。任何异常（没装 node / 脚本报错 / 超时）
   一律静默降级成「不填这两列」，岗位照常入库，由 backfill-recruitment-category 的补漏任务捡回。
   把可用性押在一个可选的富化步骤上，是拿主链路换支线，不划算。
⚠️ 配套：jobs_db 把这两列放进 _PRESERVE_IF_EMPTY / _PRESERVE_IF_NULL —— 分类失败写 None 时
   **保留旧值**，不能把上一次算好的值抹成 NULL（与 summary 被列表重抓抹掉的老坑同形态）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

# 分类器的全部输入字段。多传是白传，少传会静默算错 —— 与 scripts/classify-recruitment.js 对齐。
_FIELDS = ("title", "summary", "jd_url", "apply_url", "job_type", "company", "experience")

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classify-recruitment.js"
_TIMEOUT_S = float(os.getenv("RECRUITMENT_CLASSIFY_TIMEOUT", "60"))
_DISABLED = os.getenv("RECRUITMENT_CLASSIFY_DISABLED", "").lower() in ("1", "true", "yes")

_warned = False


def _warn_once(msg: str) -> None:
    global _warned
    if not _warned:
        print(f"[recruitment-classify] 降级（岗位照常入库，等补漏任务）：{msg}", flush=True)
        _warned = True


def classify(jobs: Iterable[dict]) -> list[tuple[str | None, bool | None]]:
    """批量分类，返回与输入等长的 [(category, explicit)]；任何失败一律返回全 (None, None)。"""
    items = list(jobs)
    if not items:
        return []
    if _DISABLED:
        return [(None, None)] * len(items)
    node = shutil.which("node")
    if not node or not _SCRIPT.exists():
        _warn_once("未找到 node 或分类脚本")
        return [(None, None)] * len(items)

    payload = json.dumps(
        [{f: j.get(f) for f in _FIELDS} for j in items], ensure_ascii=False
    )
    try:
        proc = subprocess.run(
            [node, str(_SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
        if proc.returncode != 0:
            _warn_once(f"分类脚本退出码 {proc.returncode}: {proc.stderr.strip()[:160]}")
            return [(None, None)] * len(items)
        out = json.loads(proc.stdout)
        if not isinstance(out, list) or len(out) != len(items):
            _warn_once("分类结果条数与输入不符")
            return [(None, None)] * len(items)
        return [(o.get("category"), o.get("explicit")) for o in out]
    except Exception as exc:  # noqa: BLE001 —— 故意兜住一切，主链路不能被支线拖垮
        _warn_once(f"{type(exc).__name__}: {exc}")
        return [(None, None)] * len(items)


# ⚠️ 这两列的「所有权」在数据库，不在写入方（2026-09-03）。
# 库里有触发器 jobs_guard_recruitment_class（jobs-db/schema.sql）替它们把门：
#   · 分类依据（title/summary/job_type/jd_url/apply_url/company/experience）变了 → 结论作废置 NULL
#   · 依据没变却有人想改这两列 → 驳回，保留库里那份
#   · 只有重算任务（打了 `set jobradar.reclassify='on'` 标记）能写值
# 所以这里**只管 INSERT 那一次**：新行的 payload 就是整行内容，算出来必然自洽。
# UPDATE 时本模块算出来的值会被触发器按上面的规则处理，写入方无需（也无法）自己拿捏。
# 为什么要交给数据库：写入方有 4 条以上（爬虫 upsert / 爬虫富化 / app upsert / app 富化）、
# 语言还不同，靠每个人自觉 = 下一条新路径原样复发（实测漂过 8,140 行 / 1.93%）。

def annotate(jobs: list[dict[str, Any]]) -> None:
    """就地给每个 job 补上两列。已经带值的行不覆盖（调用方可能已算过）。

    ⚠️ 这里**再兜一层异常**（classify 内部已经兜过）：这是写库主链路上的一个可选富化步骤，
    任何从意料之外的路径冒出来的异常都不许冒泡到 upsert —— 否则一个支线故障会让整源抓取失败。
    降级后两列留空，由 backfill-recruitment-category 的定时任务捡回。
    """
    try:
        todo = [j for j in jobs if j.get("recruitment_category") is None]
        if not todo:
            return
        for job, (cat, exp) in zip(todo, classify(todo)):
            job["recruitment_category"] = cat
            job["recruitment_explicit"] = exp
    except Exception as exc:  # noqa: BLE001 —— 主链路不能被支线拖垮，见上
        _warn_once(f"annotate 异常 {type(exc).__name__}: {exc}")
