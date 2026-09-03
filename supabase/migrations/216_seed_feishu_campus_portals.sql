-- 216 — 飞书子门户校招源（小米 / 蔚来）
--
-- 背景：飞书招聘的同一个租户可以挂多个门户，**用哪个门户由请求头 `website-path` 决定**，
-- 与 URL 路径同名。此前判「飞书私有部署没有校招板块」是错的——错在试错了维度：当时对比的是
-- 两个 `storefront_id` 取值（返回完全相同的 1887 条），而真正的开关是这个请求头。
--
-- live 2026-09-04（纯 httpx，零浏览器、无需 _signature）：
--   小米 xiaomi.jobs.f.mioffice.cn  不带头 1894（现有社招源）/ campus 764 / internship 554
--                                   / newretailing 121  —— 四个池子互不相同
--   蔚来 nio.jobs.feishu.cn          不带头 2055（现有社招源）/ campus 920（标题全是「校招-…」）
-- jd_url 走 https://{host}/{path}/position/{id}/detail，小米 campus 首条已 live 核过页面含该岗标题。
--
-- ⚠️ **不要给存量源加 `/index/`**：`website-path: index` 拿到的是**子集**而非主门户
--    （蔚来 2055 → 1801，少 254 个岗）。adapter 已把 index 当「无子门户」，库里 70 个
--    存量 `/index/position` 源行为不变。
--
-- 加新租户的校招源**零代码**：插一行指向 https://{host}/campus/position 即可，
-- adapter 按路径自动切门户与详情模板。
--
-- board：URL 含 campus / internship → classify_source_board 规则④⑤ 自动判定，无需改函数。
-- Idempotent: guarded by source_url。crawl_method 只接受 http/playwright/manual。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)
select v.company, v.url, 'official', v.adapter, 'http', 'private', v.industry, v.notes
from (values
  ('小米', 'https://xiaomi.jobs.f.mioffice.cn/campus/position', 'xiaomi_feishu',
   '互联网·智能终端', '小米 2027届校园招聘（飞书子门户 website-path=campus）。live 2026-09-04：764 岗。'),
  ('小米', 'https://xiaomi.jobs.f.mioffice.cn/internship/position', 'xiaomi_feishu',
   '互联网·智能终端', '小米实习生招聘（飞书子门户 website-path=internship）。live 2026-09-04：554 岗。'),
  ('小米', 'https://xiaomi.jobs.f.mioffice.cn/newretailing/position', 'xiaomi_feishu',
   '互联网·智能终端', '小米 2027届新零售招聘（飞书子门户 website-path=newretailing）。live 2026-09-04：121 岗。'),
  ('蔚来', 'https://nio.jobs.feishu.cn/campus/position', 'nio_feishu',
   '汽车·智能电动', '蔚来校园招聘（飞书子门户 website-path=campus）。live 2026-09-04：920 岗，标题均为「校招-…」。')
) as v(company, url, adapter, industry, notes)
where not exists (select 1 from sources s where s.source_url = v.url);
