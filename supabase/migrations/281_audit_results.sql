-- 281 — 结构性审计结果台账。
-- crawler/audit_runner.py 每天把 crawler/audit_contract.yaml 里每条检查项量一遍，一条一行写进来。
-- 一天一行（同日重跑覆盖）⇒ 直接就是趋势表；ok 也写 ⇒ 「在招总量」这类此前零历史的指标从此每天留一个点。
-- verdict='error' = 没查到（查询失败 / 空结果），此时 value 必为 NULL —— 绝不拿 0 充数，由约束钉死。

create table if not exists public.audit_results (
  id uuid primary key default gen_random_uuid(),
  check_id text not null,
  run_date date not null,
  layer text not null check (layer in ('pipeline', 'data', 'experience')),
  severity text not null check (severity in ('info', 'warn', 'critical')),
  value double precision,
  normal text not null,
  verdict text not null check (verdict in ('ok', 'breach', 'error')),
  calibrated boolean not null default true,
  measured_at timestamptz not null,
  error_message text,
  duration_ms integer,
  created_at timestamptz not null default now(),
  constraint audit_results_check_day_key unique (check_id, run_date),
  constraint audit_results_error_has_no_value check ((verdict = 'error') = (value is null))
);

-- unique(check_id, run_date) 已覆盖「某条检查的历史」；这条服务「某天的全部检查」（晨报取数）。
create index if not exists idx_audit_results_run_date
  on public.audit_results (run_date desc, verdict);

alter table public.audit_results enable row level security;
revoke all on table public.audit_results from public, anon, authenticated;
grant select, insert, update on table public.audit_results to service_role;
