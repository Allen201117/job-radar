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

# ③ 新迁移不得写带招聘渠道后缀的公司名（「X 校招」「X 实习」「X 社招」）。
#    渠道看 sources.board 与逐岗分类，不写进公司名：岗位公司名直接抄源名，后缀会跟着出现在岗位卡、公司筛选里，
#    还让同一家公司在洞察库长出几个画像（迁移 317）。迁移 320 把存量 55 条改回来了，这里防它再长出来。
#    判据 = 非注释行里有「以空白 + 校招/实习/社招 结尾」的 SQL 字符串字面量。只查前缀 > 基线的文件（历史文件不动）。
#    确实需要写出旧名的（比如清理别名），在那一行行尾加注释 -- allow-channel-suffix。
CHANNEL_SUFFIX_BASELINE=320
while IFS= read -r name; do
  [ -z "$name" ] && continue
  prefix="${name%%_*}"
  case "$prefix" in '' | *[!0-9]*) continue ;; esac   # 非数字前缀已在 ① 报过
  [ "$((10#$prefix))" -gt "$CHANNEL_SUFFIX_BASELINE" ] || continue
  hits="$(grep -nE "'[^']*[[:space:]](校招|实习|社招)'" "$MIG_DIR/$name" \
            | grep -vE '^[0-9]+:[[:space:]]*--' \
            | grep -v 'allow-channel-suffix' || true)"
  if [ -n "$hits" ]; then
    echo "ERROR: $name 里有带渠道后缀的名字（公司名不写「校招 / 实习 / 社招」，渠道看 board）："
    printf '%s\n' "$hits" | sed 's/^/         /'
    fail=1
  fi
done <<EOF
$names
EOF

# ④ 新迁移在 public 建表：同一个文件里开 RLS + 写 grant；bigserial 列再给序列授权（identity 列不用）。
#    Supabase 2026-10-30 起新表不再自动授权 anon / authenticated / service_role，不写 grant 网站和爬虫读写就 42501；
#    给了读权限却没开 RLS = Security Advisor 的 rls_disabled_in_public。来龙去脉见 CLAUDE.md「数据库迁移」。
#    只走 psql 的表在建表语句那几行里加注释 -- no-data-api，免授权检查（RLS 照开）。只查前缀 > 基线的新文件。
GRANT_BASELINE=335
NO_API='__no_data_api__'
create_re='(^|[^a-z0-9_])create[[:space:]]+(unlogged[[:space:]]+)?table[[:space:]]+(if[[:space:]]+not[[:space:]]+exists[[:space:]]+)?[a-z0-9_."]+'
grant_re='(^|[^a-z0-9_])grant[[:space:]]'
non_table_grant_re='[[:space:]]on[[:space:]]+(function|procedure|routine|sequence|schema|type|domain|database|language|all)[[:space:]]'
all_tables_re='on[[:space:]]+all[[:space:]]+tables[[:space:]]+in[[:space:]]+schema[[:space:]]+public'
rls_re='enable[[:space:]]+row[[:space:]]+level[[:space:]]+security'
serial_re='[a-z0-9_"][[:space:]]+(small|big)?serial([^a-z0-9_]|$)'   # 只认「列名 + serial」的类型位置，叫 serial 的列不算
# 不用 grep -q：pipefail 下 grep 提前退出会让 printf 吃 SIGPIPE，大文件里会误判成「没写」。
has() { printf '%s\n' "$1" | grep -E "$2" >/dev/null; }
while IFS= read -r name; do
  [ -z "$name" ] && continue
  prefix="${name%%_*}"
  case "$prefix" in '' | *[!0-9]*) continue ;; esac
  [ "$((10#$prefix))" -gt "$GRANT_BASELINE" ] || continue
  # 小写 → 去注释（只认行首或空白后的 --，URL 里的 Analyst--Wealth 不是注释；no-data-api 标记换成占位词挪到行首，
  # 免得写在分号后面被切进下一句）→ 整份连成一行再按分号切成一句一行（建表语句常跨行）。
  stmts="$(LC_ALL=C tr 'A-Z' 'a-z' < "$MIG_DIR/$name" \
             | LC_ALL=C sed -E -e "s/^([[:space:]]*[^-[:space:]].*[[:space:]])--[[:space:]]*no-data-api.*\$/ $NO_API \\1/" \
                               -e 's/(^|[[:space:]])--.*$/\1/' \
             | LC_ALL=C tr '\n;' ' \n')"
  creates="$(printf '%s\n' "$stmts" | grep -E "$create_re" || true)"
  [ -n "$creates" ] || continue
  grants="$(printf '%s\n' "$stmts" | grep -E "$grant_re" || true)"
  table_grants="$(printf '%s\n' "$grants" | grep -vE "$non_table_grant_re" || true)"
  rls="$(printf '%s\n' "$stmts" | grep -E "$rls_re" || true)"
  while IFS= read -r stmt; do
    [[ $stmt =~ $create_re ]] || continue
    ident="${BASH_REMATCH[0]##*[[:space:]]}"
    ident="${ident//\"/}"
    case "$ident" in
      *.*) [ "${ident%%.*}" = "public" ] || continue; t="${ident#*.}" ;;
      *) t="$ident" ;;
    esac
    word="(^|[^a-z0-9_])${t}([^a-z0-9_]|\$)"
    if ! has "$rls" "$word"; then
      echo "ERROR: $name 在 public 建了表 $t，没开 RLS。加：alter table public.$t enable row level security;（迁移里临时用的表改用 create temp table）"
      fail=1
    fi
    case "$stmt" in *"$NO_API"*) continue ;; esac
    if ! has "$table_grants" "$word" && ! has "$grants" "$all_tables_re"; then
      echo "ERROR: $name 在 public 建了表 $t，没写 grant（Supabase 2026-10-30 起新表不再自动授权）。"
      echo "       按谁要用来写，例如：grant select, insert, update, delete on public.$t to service_role;"
      echo "       网站登录用户要读写再加 authenticated，未登录要读再加 anon。只走 psql 的表在建表语句里加注释 -- no-data-api。"
      fail=1
    fi
    if has "$stmt" "$serial_re" \
       && ! has "$grants" "on[[:space:]]+(sequence[[:space:]].*[^a-z0-9_]${t}_|all[[:space:]]+sequences)"; then
      echo "ERROR: $name 的表 $t 用了 serial 自增列，没给序列授权（不给插不进去）。"
      echo "       加：grant usage, select on sequence public.${t}_id_seq to service_role;（列名不是 id 就换成对应序列名），或改用 identity 列。"
      fail=1
    fi
  done <<INNER
$creates
INNER
done <<EOF
$names
EOF

if [ "$fail" -ne 0 ]; then
  echo "[check-migrations] 失败：迁移文件有问题（见上）。"
  exit 1
fi
echo "[check-migrations] 通过：$(printf '%s\n' "$names" | grep -c .) 个迁移文件，前缀纯数字、无新增重复、新文件没有带渠道后缀的公司名、新建的 public 表都开了 RLS 并写了授权。"
