-- 308: 欧莱雅 radancy 源改读站点地图（307 填的搜索页被对方 robots.txt 禁止）。
--
-- 现象：307 上线后首轮（2026-10-07）记 skipped「robots.txt disallows /en/search-jobs」——TalentBrew 站点
--   robots 一律禁 /search-jobs，307 那个地址从一开始就不该填，run.py 的 robots 门如实挡下了。
-- 改法：radancy adapter 改为「sitemap.xml（robots 自己声明）→ 按城市/标题粗筛 → 逐岗详情页 ld+json」，
--   详情页 /en/job/ 不在 robots 禁止之列。live 对拍：站点地图 1,694 岗逐个开详情页取 addressCountry，
--   中国 326；adapter 抓回 326、漏 0、多 0，全部带正文。
-- 可逆：改回 307 的地址（但那个地址抓不了）。幂等：id + 旧 source_url 双重限定。
update public.sources
   set source_url = 'https://careers.loreal.com/en/sitemap.xml'
 where id = 'e07c58b0-c06b-4a85-8e22-82923b674a32'
   and source_url = 'https://careers.loreal.com/en/search-jobs/China/3456/2/1814991/35/105/50/2';
