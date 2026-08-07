"""校招高频车道的频率闸 —— 判断「本轮该不该跑」，供 campus-crawl.yml 的前置 job 调用。

背景（2026-08-07 实测）：GitHub 在平台高负载时会静默丢弃 schedule 触发。
cron "20 * * * *" 声称每小时一轮，实际只跑出 ~7 次/天、相邻两轮平均间隔 171 分钟，
车道的真实节奏只有设计值的 1/3 —— 秋招开闸后最坏要等 3 小时才被发现。
对策：cron 加密到每 20 分钟，多出来的轮次由这道闸挡回去。

⚠️ 本文件**只准用标准库**。它跑在一个不装 crawler/requirements.txt 的轻量 job 里
（整轮 ~10 秒），就是为了让「不该跑」的那些轮次不必花 2-3 分钟装依赖和 chromium。
唯一允许的项目内 import 是 campus_lane（该模块同样只依赖标准库）。

判据本身在 campus_lane.is_due，与 campus_crawl 主流程共用同一个实现 —— 不做第二份镜像。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import campus_lane


TIMEOUT_SECONDS = 15


def _log(msg: str) -> None:
    print(f"[campus-gate] {msg}", flush=True)


def last_lane_finished_at(supabase_url: str, service_key: str):
    """ops_runs 里 module='campus_lane' 的最新 finished_at；取不到返回 None。

    用 ops_runs 而不是「上一个 workflow run 的时间」：早退的轮次同样会让 run 记成 success，
    拿它当基准会让时间戳被每次早退一路往后推，最终车道再也跑不起来。
    ops_runs 只在车道真跑完时才写，是「真跑过」的权威证据。
    """
    query = urllib.parse.urlencode({
        "module": "eq.campus_lane",
        "select": "finished_at",
        "order": "finished_at.desc",
        "limit": "1",
    })
    url = f"{supabase_url.rstrip('/')}/rest/v1/ops_runs?{query}"
    req = urllib.request.Request(url, headers={
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    return rows[0].get("finished_at") if rows else None


def decide() -> bool:
    """本轮该不该跑。任何异常一律返回 True —— 漏跑会错过开闸窗口，多跑只是多花几分钟 CI。"""
    force = (os.environ.get("CAMPUS_LANE_FORCE") or "").lower() in ("1", "true", "yes")
    now = datetime.now(timezone.utc)

    # 淡季直接不起 job。主流程里也有同一道判断（直接跑脚本时仍会挡），这里前置只为省掉
    # 装依赖 + 装 chromium 的 2-3 分钟——秋招淡季按每 20 分钟算是每天 72 次无谓开销。
    if not campus_lane.is_campus_season(now.month) and not force:
        _log(f"{now.month} 月为校招淡季，本轮跳过（强跑设 CAMPUS_LANE_FORCE=true）。")
        return False

    if force:
        _log("CAMPUS_LANE_FORCE=true，跳过频率闸直接跑。")
        return True

    # 频率闸只管定时触发。人手动点了 Run workflow 却因为「20 分钟前刚跑过」什么都不发生，
    # 是最容易让人以为流水线坏了的一种行为——手动触发一律放行。
    event = os.environ.get("GITHUB_EVENT_NAME") or ""
    if event and event != "schedule":
        _log(f"事件 {event}（非定时触发）→ 跳过频率闸，直接跑。")
        return True

    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        _log("⚠️ 未配置 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，无法查台账 → 放行本轮。")
        return True

    try:
        last = last_lane_finished_at(supabase_url, service_key)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, TimeoutError) as exc:
        _log(f"⚠️ 查 ops_runs 台账失败（{type(exc).__name__}）→ 放行本轮，宁可多跑一轮。")
        return True

    due = campus_lane.is_due(last, now)
    if due:
        _log(f"上轮跑完于 {last or '（无记录）'} → 已达最小间隔"
             f" {campus_lane.MIN_LANE_INTERVAL_MINUTES}min，本轮开跑。")
    else:
        _log(f"上轮跑完于 {last}，距今不足 {campus_lane.MIN_LANE_INTERVAL_MINUTES}min → 本轮跳过。"
             f"（cron 每 20min 触发是为了对冲 GitHub 丢触发，不是真要每 20min 抓一遍）")
    return due


def main() -> int:
    due = decide()
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"due={'true' if due else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
