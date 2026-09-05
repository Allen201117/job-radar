-- 226 — 项目制投递入口（apply_programs）
--
-- 为什么要有这张表：有一类公司**客观上不存在「一岗一页」**，我们再怎么改抓取也拿不到 jd_url：
--   · 中通快递校招 = 「蓝天计划」项目制投递（2026-09-04 浏览器实测：整页只有项目介绍 +
--     宣讲会日程 + 一个「投递简历」按钮，**没有任何岗位列表**，学生投的是项目不是岗位）
--   · 国有大行 = 公告制（工行实测：首页只有「XX分行2026年社会招聘公告」，
--     零鉴权接口能拿到的是**岗位类型**「星辰管培生」而不是岗位记录）
--
-- 此前这类公司在产品里**完全不存在**：既进不了 jobs（过不了 jd_url 红线，也不该假装是岗位），
-- 又没有别的地方承载 → 用户搜「中通 校招」一无所获，而对方其实正在招。
-- 创始人 2026-09-04 拍板：「这种项目制投递的公司，单独做一个入口，把这部分也补充进来。」
--
-- ⚠️ 设计红线：**它不是 jobs 的旁路，绝不能反过来污染岗位流**。
--   · 独立表、独立路由 /programs、UI 上必须显式标注「项目制投递 / 公告制」，
--     不允许把这些条目渲染成岗位卡片 —— 那等于用「看起来有岗」骗用户点击。
--   · entry_url 存的是**官方投递/公告入口页**，语义上就不是逐岗详情页，
--     所以不套 jobs 的 jd_url 质量门；但**必须人工核实过能打开**，用 verified_at 记录核实时间。
--   · 只有 enabled=true 且核实过的才对外可见。
--
-- 为什么用独立表而不是给 jobs 加个 flag：jobs 的每一列（canonical_jd_url 唯一索引、
-- 招聘类型物化触发器、探活/撤岗链路）都建立在「一行 = 一个可投递岗位」这个前提上，
-- 塞进去会让所有那些机制对这类行失去意义，还会污染「岗位库」计数口径（指标诚实）。

create table if not exists apply_programs (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  -- 项目/公告名，如「蓝天计划（2027届校园招聘）」
  program_name text not null,
  -- campus_program=项目制校招；announcement=公告制（多见于国有大行）；talent_pool=人才库/长期简历池
  program_type text not null check (program_type in ('campus_program', 'announcement', 'talent_pool')),
  -- 官方投递/公告入口页（必须人工核实能打开）
  entry_url text not null unique,
  -- 一句话说明这是什么、投的是什么（给用户看，别写黑话）
  description text,
  -- 对方页面上自己写的时间窗（原文照抄，如「毕业时间 2026/10/01-2027/09/30」）；
  -- 刻意存文本不存 date：各家写法不一，硬解析会造出假精度。
  window_text text,
  industry text,
  -- 最近一次人工核实 entry_url 能打开的时间。为空 = 未核实，不对外展示。
  verified_at timestamptz,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 读侧唯一的查询形态：按类型取已启用且核实过的，按公司排。
create index if not exists idx_apply_programs_visible
  on apply_programs (program_type, company)
  where enabled and verified_at is not null;

alter table apply_programs enable row level security;
revoke all on table apply_programs from public, anon, authenticated;
grant all on table apply_programs to service_role;
grant select on table apply_programs to anon, authenticated;

-- 所有人可读，但只读「已启用 + 已核实」的行；未核实的草稿只有 service_role/admin 看得到。
create policy "Anyone can read verified apply_programs"
  on apply_programs for select
  to anon, authenticated
  using (enabled and verified_at is not null);

-- ── 种子：只放 2026-09-04 **本人实测过 entry_url 返回 200 且页面确认内容**的两条 ──
-- 其余候选（工行/建行/农行/交行/浦发…）当天本机对这些域名持续 ConnectError，
-- **没核实就不入库** —— 拿没核实的链接去种一个面向用户的入口，正是本项目的红线。
-- 补齐是独立任务（见记忆 job-radar-a-class-gap-sweep 的交接任务卡）。

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '中通快递', '蓝天计划（校园招聘）', 'campus_program', 'https://hr.zto.com/campus',
       '中通的校招走「蓝天计划」项目制投递：官网不按岗位一个个挂，而是投递到项目、再由对方分配方向。'
       '页面同时挂着各高校宣讲会日程。',
       '毕业时间 2026/10/01-2027/09/30', '物流/供应链', now()
where not exists (select 1 from apply_programs where entry_url = 'https://hr.zto.com/campus');

insert into apply_programs (company, program_name, program_type, entry_url, description, window_text, industry, verified_at)
select '中国银行', '招聘公告', 'announcement', 'https://www.bankofchina.com/aboutboc/bi4/',
       '中国银行按「公告」发布招聘：每条公告对应一次批量招聘（分行/条线），'
       '需要在公告里看具体岗位与报名方式，官网没有逐个岗位的详情页。',
       null, '金融', now()
where not exists (select 1 from apply_programs where entry_url = 'https://www.bankofchina.com/aboutboc/bi4/');
