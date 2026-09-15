#!/bin/bash
# 公告制招聘：每日本机（中国大陆路由）抓取官方招聘公告 → announcement_postings（Supabase）。
#
# 为什么在本机跑而不是 GitHub Actions：很多省 gov 服务器 geo-block 境外 IP
# （GitHub US runner 与香港服务器 2026-09-15 实测都连不上山东/湖南/安徽/陕西/山西），
# 只有大陆 IP 能连。本机是大陆路由，故用它跑 --include-geo-blocked（含那 5 个省）。
# GitHub 的 announcement-crawl.yml 仍每天跑「境外可达的 4 省」作常开兜底，两边 upsert 幂等不冲突。
#
# 触发：~/Library/LaunchAgents/com.jobradar.announcement-crawl.plist（每日 12:30 本地时间）。
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
/usr/bin/python3 -m announcements.harvest --include-geo-blocked >> "$LOG" 2>&1
rc=$?
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 结束（exit $rc）=====" >> "$LOG"
exit $rc
