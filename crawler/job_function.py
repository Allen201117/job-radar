"""岗位职能分类的 Python 侧薄封装：隔一个进程调 JS 权威实现。

为什么不在 Python 里重写：与 crawler/recruitment_classify.py 同理——判「研发/产品/销售…」
的权威词表只有一份，在 lib/china-keyword-expansion.js。翻译一份到 Python = 制造第二份会漂移
的实现（本仓库在 canonicalize_jd_url 上吃过这个亏，CLAUDE.md 明确禁止 UI/派生层留第二份词表）。

⚠️ 与 recruitment_classify 的失败语义不同：那边在**抓取主链路**上，失败必须静默降级；
   这里在**离线派生链路**上，失败应当让调用方看得见（返回全 None），由调用方决定
   「这一批不出 function_share」——绝不能悄悄按「其他」算，那会把分布统计做成假数据。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classify-job-function.js"
_TIMEOUT_S = float(os.getenv("JOB_FUNCTION_CLASSIFY_TIMEOUT", "120"))
# 一批多少条。进程启动是主要开销，但 argv/stdin 也不宜无限大。
BATCH_SIZE = int(os.getenv("JOB_FUNCTION_BATCH", "2000"))


def _run_batch(titles: list[str]) -> list[str | None]:
    node = shutil.which("node")
    if not node or not _SCRIPT.exists():
        raise RuntimeError("未找到 node 或 scripts/classify-job-function.js")
    payload = json.dumps([{"title": t or ""} for t in titles], ensure_ascii=False)
    proc = subprocess.run(
        [node, str(_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"分类脚本退出码 {proc.returncode}: {proc.stderr.strip()[:200]}")
    out = json.loads(proc.stdout)
    if not isinstance(out, list) or len(out) != len(titles):
        raise RuntimeError("分类结果条数与输入不符")
    return [str(v) if v else None for v in out]


def classify_titles(titles: Iterable[str]) -> list[str | None]:
    """批量分类岗位标题，返回与输入等长的职能桶名；失败时返回全 None（调用方据此弃权）。"""
    items = [str(t or "") for t in titles]
    if not items:
        return []
    out: list[str | None] = []
    try:
        for start in range(0, len(items), BATCH_SIZE):
            out.extend(_run_batch(items[start:start + BATCH_SIZE]))
    except Exception as exc:  # noqa: BLE001 —— 派生层弃权，不是静默按「其他」算
        print(f"[job-function] 分类失败，本轮不产出职能分布：{type(exc).__name__}: {exc}", flush=True)
        return [None] * len(items)
    return out
