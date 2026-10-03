#!/bin/bash
# 公告制招聘：每日本机（中国大陆路由）抓取官方招聘公告 → announcement_postings（Supabase）。
#
# 为什么在本机跑而不是 GitHub Actions：很多省 gov 服务器 geo-block 境外 IP
# （GitHub US runner 与香港服务器 2026-09-15 实测都连不上山东/湖南/安徽/陕西/山西），
# 只有大陆 IP 能连。本机是大陆路由，故用它跑 --include-geo-blocked（含那 5 个省）。
# GitHub 的 announcement-crawl.yml 仍每天跑「境外可达的 4 省」作常开兜底，两边 upsert 幂等不冲突。
#
# 触发：Mac：~/Library/LaunchAgents/com.jobradar.announcement-crawl.plist；Windows：任务计划程序 \ClaudeMigration\JobRadar-announcement-crawl（解释器经 JOBRADAR_PYTHON 指定）（均每日 12:30 本地时间）。
# 日志：~/Library/Logs/jobradar-announcement.log。停用：launchctl bootout gui/$(id -u) <plist> 或删 plist。
set -uo pipefail

# 仓库根 = 本脚本所在 scripts/ 的上一级（不写死绝对路径——本仓公开，不能出现本机用户名）。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG="$HOME/Library/Logs/jobradar-announcement.log"
mkdir -p "$(dirname "$LOG")"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 开始 =====" >> "$LOG"

cd "$REPO" || { echo "[err] repo 不存在: $REPO" >> "$LOG"; exit 1; }
# 尽量更新到最新 main（干净且在 main 上才 ff 成功；否则跳过、跑现有代码，绝不因此挂掉）。
GIT_TERMINAL_PROMPT=0 git pull --ff-only origin main >> "$LOG" 2>&1 \
  || echo "[warn] git pull 跳过（非 main / 有本地改动 / 无凭据），跑现有代码" >> "$LOG"

# Supabase 密钥从 .env.local 读（绝不打印）。
set -a; source "$REPO/.env.local" 2>/dev/null; set +a

cd "$REPO/crawler" || { echo "[err] 无 crawler 目录" >> "$LOG"; exit 1; }
# 解释器：JOBRADAR_PYTHON 优先（Windows 定时任务指向装好 crawler 依赖 + tzdata 的 venv）；
# 否则 Mac 走系统 /usr/bin/python3（原行为不变），都没有才用 PATH 上的 python3。
# ⚠️ Windows 自带的 python 没有时区库，ops_runs 记台账时 ZoneInfo("Asia/Shanghai") 直接抛错 → 整轮没有运行记录。
PY="${JOBRADAR_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x /usr/bin/python3 ]; then PY=/usr/bin/python3; else PY=python3; fi
fi
echo "[info] python = $PY" >> "$LOG"
"$PY" -m announcements.harvest --include-geo-blocked >> "$LOG" 2>&1
rc=$?

# 国聘（央企/地方国企公告，JSON 接口）——各省人社厅结构性够不着的那块供给。
"$PY" -m announcements.iguopin >> "$LOG" 2>&1 || echo "[warn] 国聘抓取失败（不影响整轮）" >> "$LOG"

# 每日复验：逐条真抓正文，判「现在还能不能报」，报不了的下架。
# 本机是大陆路由，够得着**全部**省份——GitHub runner 够不着的那些省只有这里能复验。
"$PY" -m announcements.verify >> "$LOG" 2>&1 || echo "[warn] 公告复验失败（不影响整轮）" >> "$LOG"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 结束（exit $rc）=====" >> "$LOG"
exit $rc
