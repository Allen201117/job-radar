-- ============================================================
-- jobs 结构化字段：经验 / 学历 / 截止日期
-- ============================================================
-- 背景：卡片上的「经验/学历/截止」原先靠前端正则从 summary 派生，而 summary 被
-- clean_summary 截到 400 字，常抠不到 → 显示「未知」。改为爬虫从**完整 JD** 抽取后
-- 写入这三列，前端直接读列（列为空时回退旧正则，兼容历史行/未重抓的行）。
--
-- 幂等：add column if not exists。应用本迁移后，下一次抓取会回填历史行的这三列
-- （upsert 走 update 路径）。⚠️ 未应用本迁移就部署新爬虫代码会导致写库报「未知列」。

alter table jobs add column if not exists experience text;  -- 经验要求，如 "3-5年" / "应届/不限"
alter table jobs add column if not exists education text;    -- 学历要求，如 "本科" / "硕士" / "不限"
alter table jobs add column if not exists deadline text;     -- 截止，如 "2026-06-30" / "长期有效"
