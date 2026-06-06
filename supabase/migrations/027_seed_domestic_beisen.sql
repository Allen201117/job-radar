-- 027 — 本土扩源（北森/zhiye）：render 验证通过的在华企业招聘源
-- 来源：crawler/probe.py 升级版 beisen adapter live 抓取 + 详情页 render-check（构造的
--   {origin}{portal}/zwxq?jobAdId={Id} 必须渲染对应岗位且 job-specific）才入库，杜绝坏链。
-- Idempotent: guarded by source_url.

insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)
select '中国人寿', 'https://chinalife.zhiye.com/custom/intern', 'official', 'beisen', 'playwright',
       '中国人寿（金融·保险，北森 zhiye，probe render 验证 10 岗）'
where not exists (select 1 from sources where source_url = 'https://chinalife.zhiye.com/custom/intern');
