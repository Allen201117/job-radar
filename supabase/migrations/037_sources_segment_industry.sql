-- 037 — sources 加 segment(模块) + industry(行业) 字段 + 粗粒度回填
-- segment: foreign(外企) / soe(国企央企) / private(中国私企)。用于按模块/行业看「各公司爬取通道打通进度」。
-- industry: 行业（如 医药/半导体/金融…），后续每加一源逐个补；存量先留 NULL。
-- Idempotent: add column if not exists + 回填仅填 segment is null 的行。

alter table sources add column if not exists segment text;
alter table sources add column if not exists industry text;

-- 外企 ATS 必为 foreign
update sources set segment = 'foreign'
 where segment is null and adapter_name in
   ('workday', 'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'apple', 'apple_cn', 'siemens');

-- 中国科技私企（自有/飞书系 adapter）
update sources set segment = 'private'
 where segment is null and adapter_name in
   ('baidu', 'jd', 'tencent', 'bytedance', 'bytedance_campus',
    'nio_feishu', 'xpeng_feishu', 'horizon_feishu', 'xiaomi_feishu', 'haier');

-- 北森/moka/company_spa 按公司定（国企 vs 私企）
update sources set segment = 'soe'
 where segment is null and company in ('中国人寿', '潍柴集团');
update sources set segment = 'private'
 where segment is null and company in ('三一集团', '杰瑞集团', '爱慕集团', '锐明技术', '横店集团');
