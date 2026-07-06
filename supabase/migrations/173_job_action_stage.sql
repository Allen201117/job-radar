-- 173 — 投递阶段跟踪（求职漏斗中段最小版）
-- 为何：job_actions 只有投前四态（viewed/saved/ignored/applied），用户投递后的笔试/面试/offer
-- 进展无处记录，投递量一上来就回流 Excel/Notion。本迁移只加最小字段，不做提醒/备注/多轮面试。
-- stage 仅对 action='applied' 的行有意义（API 层约束）；null = 未设置（等同「已投递」初始态）。
alter table job_actions
  add column if not exists stage text
    check (stage in ('applied', 'assessment', 'interview', 'offer', 'closed')),
  add column if not exists stage_updated_at timestamptz;

comment on column job_actions.stage is
  '投递进展阶段：applied已投递/assessment笔试测评/interview面试中/offer已拿offer/closed已结束；null=未设置';
