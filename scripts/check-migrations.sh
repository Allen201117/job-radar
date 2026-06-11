#!/usr/bin/env bash
# 校验 supabase/migrations/*.sql 文件名前缀：① 必须为纯数字 ② 不得重复。
# 由 .github/workflows/migrate.yml 在 apply 之前调用——校验失败则不 apply。
#
# 为什么需要它：db-migrate.sh 按【完整文件名】追踪 schema_migrations，所以重复前缀
#   侥幸能跑；但「前缀按序递增」是项目约定，且 BASELINE 用字符串比较，重复/非数字前缀
#   存在踩坑空间。本脚本把这条约定变成 CI 硬门禁。
#
# 历史已应用的重复前缀：schema_migrations 按文件名记录，重命名会触发重跑（破坏生产），
#   所以【不改名】，改为在 GRANDFATHERED 白名单里豁免。白名单只收录历史既存文件——任何
#   【新增】重复（包括给已豁免前缀再加一个文件）都会被拦下。
#
# 兼容性：只用 POSIX-ish 构造（无 bash4 关联数组），可在 macOS 自带 bash 3.2 下运行。
set -euo pipefail

MIG_DIR="${1:-supabase/migrations}"

# —— 历史遗留重复前缀文件（已应用到生产，禁止改名）。新增重复禁止加进此列表，应改前缀。
GRANDFATHERED='015_seed_more_foreign_ats_sources.sql
015_verify_experience_sources.sql
016_job_structured_fields.sql
016_rewrite_culture_and_experience_copy.sql
098_seed_foreign_hardbones.sql
098_seed_probed_sources.sql
099_seed_foreign_hardbones.sql
099_seed_probed_sources.sql
105_dedup_foreign_source_names.sql
105_seed_probed_sources.sql
133_job_enrich_tracking.sql
133_seed_probed_sources.sql'

is_grandfathered() { printf '%s\n' "$GRANDFATHERED" | grep -Fxq "$1"; }

fail=0

names="$(ls -1 "$MIG_DIR"/*.sql 2>/dev/null | sed 's#.*/##' || true)"
if [ -z "$names" ]; then
  echo "ERROR: $MIG_DIR 下没有 .sql 迁移文件"
  exit 1
fi

# ① 前缀必须纯数字
while IFS= read -r name; do
  [ -z "$name" ] && continue
  prefix="${name%%_*}"
  if ! printf '%s' "$prefix" | grep -qE '^[0-9]+$'; then
    echo "ERROR: 非数字前缀: $name (前缀='$prefix')"
    fail=1
  fi
done <<EOF
$names
EOF

# ② 前缀不得重复（历史白名单豁免）
dups="$(printf '%s\n' "$names" | sed -E 's/^([0-9]+)_.*/\1/' | sort | uniq -d || true)"
while IFS= read -r prefix; do
  [ -z "$prefix" ] && continue
  group="$(printf '%s\n' "$names" | grep -E "^${prefix}_" || true)"
  unwl=0
  while IFS= read -r nf; do
    [ -z "$nf" ] && continue
    is_grandfathered "$nf" || unwl=1
  done <<INNER
$group
INNER
  oneline="$(printf '%s' "$group" | tr '\n' ' ')"
  if [ "$unwl" -eq 0 ]; then
    echo "OK(historical) 前缀 $prefix 重复但已豁免: $oneline"
  else
    echo "ERROR: 新增重复前缀 $prefix: $oneline"
    echo "       → 请改名为未占用前缀（先 ls $MIG_DIR 确认）。历史豁免名单见本脚本 GRANDFATHERED。"
    fail=1
  fi
done <<EOF
$dups
EOF

if [ "$fail" -ne 0 ]; then
  echo "[check-migrations] 失败：迁移前缀有问题（见上）。"
  exit 1
fi
echo "[check-migrations] 通过：$(printf '%s\n' "$names" | grep -c .) 个迁移文件，前缀纯数字、无新增重复。"
