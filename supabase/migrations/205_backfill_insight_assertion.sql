-- 职业洞察 v3 P0-5：按来源层回填断言强度，并治理把搜索网页包装成「事实」的存量。
-- 映射规则（见 docs/superpowers/specs/2026-09-03-insights-v3-scope-and-model.md §2.1-2.2）：
--   origin in ('official', 'official_filing', 'wikidata') -> assertion='fact'
--   origin = 'derived' -> assertion='signal'
--   origin = 'public_web' -> assertion='claim'；若 grade='fact'，同步降为 grade='experience'
--   origin = 'manual' -> grade='fact' 时 assertion='fact'，其余 grade（含 experience）为 assertion='claim'
-- public_web 不得保留 fact grade：它来自公开讨论而非官方出处；降级后沿用 experience
-- 展示门的来源域名/样本量要求，避免直接作为事实放行。

begin;

-- insight_items 目前约 6 千行；仍显式限制语句时间，避免迁移环境异常时长期占用连接。
set local statement_timeout = '30s';

update insight_items
set
  assertion = case
    when origin in ('official', 'official_filing', 'wikidata') then 'fact'
    when origin = 'derived' then 'signal'
    when origin = 'public_web' then 'claim'
    when origin = 'manual' and grade = 'fact' then 'fact'
    when origin = 'manual' then 'claim'
  end,
  grade = case
    when origin = 'public_web' and grade = 'fact' then 'experience'
    else grade
  end
where origin in ('official', 'official_filing', 'wikidata', 'derived', 'public_web', 'manual')
  and (
    assertion is distinct from case
      when origin in ('official', 'official_filing', 'wikidata') then 'fact'
      when origin = 'derived' then 'signal'
      when origin = 'public_web' then 'claim'
      when origin = 'manual' and grade = 'fact' then 'fact'
      when origin = 'manual' then 'claim'
    end
    or (origin = 'public_web' and grade = 'fact')
  );

commit;

-- 上线后校验：invalid_fact_assertion 必须为 0；即 assertion='fact' 的行只能来自官方、年报、
-- Wikidata 或人工事实录入，绝不包含 public_web / derived。
-- select count(*) as invalid_fact_assertion
-- from insight_items
-- where assertion = 'fact'
--   and origin not in ('official', 'official_filing', 'wikidata', 'manual');

