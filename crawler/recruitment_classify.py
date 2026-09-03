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


# 分类输入里、upsert 会「新值为空则保留旧值」的那几列（与 jobs_db._PRESERVE_IF_EMPTY 同口径）。
# education / deadline / salary_text 也被保留，但它们不是分类输入，与这里无关。
_PRESERVED_INPUTS = ("summary", "job_type", "experience")


def carries_full_inputs(job: dict[str, Any]) -> bool:
    """本次 payload 是否带齐了「会被保留规则替换掉」的那几个分类输入。"""
    return all(str(job.get(f) or "").strip() for f in _PRESERVED_INPUTS)


def drop_for_thin_update(job: dict[str, Any]) -> None:
    """UPDATE 且 payload 偏瘦时，把算好的分类作废（置 None）→ 由 _PRESERVE_IF_* 保留库里那份。

    ⚠️ 为什么必须这样（2026-09-03 线上实锤 5,275 行）：分类是拿**这次抓到的 payload** 算的，
    而落库时 summary / job_type / experience 走「新值为空则保留旧值」→ 最终那一行是
    「旧的富字段 + 用瘦 payload 算出来的分类」，两者对不上。典型症状：`job_type='社招'` 却
    `recruitment_explicit=false` —— 规则里只要 job_type 有值就必然是「有据」，这个状态逻辑上
    不可能出现，除非分类算的时候 job_type 是空的。
    后果不只是数字难看：检索侧按这两列**排除**候选（lib/jobs-store/search.ts），
    一个真校招岗被记成社招就会被挡在候选之外 → 用户搜「校招」永远搜不到它。

    保留旧值是安全的：那份是它被写进去时按当时整行算出来的，自洽。
    标题等「列表每次都带」的字段真变了导致的陈旧，由 backfill-recruitment-category
    的定时全量重算兜底（它读的是库里最终那一行，不会有这个错位）。
    """
    if carries_full_inputs(job):
        return
    job["recruitment_category"] = None
    job["recruitment_explicit"] = None


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
