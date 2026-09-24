-- 302 — 接入去哪儿旅行社招（飞书招聘 hf7l9aiqzx.jobs.feishu.cn）
--
-- 为什么：去哪儿在静态目标清单里，自动扩源按 slug 探 Moka 命中的 app.mokahr.com/social-recruitment/qunar/37562
-- 只是个空壳（「尚无任何相关职位」），浏览器确认 53 次 0 岗；其官方 Moka 页的「社会招聘」按钮直链到飞书租户
-- hf7l9aiqzx.jobs.feishu.cn（从对方官方页面点过去的，不是猜的 slug）。校招在自建站 campus.qunar.com，本次不接。
--
-- ── 接入前 live 验过的事实（2026-09-23）──
--   · 租户自报：tenant_name「北京趣拿软件科技有限公司」（去哪儿运营主体）、门户标题「去哪儿旅行招聘」、
--     website_info.path = index。源名用自报品牌「去哪儿旅行」（必投分级 pattern %去哪儿% 命中）。
--   · 公开门户（website-path: index）自报 59 岗；改过的 feishu adapter（按公开门户抓，同批提交）端到端
--     fetch→parse 59 / fetch_complete=True / jd_url 全部 /index/position/{id}/detail，抽样浏览器实开可见完整 JD。
--   · 不带 website-path 头会拿到 74 岗，多出的 18 个在公开页全是「该职位已下线」——这正是本批修的 adapter 问题，
--     所以本源必须在 adapter 修好之后才接（旧口径接进来就是 24% 死链）。
-- 回滚：update sources set enabled=false where source_url='https://hf7l9aiqzx.jobs.feishu.cn/index/position';

insert into public.sources (company, source_url, source_type, adapter_name, crawl_method,
                            enabled, regions, segment, industry, notes)
select v.company, v.url, 'official', 'feishu', 'http', true, '{CN}', 'private', '互联网', v.notes
from (values
  ('去哪儿旅行', 'https://hf7l9aiqzx.jobs.feishu.cn/index/position',
   '2026-09-23 接入：租户自报 tenant_name 北京趣拿软件科技有限公司、门户标题「去哪儿旅行招聘」；官方 Moka 页「社会招聘」直链。公开门户 59 岗 live = 自报 59。')
) as v(company, url, notes)
where not exists (select 1 from public.sources s where s.source_url = v.url);
