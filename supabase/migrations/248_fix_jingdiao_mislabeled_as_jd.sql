-- 248 — 纠正张冠李戴：jd.hotjob.cn 是「精雕科技集团」不是「京东集团」（2026-09-09 查实）
--
-- 现象：库里「京东集团」名下 74 个 active 岗（机加工 / CAE 分析师 / 驱动系统研发 / 质量工程师…），
--   全部来自 https://jd.hotjob.cn/SU6923bd7fd14e321454349e91/pb/{school,social}.html 两条源。
-- 根因：接源时看见子域名 `jd` 就当成了京东。live 核验：
--   POST https://jd.hotjob.cn/wecruit/suite/config/SU6923bd7fd14e321454349e91 返回
--   companyName = 精雕科技集团股份有限公司，keywords = 北京精雕科技社会招聘/校园招聘…
--   —— 与京东（campus.jd.com / zhaopin.jd.com）无任何关系。
-- 后果：按「京东」筛出来的是精雕的机加工岗（归属准确性红线，同「国聘集团展开 84% 挂错公司」那节）。
-- 处置：源保留、改正公司名（岗位是真实的、jd_url 稳定，只是挂错了名）；jobs 热表在香港库，
--   同日用 psql 把这 74 行的 company 一并改成「精雕科技集团」（见迁移说明，不在本文件里）。
update sources
   set company = '精雕科技集团',
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-09-09 公司名由「京东集团」纠正为「精雕科技集团」：suite/config 接口自报 companyName=精雕科技集团股份有限公司（北京精雕，数控机床），jd 是「精雕」拼音缩写不是京东。$md$
 where source_url like 'https://jd.hotjob.cn/SU6923bd7fd14e321454349e91/%'
   and company = '京东集团';
