#!/usr/bin/env bash
# 自动应用 supabase/migrations 下的新迁移到生产库。由 GitHub Actions 在 push main 时跑，
# 用户不再需要手动进 Supabase SQL Editor 跑迁移。
#
# 一次性设置：在 GitHub repo → Settings → Secrets → Actions 添加 SUPABASE_DB_URL
#   值 = Supabase → Settings → Database → Connection string（直连/会话模式，端口 5432，含密码）。
#   之后每次 push 含新迁移即自动应用，零手动 SQL。
#
# 机制：schema_migrations 表记录已应用版本。
#   - 前缀 <= BASELINE 的历史迁移：仅登记不重跑（引入自动迁移前已手动应用，且部分非幂等）。
#   - 前缀 >  BASELINE 的新迁移：自动应用一次并登记。
set -euo pipefail

: "${SUPABASE_DB_URL:?need SUPABASE_DB_URL}"
DB="$SUPABASE_DB_URL"
BASELINE="022"           # 截至此前缀已手动迁移到位；只登记
MIG_DIR="supabase/migrations"

psql "$DB" -v ON_ERROR_STOP=1 -c \
  "create table if not exists schema_migrations(version text primary key, applied_at timestamptz default now());"

for f in $(ls "$MIG_DIR"/*.sql | sort); do
  v="$(basename "$f")"
  prefix="${v%%_*}"
  applied="$(psql "$DB" -tAc "select 1 from schema_migrations where version='$v'")"
  if [ "$applied" = "1" ]; then
    echo "skip(tracked)     $v"
    continue
  fi
  if [[ "$prefix" < "$BASELINE" || "$prefix" == "$BASELINE" ]]; then
    echo "baseline(register) $v"
    psql "$DB" -v ON_ERROR_STOP=1 -c \
      "insert into schema_migrations(version) values ('$v') on conflict do nothing;"
    continue
  fi
  echo "apply             $v"
  psql "$DB" -v ON_ERROR_STOP=1 -1 -f "$f"
  psql "$DB" -v ON_ERROR_STOP=1 -c \
    "insert into schema_migrations(version) values ('$v') on conflict do nothing;"
done
echo "[db-migrate] done."
