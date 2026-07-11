#!/usr/bin/env bash
# Source this file inside a GitHub Actions run step before invoking psql/pg_dump.
# It never prints the URL or certificate; the transformed URL carries
# verify-full, sslrootcert and (for the current IP endpoint) hostaddr.

if [ -z "${JOBS_DATABASE_URL:-}" ] || [ -z "${JOBS_DATABASE_SSL_CA:-}" ]; then
  echo "::error::JOBS_DATABASE_URL / JOBS_DATABASE_SSL_CA 未配置，拒绝非严格 TLS 连接。"
  return 1 2>/dev/null || exit 1
fi

_jobs_database_strict_url="$(node scripts/build-jobs-db-libpq-url.cjs)" || {
  echo "::error::jobs 数据库严格 TLS 配置失败。"
  return 1 2>/dev/null || exit 1
}
export JOBS_DATABASE_URL="$_jobs_database_strict_url"
unset _jobs_database_strict_url
