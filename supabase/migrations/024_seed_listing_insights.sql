-- ============================================================
-- 024 — listing 维度种子（上市状态 / 股票 / 即将上市），grade=fact
-- ============================================================
-- ⚠️ 待人工核实草稿（同 014 口径）。只录**稳定公开事实**：是否上市 + 交易所 + 代码 + 上市年份；
-- 易变的「近期行情」不落库为数字，改在 payload.quote_url 存公开行情页链接（前端「近期行情 →」）。
-- 来源用官方公告检索入口（港交所披露易 / SEC EDGAR / 公司官网），非整段原文，deidentified=true。
-- company 走 upsert（与 013/014 同表）；本文件由迁移器只跑一次，re-run 安全。
-- ============================================================

create or replace function _seed_listing(
  p_company text,
  p_aliases text[],
  p_status text,        -- listed / filed / pre_ipo / private
  p_exchange text,
  p_ticker text,
  p_quote_url text,
  p_content text,
  p_valid_until date,
  p_src_url text,
  p_src_publisher text,
  p_src_kind text
) returns void language plpgsql as $$
declare
  v_company_id uuid;
  v_item_id uuid;
  v_src_id uuid;
begin
  insert into company_profiles (company, display_name, aliases, summary, last_verified_at)
  values (p_company, p_company, coalesce(p_aliases, '{}'), null, now())
  on conflict (company) do update set
    aliases = case
      when coalesce(array_length(excluded.aliases, 1), 0) > 0 then excluded.aliases
      else company_profiles.aliases
    end,
    last_verified_at = now(),
    updated_at = now()
  returning id into v_company_id;

  insert into insight_items (
    company_id, dimension, grade, title, content, sample_size, payload,
    time_window, valid_until, last_verified_at, deidentified, status
  ) values (
    v_company_id, 'listing', 'fact',
    case p_status
      when 'listed' then '已上市 · ' || coalesce(p_exchange, '')
      when 'filed' then '已递交招股书'
      when 'pre_ipo' then '筹备上市'
      else '未上市'
    end,
    p_content, null,
    jsonb_strip_nulls(jsonb_build_object(
      'status', p_status, 'exchange', p_exchange, 'ticker', p_ticker, 'quote_url', p_quote_url
    )),
    '上市状态截至 2026 年', p_valid_until, now(), true, 'active'
  ) returning id into v_item_id;

  insert into insight_sources (url, publisher, source_kind, excerpt, deidentified, collected_at)
  values (p_src_url, p_src_publisher, p_src_kind, '上市公司公告 / 公开披露检索入口', true, now())
  returning id into v_src_id;
  insert into insight_item_sources (item_id, source_id) values (v_item_id, v_src_id);
end;
$$;

-- —— 已上市（content 不含实时报价，行情见 quote_url）——
select _seed_listing('腾讯', array['腾讯控股','Tencent'], 'listed', '港交所', '0700.HK',
  'https://xueqiu.com/S/00700',
  '据公开披露，腾讯控股于 2004 年在港交所主板上市（代码 0700.HK），属长期上市的大型科技股。近期行情见下方公开行情页，本产品不提供实时报价，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('阿里巴巴', array['阿里','Alibaba','淘宝','蚂蚁'], 'listed', '港交所 / 纽交所', '9988.HK',
  'https://xueqiu.com/S/09988',
  '据公开披露，阿里巴巴集团于 2014 年在纽交所上市（BABA）、2019 年在港交所二次上市（9988.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('京东', array['JD','京东集团'], 'listed', '港交所 / 纳斯达克', '9618.HK',
  'https://xueqiu.com/S/09618',
  '据公开披露，京东集团于纳斯达克上市（JD），并于 2020 年在港交所上市（9618.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('百度', array['Baidu'], 'listed', '港交所 / 纳斯达克', '9888.HK',
  'https://xueqiu.com/S/09888',
  '据公开披露，百度于纳斯达克上市（BIDU），并于 2021 年在港交所二次上市（9888.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('美团', array['Meituan','美团点评'], 'listed', '港交所', '3690.HK',
  'https://xueqiu.com/S/03690',
  '据公开披露，美团于 2018 年在港交所上市（3690.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('快手', array['Kuaishou'], 'listed', '港交所', '1024.HK',
  'https://xueqiu.com/S/01024',
  '据公开披露，快手于 2021 年在港交所上市（1024.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('网易', array['NetEase'], 'listed', '港交所 / 纳斯达克', '9999.HK',
  'https://xueqiu.com/S/09999',
  '据公开披露，网易于纳斯达克上市（NTES），并于 2020 年在港交所二次上市（9999.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('拼多多', array['PDD','Pinduoduo'], 'listed', '纳斯达克', 'PDD',
  'https://xueqiu.com/S/PDD',
  '据公开披露，拼多多于 2018 年在纳斯达克上市（PDD）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany', '美国 SEC EDGAR', 'official_filing');

select _seed_listing('小米', array['Xiaomi','小米集团'], 'listed', '港交所', '1810.HK',
  'https://xueqiu.com/S/01810',
  '据公开披露，小米集团于 2018 年在港交所上市（1810.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('苹果中国', array['Apple','苹果'], 'listed', '纳斯达克', 'AAPL',
  'https://xueqiu.com/S/AAPL',
  '据公开披露，苹果公司（Apple Inc.）于纳斯达克上市（AAPL）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany', '美国 SEC EDGAR', 'official_filing');

select _seed_listing('微软中国', array['Microsoft','微软'], 'listed', '纳斯达克', 'MSFT',
  'https://xueqiu.com/S/MSFT',
  '据公开披露，微软公司（Microsoft）于纳斯达克上市（MSFT）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany', '美国 SEC EDGAR', 'official_filing');

select _seed_listing('蔚来', array['NIO'], 'listed', '纽交所 / 港交所', '9866.HK',
  'https://xueqiu.com/S/09866',
  '据公开披露，蔚来于 2018 年在纽交所上市（NIO），并于 2022 年在港交所等地二次上市（9866.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

select _seed_listing('小鹏汽车', array['小鹏','XPeng'], 'listed', '纽交所 / 港交所', '9868.HK',
  'https://xueqiu.com/S/09868',
  '据公开披露，小鹏汽车于 2020 年在纽交所上市（XPEV），并于 2021 年在港交所双重上市（9868.HK）。近期行情见下方公开行情页，仅供参考。',
  null, 'https://www.hkexnews.hk', '香港交易所披露易', 'official_filing');

-- —— 未上市（status=private；可能变化，设有效期 2026 末，到期需复核）——
select _seed_listing('华为', array['Huawei','华为技术'], 'private', null, null, null,
  '据公开信息，截至 2026 年华为为非上市公司，未在公开市场发行股票，亦无官方披露的上市时间表（员工持股为内部机制）。仅供参考。',
  date '2026-12-31', 'https://www.huawei.com', '华为官网', 'official_site');

select _seed_listing('字节跳动', array['字节','ByteDance','抖音','Douyin'], 'private', null, null, null,
  '据公开信息，截至 2026 年字节跳动尚未公开上市，市场虽有 IPO 讨论，但公司未公开确认上市时间表。仅供参考。',
  date '2026-12-31', 'https://www.bytedance.com', '字节跳动官网', 'official_site');

select _seed_listing('小红书', array['RED','Xiaohongshu','小红书科技'], 'private', null, null, null,
  '据公开信息，截至 2026 年小红书尚未公开上市，市场有上市传闻但公司未公开确认。仅供参考。',
  date '2026-12-31', 'https://www.xiaohongshu.com', '小红书官网', 'official_site');

drop function _seed_listing(
  text, text[], text, text, text, text, text, date, text, text, text
);
