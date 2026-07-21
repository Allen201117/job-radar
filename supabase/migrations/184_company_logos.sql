-- ============================================================
-- 184 — 企业 logo 缓存表 company_logos
-- 小图标级真 logo（favicon）以 base64 data URI 存 logo_data（国内可访问、无外链、无 CSP 问题）；
-- 抓不到的公司 status='not_found'，前端用首字母色块兜底 → 覆盖率 100%、不参差。
-- 抓取：crawler/fetch_company_logos.py（海外 CI，DuckDuckGo 为「有没有」权威 + icon.horse 高清升级）。
-- 读取：app/api/company-logos，按 company_key 批量查（与前端 lower(trim(company)) 同口径）。
-- ============================================================

create table company_logos (
  id uuid primary key default gen_random_uuid(),
  company text not null,                                   -- 原始公司名
  company_key text generated always as (lower(trim(company))) stored,  -- 归一匹配 key
  logo_data text,                                          -- data URI；status='not_found' 时 null
  domain text,                                             -- 推导出的品牌域名（可空）
  width int,                                               -- 像素宽（未知填 null），前端判断清晰度用
  source text,                                             -- 'duckduckgo' | 'iconhorse' | null
  status text not null default 'found' check (status in ('found', 'not_found')),
  fetched_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

-- 归一 key 唯一：抓取脚本 upsert on conflict、前端按 lower(trim(company)) 匹配同口径。
create unique index idx_company_logos_company_key on company_logos(company_key);

-- ============================================================
-- RLS — 所有登录用户可读，admin/service_role 写（service_role 绕 RLS 供抓取脚本写）。
-- 照抄 company_profiles（013）口径。
-- ============================================================
alter table company_logos enable row level security;

create policy "Authenticated users can read company_logos"
  on company_logos for select
  using (auth.role() = 'authenticated');

create policy "Admins can write company_logos"
  on company_logos for all
  using (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  )
  with check (
    exists (select 1 from profiles where id = auth.uid() and role = 'admin')
  );
