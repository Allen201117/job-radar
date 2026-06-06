-- ============================================================
-- 025 — listing 维度增强：未上市独角兽「股权含金量」标记 + 新增独角兽种子
-- ============================================================
-- 需求（承接 023/024）：上市维度不止给「是否上市」，还要给行业通行的投递视角——
--   已上市看行情判断股权值钱；未上市但是独角兽（字节/DeepSeek 等）股权激励同样很值钱。
-- 实现：payload 增加布尔 unicorn；前端 EquityAngle 由 status + unicorn 确定性生成「投递视角」文案
--   （非投资建议、不落库易变行情）。本文件：① 给已有未上市高价值公司打 unicorn 标；② 补几家独角兽种子。
-- ⚠️ 同 014/024：待人工核实草稿，valid_until 设 2026 末，到期需复核（IPO 状态易变）。
-- ============================================================

-- ① 已有 private 种子打 unicorn 标（估值高、市场看好、股权激励含金量高的未上市公司）
update insight_items i
set payload = coalesce(i.payload, '{}'::jsonb) || '{"unicorn": true}'::jsonb,
    updated_at = now()
from company_profiles c
where i.company_id = c.id
  and i.dimension = 'listing'
  and i.payload->>'status' = 'private'
  and c.company in ('字节跳动', '小红书', '华为');

-- ② 新增独角兽种子（未上市，股权激励含金量高）
create or replace function _seed_listing2(
  p_company text, p_aliases text[], p_status text, p_unicorn boolean,
  p_content text, p_valid_until date, p_src_url text, p_src_publisher text
) returns void language plpgsql as $$
declare
  v_company_id uuid; v_item_id uuid; v_src_id uuid;
begin
  insert into company_profiles (company, display_name, aliases, summary, last_verified_at)
  values (p_company, p_company, coalesce(p_aliases, '{}'), null, now())
  on conflict (company) do update set
    aliases = case when coalesce(array_length(excluded.aliases, 1), 0) > 0
      then excluded.aliases else company_profiles.aliases end,
    last_verified_at = now(), updated_at = now()
  returning id into v_company_id;

  -- 已有同公司 listing 条目则跳过（迁移幂等）
  if exists (select 1 from insight_items where company_id = v_company_id and dimension = 'listing') then
    return;
  end if;

  insert into insight_items (
    company_id, dimension, grade, title, content, sample_size, payload,
    time_window, valid_until, last_verified_at, deidentified, status
  ) values (
    v_company_id, 'listing', 'fact', '未上市',
    p_content, null,
    jsonb_strip_nulls(jsonb_build_object('status', p_status, 'unicorn', p_unicorn)),
    '上市状态截至 2026 年', p_valid_until, now(), true, 'active'
  ) returning id into v_item_id;

  insert into insight_sources (url, publisher, source_kind, excerpt, deidentified, collected_at)
  values (p_src_url, p_src_publisher, 'official_site', '公司官网 / 公开披露检索入口', true, now())
  returning id into v_src_id;
  insert into insight_item_sources (item_id, source_id) values (v_item_id, v_src_id);
end;
$$;

select _seed_listing2('深度求索', array['DeepSeek','深度求索','幻方'], 'private', true,
  '据公开信息，截至 2026 年 DeepSeek（深度求索）为非上市公司，由量化机构孵化、估值受市场高度关注，属热门 AI 独角兽；尚无官方上市时间表。仅供参考。',
  date '2026-12-31', 'https://www.deepseek.com', 'DeepSeek 官网');

select _seed_listing2('大疆', array['DJI','大疆创新','SZ DJI'], 'private', true,
  '据公开信息，截至 2026 年大疆创新（DJI）为非上市公司，在消费无人机等领域市占率领先，属知名独角兽；尚无官方上市时间表。仅供参考。',
  date '2026-12-31', 'https://www.dji.com', '大疆官网');

select _seed_listing2('蚂蚁集团', array['蚂蚁','Ant Group','支付宝','Alipay'], 'private', true,
  '据公开信息，蚂蚁集团 2020 年 IPO 暂缓后截至 2026 年仍未公开上市，体量与估值居前，属大型未上市金融科技公司；后续上市安排以官方披露为准。仅供参考。',
  date '2026-12-31', 'https://www.antgroup.com', '蚂蚁集团官网');

drop function _seed_listing2(text, text[], text, boolean, text, date, text, text);
