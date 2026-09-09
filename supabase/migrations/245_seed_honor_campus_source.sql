-- 245 — 荣耀 Honor 校招（应届生）门户接入（2026-09-09 真浏览器核验）
--
-- 现象：校招专区里荣耀一直「待接入 · 暂无校招在招岗位」，库里荣耀校招 0、实习 18。
-- 根因：荣耀在 career.honor.com 上挂了 **三个不同 suiteKey** 的 wecruit 门户（应届生 / 实习生 / 博士生），
--   库里只接了实习生那个（SU61b9b9992f9d24431f5050a5），拿它的 suiteKey 开 school.html 只会得到
--   「内部处理中，请稍后再试」——所以此前判「荣耀没开校招」是拿错门判的（同 CLAUDE.md
--   「接口返 0/403 不能证明对方没开」那节的坑）。应届生门户的 suiteKey 是从 hihonor.com/cn/career/
--   首页「应届生」链接点出来的：SU60eea919bef57c1023f6fe78。
-- 证据（本机 hotjob adapter 真跑 school.html）：parse 93 岗、reported_total 93、fetch_complete=True，
--   首条「服务解决方案管培生」、jd_url 形如 …/pb/posDetail.html?postId=…&postType=campus；
--   官网页面自报「在招职位 98 个」（2027 届应届本硕项目，recruitType=1），差额为抓取时刻的上下架。
--   should_skip(url) 返回 None（不会整源被跳过）。robots.txt 404（无限制）。
-- 博士生门户 SU60eea1aa0dcad47a7e1ce1ed 本次不接（未核验岗位数与 jd_url）。
insert into sources (company, source_url, source_type, adapter_name, crawl_method, enabled, segment, industry, regions, notes)
values (
  '荣耀 Honor',
  'https://career.honor.com/SU60eea919bef57c1023f6fe78/pb/school.html',
  'official',
  'hotjob',
  'http',
  true,
  'private',
  '手机/智能终端',
  '{CN}',
  $md$2026-09-09 接入：荣耀应届生校招门户（独立 suiteKey SU60eea919bef57c1023f6fe78，与实习生门户 SU61b9b9992f9d24431f5050a5 不是同一个）。live hotjob adapter 真跑 93 岗 / 自报 93 / fetch_complete=True，官网页面写「在招职位 98 个」。别再拿实习生那个 suiteKey 开 school.html 判「没开校招」。$md$
)
on conflict do nothing;
