-- ============================================================
-- 模块 B 职业洞察 — 四维种子数据（草稿）
-- ============================================================
-- ⚠️ 重要：本文件为「待人工核实的策展草稿」。
--   * timing 维度（grade=fact）锚定各公司官方招聘域名，可信度较高，但具体
--     窗口日期与 URL 深链仍需上线前核对官方公告。
--   * compensation_intensity / path / culture 维度（grade=experience）的
--     sample_size 与社区聚合来源 URL 为「示意占位」，必须由人工用真实、去标识化的
--     公开聚合来源替换并核验后才可对外当作可信内容（PRD §7.2 / §8.2）。
--   * 全部 content 已按「聚合 + 归因」口径书写，不含产品断言（PRD §14）。
--   * 所有条目 deidentified=true、status=active；rumor 级一律不入种子。
-- 重复执行安全：company 唯一冲突走 upsert；条目为追加（重复跑会重复插入条目，
--   故仅在全新库或先 truncate insight_* 后执行）。
-- ============================================================

create or replace function _seed_insight(
  p_company text,
  p_aliases text[],
  p_summary text,
  p_dimension text,
  p_grade text,
  p_title text,
  p_content text,
  p_sample integer,
  p_time_window text,
  p_valid_until date,
  p_payload jsonb,
  p_sources jsonb
) returns void language plpgsql as $$
declare
  v_company_id uuid;
  v_item_id uuid;
  v_src jsonb;
  v_src_id uuid;
begin
  insert into company_profiles (company, display_name, aliases, summary, last_verified_at)
  values (p_company, p_company, coalesce(p_aliases, '{}'), p_summary, now())
  on conflict (company) do update set
    -- 同一公司多次调用（多维度）时，后续 null/空 aliases 不得覆盖已有别名
    aliases = case
      when coalesce(array_length(excluded.aliases, 1), 0) > 0 then excluded.aliases
      else company_profiles.aliases
    end,
    summary = coalesce(company_profiles.summary, excluded.summary),
    last_verified_at = now(),
    updated_at = now()
  returning id into v_company_id;

  insert into insight_items (
    company_id, dimension, grade, title, content, sample_size, payload,
    time_window, valid_until, last_verified_at, deidentified, status
  ) values (
    v_company_id, p_dimension, p_grade, p_title, p_content, p_sample,
    coalesce(p_payload, '{}'::jsonb), p_time_window, p_valid_until, now(), true, 'active'
  ) returning id into v_item_id;

  for v_src in select * from jsonb_array_elements(coalesce(p_sources, '[]'::jsonb))
  loop
    insert into insight_sources (url, publisher, source_kind, excerpt, deidentified, collected_at)
    values (
      v_src->>'url', v_src->>'publisher', v_src->>'kind', v_src->>'excerpt', true, now()
    ) returning id into v_src_id;
    insert into insight_item_sources (item_id, source_id) values (v_item_id, v_src_id);
  end loop;
end;
$$;

-- ============================================================
-- timing 时机类（grade=fact，官方源锚定，周期性窗口无 valid_until）
-- ============================================================

select _seed_insight('字节跳动', array['字节','ByteDance','抖音','Douyin'],
  '互联网大厂，校招规模大、节奏靠前；薪资在行业中相对偏高（均为公开聚合观察）。',
  'timing','fact','校招节奏：提前批靠前',
  '据官方招聘渠道与公开校招公告，字节校招通常秋招提前批约 7 月启动、正式批集中在 8–9 月，春招 3–4 月有补录。具体批次以官网当年公告为准。',
  null,'每年 7–9 月（秋招）/ 3–4 月（春招）',null,
  '{"phase":["秋招提前批 7月","秋招正式批 8-9月","春招 3-4月"]}'::jsonb,
  '[{"url":"https://jobs.bytedance.com/campus","publisher":"字节跳动官方招聘","kind":"official_site","excerpt":"官方校园招聘入口"}]'::jsonb);

select _seed_insight('腾讯', array['Tencent','腾讯科技'],
  '互联网大厂，校招体系成熟（如青云 / 技术大咖等项目），节奏规律。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，腾讯校招以秋招为主（约 8–10 月），并设提前批；春招体量相对较小。以官网当年公告为准。',
  null,'每年 8–10 月（秋招）',null,
  '{"phase":["秋招 8-10月","提前批靠前"]}'::jsonb,
  '[{"url":"https://join.qq.com/","publisher":"腾讯招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('阿里巴巴', array['Alibaba','阿里','淘宝','蚂蚁'],
  '互联网大厂，校招项目体系化（如星青年）。',
  'timing','fact','校招节奏：秋招 + 春招',
  '据官方招聘渠道与公开校招公告，阿里校招秋招约 8–10 月、春招 2–4 月均有招募。以官网当年公告为准。',
  null,'每年 8–10 月（秋招）/ 2–4 月（春招）',null,'{}'::jsonb,
  '[{"url":"https://talent.alibaba.com/","publisher":"阿里巴巴招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('美团', array['Meituan'],
  '互联网大厂，业务覆盖本地生活，校招社招体量大。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，美团校招以秋招为主（约 8–10 月），设提前批；以官网当年公告为准。',
  null,'每年 8–10 月（秋招）',null,'{}'::jsonb,
  '[{"url":"https://zhaopin.meituan.com/","publisher":"美团招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('拼多多', array['Pinduoduo','PDD'],
  '互联网大厂，业务强度高（公开讨论中常见）。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，拼多多校招以秋招为主（约 8–10 月）；以官网当年公告为准。',
  null,'每年 8–10 月（秋招）',null,'{}'::jsonb,
  '[{"url":"https://careers.pinduoduo.com/","publisher":"拼多多招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('京东', array['JD','JD.com','京东集团'],
  '互联网大厂，零售 + 物流，入职门槛在头部互联网中相对友好（公开讨论观察）。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，京东校招以秋招为主（约 8–10 月）、春招有补录；以官网当年公告为准。',
  null,'每年 8–10 月（秋招）',null,'{}'::jsonb,
  '[{"url":"https://zhaopin.jd.com/","publisher":"京东招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('百度', array['Baidu'],
  '互联网大厂，AI / 搜索 / 自动驾驶等方向。',
  'timing','fact','校招节奏：秋招 + 春招',
  '据官方招聘渠道与公开校招公告，百度校招秋招约 8–10 月、春招 2–4 月均有招募；以官网当年公告为准。',
  null,'每年 8–10 月（秋招）/ 2–4 月（春招）',null,'{}'::jsonb,
  '[{"url":"https://talent.baidu.com/","publisher":"百度招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('快手', array['Kuaishou'],
  '互联网大厂，短视频，与字节 / 小红书在人才上互相青睐（公开讨论观察）。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，快手校招以秋招为主（约 8–10 月）；以官网当年公告为准。',
  null,'每年 8–10 月（秋招）',null,'{}'::jsonb,
  '[{"url":"https://zhaopin.kuaishou.cn/","publisher":"快手招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('小红书', array['RED','Xiaohongshu','xhs'],
  '互联网公司，社区 + 电商，近年扩招（公开讨论观察）。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，小红书校招以秋招为主（约 8–10 月）；以官网当年公告为准。',
  null,'每年 8–10 月（秋招）',null,'{}'::jsonb,
  '[{"url":"https://job.xiaohongshu.com/","publisher":"小红书招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('华为', array['Huawei'],
  '硬科技 / 通信 / 终端，校招规模大。',
  'timing','fact','校招节奏：秋招为主',
  '据官方招聘渠道与公开校招公告，华为校招以秋招为主（约 8–11 月），并设实习转正路径；以官网当年公告为准。',
  null,'每年 8–11 月（秋招）',null,'{}'::jsonb,
  '[{"url":"https://career.huawei.com/","publisher":"华为招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

select _seed_insight('微软中国', array['Microsoft','微软','Microsoft China'],
  '外企在华研发，受全球财年节奏影响（公开讨论观察）。',
  'timing','fact','财年节奏：年中 HC 偏紧',
  '据公开信息，微软财年通常 7 月初开始（自然年 7 月）。公开求职讨论中常提到财年切换前后（约 5–7 月）HC 相对偏紧，官网即便挂岗推进也可能较慢——此为节奏性观察，具体以岗位与团队当下 HC 为准。',
  null,'每年约 5–7 月（财年切换前后 HC 偏紧）',null,
  '{"fiscal_year_start":"7月","note":"财年切换前后 HC 偏紧"}'::jsonb,
  '[{"url":"https://careers.microsoft.com/","publisher":"微软招聘官方","kind":"official_site","excerpt":"官方招聘入口"},{"url":"https://www.microsoft.com/investor","publisher":"微软投资者关系（财年）","kind":"official_filing","excerpt":"财年信息公开披露"}]'::jsonb);

select _seed_insight('苹果中国', array['Apple','苹果','Apple China'],
  '外企在华，岗位多挂全球官网 China 区。',
  'timing','fact','招聘节奏：全年滚动',
  '据官方招聘渠道，苹果中国岗位多为全年滚动放出（rolling），无固定校招大批次；以官网当前在招岗位为准。',
  null,'全年滚动（无固定大批次）',null,'{}'::jsonb,
  '[{"url":"https://jobs.apple.com/zh-cn","publisher":"Apple 招聘官方","kind":"official_site","excerpt":"官方招聘入口"}]'::jsonb);

-- ============================================================
-- compensation_intensity 性价比类（grade=experience，社区聚合 + 归因；sample_size / URL 为待核实示意）
-- valid_until 设年底，强制周期性复核
-- ============================================================

select _seed_insight('字节跳动', null, null,
  'compensation_intensity','experience','薪资与强度：薪资偏高',
  '据脉脉、牛客等公开讨论聚合（去标识化，约 20 条样本，待核实），字节在互联网公司中给薪相对偏高，对应工作强度也偏大；不同 BU 差异明显，仅供参考。',
  20,'2025–2026 观察',date '2026-12-31',
  '{"pay":"相对偏高","intensity":"偏大","variance":"BU 差异大"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开薪资 / 强度讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开 offer / 强度讨论聚合"}]'::jsonb);

select _seed_insight('拼多多', null, null,
  'compensation_intensity','experience','薪资与强度：薪资高、强度大',
  '据脉脉、牛客等公开讨论聚合（去标识化，约 18 条样本，待核实），拼多多给薪在行业中偏高，但工作强度与时长在公开讨论中常被认为偏大；请结合自身承受度判断，仅供参考。',
  18,'2025–2026 观察',date '2026-12-31',
  '{"pay":"偏高","intensity":"偏大"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开薪资 / 强度讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"}]'::jsonb);

select _seed_insight('京东', null, null,
  'compensation_intensity','experience','薪资与门槛：门槛相对友好',
  '据脉脉、牛客等公开讨论聚合（去标识化，约 12 条样本，待核实），京东部分岗位入职门槛在头部互联网中相对友好，薪资中等；岗位间差异较大，仅供参考。',
  12,'2025–2026 观察',date '2026-12-31',
  '{"bar":"相对友好","pay":"中等"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"}]'::jsonb);

select _seed_insight('腾讯', null, null,
  'compensation_intensity','experience','薪资与强度：薪资稳健、强度中等',
  '据脉脉、牛客等公开讨论聚合（去标识化，约 14 条样本，待核实），腾讯薪资稳健、福利较好，整体强度在大厂中相对中等；不同事业群差异明显，仅供参考。',
  14,'2025–2026 观察',date '2026-12-31',
  '{"pay":"稳健","welfare":"较好","intensity":"中等"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"}]'::jsonb);

select _seed_insight('阿里巴巴', null, null,
  'compensation_intensity','experience','薪资与强度：薪资有竞争力',
  '据脉脉、牛客等公开讨论聚合（去标识化，约 13 条样本，待核实），阿里薪资具竞争力、职级体系清晰，强度因业务而异；仅供参考。',
  13,'2025–2026 观察',date '2026-12-31',
  '{"pay":"有竞争力","intensity":"因业务而异"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"}]'::jsonb);

-- ============================================================
-- path 路径类（grade=experience，公司→公司，社区聚合 + 归因；待核实）
-- ============================================================

select _seed_insight('字节跳动', null, null,
  'path','experience','常见进入路径：快手 / 小红书背景受青睐',
  '据公开求职讨论聚合（去标识化，约 10 条样本，待核实），进入字节的常见路径之一是先在快手 / 小红书等内容社区公司积累履历，三家在人才上互相青睐对方背景；此为路径性观察，非保证，仅供参考。',
  10,'2025–2026 观察',date '2026-12-31',
  '{"from":["快手","小红书"],"to":"字节跳动","direction":"互相青睐"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开跳槽路径讨论聚合"},{"url":"https://www.zhihu.com/","publisher":"知乎（聚合·去标识）","kind":"public_aggregate","excerpt":"公开职业路径讨论聚合"}]'::jsonb);

select _seed_insight('小红书', null, null,
  'path','experience','常见进入路径：内容 / 社区背景互通',
  '据公开求职讨论聚合（去标识化，约 8 条样本，待核实），小红书与字节 / 快手在内容、社区、增长方向人才互通较多；仅供参考。',
  8,'2025–2026 观察',date '2026-12-31',
  '{"from":["字节跳动","快手"],"to":"小红书","direction":"内容/社区互通"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开跳槽路径讨论聚合"},{"url":"https://www.zhihu.com/","publisher":"知乎（聚合·去标识）","kind":"public_aggregate","excerpt":"公开职业路径讨论聚合"}]'::jsonb);

-- ============================================================
-- culture 文化 / 避坑类（grade=experience，做浅、重免责；待核实）
-- ============================================================

select _seed_insight('拼多多', null, null,
  'culture','experience','工作节奏：强度与时长偏高（避坑提示）',
  '据脉脉等公开讨论聚合（去标识化，约 15 条样本，待核实），公开讨论中拼多多工作时长与强度常被认为偏高。此为去标识化的群体性反馈、非对公司的事实定性，个体体验差异很大，请结合面试沟通与自身情况判断，仅供参考。',
  15,'2025–2026 观察',date '2026-12-31',
  '{"theme":"强度/时长","tone":"避坑提示"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开工作强度讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"}]'::jsonb);

select _seed_insight('字节跳动', null, null,
  'culture','experience','工作节奏：快节奏 / 高目标（避坑提示）',
  '据脉脉等公开讨论聚合（去标识化，约 12 条样本，待核实），公开讨论中常提到字节节奏快、目标导向强、OKR 压力较大。此为群体性反馈、非事实定性，不同 BU / 团队差异明显，请结合面试沟通判断，仅供参考。',
  12,'2025–2026 观察',date '2026-12-31',
  '{"theme":"快节奏/高目标","tone":"避坑提示"}'::jsonb,
  '[{"url":"https://maimai.cn/","publisher":"脉脉（聚合·去标识）","kind":"public_aggregate","excerpt":"公开企业文化讨论聚合"},{"url":"https://www.nowcoder.com/","publisher":"牛客（聚合·去标识）","kind":"public_aggregate","excerpt":"公开讨论聚合"}]'::jsonb);

-- 清理临时函数
drop function _seed_insight(
  text, text[], text, text, text, text, text, integer, text, date, jsonb, jsonb
);
