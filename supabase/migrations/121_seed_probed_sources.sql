-- 121 — 扩源（华为自建门户，新 adapter huawei，live 全量验证 431 岗）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。
-- 华为 portal5 公开 GET getJob 接口（零鉴权/零签名/零 cookie），jobType 1社招103/2校招198/3实习130，
-- mainBusiness 自带岗位职责正文；逐岗稳定深链 social|campus-recruitment-detail.html?jobId={id}&dataSource={ds}
-- 已 social/campus 两渠道 render-verify 过质量门。华为=最大此前未覆盖私企，零浏览器接入。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '华为', 'https://career.huawei.com/reccampportal/portal5/social-recruitment.html', 'official', 'huawei', 'http', 'private', 'ICT·通信设备', '华为（ICT/通信设备/终端，自建门户 getJob 零鉴权零浏览器，live 全量 431 岗：社103/校198/实130）'
where not exists (select 1 from sources where source_url = 'https://career.huawei.com/reccampportal/portal5/social-recruitment.html');
