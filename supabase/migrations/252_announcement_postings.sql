-- 252 — 公告制招聘：官方招聘公告抓取表 announcement_postings
--
-- 设计文档：docs/superpowers/specs/2026-09-15-announcement-recruitment-supply-design.md
--
-- 为什么独立于 apply_programs（迁移 226）：
--   apply_programs 是「纯手工、人工核实、永久有效」的小表（数十行），承载没有官方逐岗页、
--   也没有统一抓取渠道的边缘情况（中国银行公告、中通蓝天计划、人才库）。
--   本表相反：是**可自动扩量、带自动过期治理**的官方招聘公告（事业单位/体制内），量级数千。
--   两者质量模型/量级/查询形态都不同，独立建表可保住 apply_programs 的「人工核实」不变量完整。
--   /programs 读侧 union 两表，统一渲染为「招聘公告」卡。
--
-- ⚠️ 归属由构造保证：只从**官方政府域名白名单**抓取（见 crawler/announcements/portals.py），
--   source_url 的 host 必属该 portal 声明的官方域名，插入端硬校验 → 天然不会张冠李戴
--   （这正是企业爬取最头疼、本表免费解决的一点）。
--
-- ⚠️ 与 apply_programs 的 window_text（自由文本）不同，本表把报名截止日抽成结构化 date（deadline），
--   这是「自动过期」的技术落点。只有高置信抽取才写 date；抽不到存 deadline_text 原文 + 走 TTL 兜底。

create table if not exists announcement_postings (
  id uuid primary key default gen_random_uuid(),
  -- 官方源标识（白名单键），如 'gd_hrss'（广东人社厅）/ 'bj_rsj'（北京人社局）
  source_portal text not null,
  -- 公告详情页 URL（必须是官方 gov 域名，插入端按 portal 白名单校验 host）
  source_url text not null unique,
  title text not null,
  -- 省/市，如 '广东省' / '北京市'（后续可细化到地级市）
  region text,
  -- 粗分类：事业单位 / 军队文职 / 央国企 / 高校（可空）
  employer_type text,
  -- 应届 / 社会 / 两者皆可 / 未知 —— 校招/社招分面
  audience text not null default 'unknown'
    check (audience in ('fresh_grad', 'experienced', 'both', 'unknown')),
  -- 公告发布日期（列表页/URL 自带）
  published_at date,
  -- 报名截止日（高置信抽到才填；驱动自动过期）
  deadline date,
  -- 截止日原文兜底（抽不成结构化 date 时保留，避免造假精度）
  deadline_text text,
  -- active=可投 / expired=报名已截止（自动下架）/ dead=探活失败
  status text not null default 'active'
    check (status in ('active', 'expired', 'dead')),
  first_seen_at timestamptz not null default now(),
  -- 列表页最近一次还挂着它（列表缺席 ≠ 撤岗，不据此判死）
  last_seen_at timestamptz not null default now(),
  -- 最近一次探活时间
  last_checked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 读侧唯一查询形态：可投 = active，按发布日倒序，按地区/受众筛。
create index if not exists idx_announcement_visible
  on announcement_postings (published_at desc)
  where status = 'active';

create index if not exists idx_announcement_region
  on announcement_postings (region)
  where status = 'active';

alter table announcement_postings enable row level security;
revoke all on table announcement_postings from public, anon, authenticated;
grant all on table announcement_postings to service_role;
grant select on table announcement_postings to anon, authenticated;

-- 所有人可读「可投」的行：active 且未过报名截止日（deadline 为空 = 未知截止日，仍展示，靠 TTL 治理）。
-- ⚠️ 这道 RLS 门是 deadline 过期的兜底：即便 expire 任务滞后，用户也看不到已过报名日的公告。
create policy "Anyone can read active announcement_postings"
  on announcement_postings for select
  to anon, authenticated
  using (status = 'active' and (deadline is null or deadline >= current_date));
