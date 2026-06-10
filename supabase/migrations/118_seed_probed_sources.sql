-- 118 — 扩源（知名大私企 moka 自定义域，probe live 探活，#/job/{uuid} 稳定深链）
-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url。
-- 关键: 这些公司用 moka 但跑在自有域名(非 app.mokahr.com)；之前用 wrapper 落地页抓失败，
-- 改用真实 moka 页 {host}/social-recruitment|campus-recruitment/{tenant}/{orgId} 即由现有 MokaAdapter 抓出。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '宁德时代', 'https://talent.catl.com/social-recruitment/catlhr/96144', 'official', 'moka', 'playwright', 'private', '动力电池', '宁德时代CATL（动力电池，moka 自有域，probe live 探活 1800 岗）'
where not exists (select 1 from sources where source_url = 'https://talent.catl.com/social-recruitment/catlhr/96144');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '吉利汽车', 'https://campus.geely.com/campus-recruitment/geely/78436', 'official', 'moka', 'playwright', 'private', '汽车', '吉利汽车（汽车，moka 自有域校招，probe live 探活 434 岗）'
where not exists (select 1 from sources where source_url = 'https://campus.geely.com/campus-recruitment/geely/78436');

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select '大疆创新', 'https://apply.careers.dji.com/social-recruitment/dji/170070', 'official', 'moka', 'playwright', 'private', '无人机·智能硬件', '大疆DJI（无人机·智能硬件，moka 自有域，probe live 探活 430 岗）'
where not exists (select 1 from sources where source_url = 'https://apply.careers.dji.com/social-recruitment/dji/170070');
