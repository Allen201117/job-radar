-- 061 — 国内私企扩源批7（飞书 + Moka，live 验证）
-- crawl_method=playwright，segment='private'+industry。Idempotent。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '老虎国际 Tiger Brokers', 'https://tigertech.jobs.feishu.cn/index/position', 'official', 'feishu', 'playwright', 'private', '互联网券商',
       '老虎国际（互联网券商，飞书招聘泛化适配器，live 40 岗）'
where not exists (select 1 from sources where source_url = 'https://tigertech.jobs.feishu.cn/index/position');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '三只松鼠 Three Squirrels', 'https://app.mokahr.com/campus_apply/3songshu/457', 'official', 'moka', 'playwright', 'private', '消费·零食',
       '三只松鼠（消费·零食，Moka 渲染 DOM，live 验证）'
where not exists (select 1 from sources where source_url = 'https://app.mokahr.com/campus_apply/3songshu/457');
