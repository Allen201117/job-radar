-- ============================================================
-- 校招洞察 P2 种子：10 家头部往年招聘周期（据往年规律，官方招聘域名锚定）
-- 均 verify_status='verified'、绑 2027届、valid_until=2027-06-30（下季前失效）。
-- 重复执行注意：本文件为追加插入，仅在全新库或先删同 grad_class 行后重跑。
-- ============================================================

create or replace function _seed_cycle(
  p_company text, p_season text, p_batch text, p_event text,
  p_value_text text, p_month_start smallint, p_month_end smallint,
  p_evidence_url text
) returns void language plpgsql as $$
declare v_company_id uuid;
begin
  select id into v_company_id from company_profiles where company = p_company;
  if v_company_id is null then
    raise notice '跳过（company_profiles 无此公司）: %', p_company;
    return;
  end if;
  insert into recruitment_cycle_observations (
    company_id, grad_class, season, batch, event, time_expr_type,
    value_text, month_start, month_end, confidence, evidence_url,
    source_kind, verify_status, valid_until, created_by
  ) values (
    v_company_id, '2027届', p_season, p_batch, p_event, '历史规律',
    p_value_text, p_month_start, p_month_end, 'high', p_evidence_url,
    'official_site', 'verified', date '2027-06-30', 'seed'
  );
end;
$$;

-- 字节：秋招提前批约7月 / 正式批8-9月 / 春招3-4月
select _seed_cycle('字节跳动','秋招','提前批','开放','约7月',7::smallint,7::smallint,'https://jobs.bytedance.com/campus');
select _seed_cycle('字节跳动','秋招','正式批','开放','8-9月',8::smallint,9::smallint,'https://jobs.bytedance.com/campus');
select _seed_cycle('字节跳动','春招','正式批','开放','3-4月',3::smallint,4::smallint,'https://jobs.bytedance.com/campus');
-- 腾讯：秋招约8-10月（设提前批）
select _seed_cycle('腾讯','秋招','提前批','开放','靠前（约7月）',7::smallint,7::smallint,'https://join.qq.com/');
select _seed_cycle('腾讯','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://join.qq.com/');
-- 阿里：秋招8-10月 / 春招2-4月
select _seed_cycle('阿里巴巴','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://talent.alibaba.com/');
select _seed_cycle('阿里巴巴','春招','正式批','开放','2-4月',2::smallint,4::smallint,'https://talent.alibaba.com/');
-- 美团：秋招8-10月（设提前批）
select _seed_cycle('美团','秋招','提前批','开放','靠前',7::smallint,7::smallint,'https://zhaopin.meituan.com/');
select _seed_cycle('美团','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://zhaopin.meituan.com/');
-- 拼多多：秋招8-10月
select _seed_cycle('拼多多','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://careers.pinduoduo.com/');
-- 京东：秋招8-10月 / 春招补录
select _seed_cycle('京东','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://zhaopin.jd.com/');
select _seed_cycle('京东','春招','补录','开放','3-4月',3::smallint,4::smallint,'https://zhaopin.jd.com/');
-- 百度：秋招8-10月 / 春招2-4月
select _seed_cycle('百度','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://talent.baidu.com/');
select _seed_cycle('百度','春招','正式批','开放','2-4月',2::smallint,4::smallint,'https://talent.baidu.com/');
-- 快手：秋招8-10月
select _seed_cycle('快手','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://zhaopin.kuaishou.cn/');
-- 小红书：秋招8-10月
select _seed_cycle('小红书','秋招','正式批','开放','8-10月',8::smallint,10::smallint,'https://job.xiaohongshu.com/');
-- 华为：秋招8-11月（设实习转正）
select _seed_cycle('华为','秋招','正式批','开放','8-11月',8::smallint,11::smallint,'https://career.huawei.com/');
select _seed_cycle('华为','秋招','实习转正','开放','贯穿秋招',8::smallint,11::smallint,'https://career.huawei.com/');

drop function _seed_cycle(text, text, text, text, text, smallint, smallint, text);
