-- 217 — 飞书子门户校招源批量补齐（21 个租户 / 22 条，合计 1,326 个校招+实习岗）
--
-- 承接迁移 216 与 adapter 的 website_path 支持：飞书租户的校招岗挂在 `website-path` 子门户上，
-- 与社招（/index）是**互不相同的池子**。2026-09-04 对库里全部 71 个飞书源做了一轮慢速探活
-- （慢是刻意的——快扫会被限流，失败会被误读成「没有这个门户」），共 23 个租户有子门户、
-- 子门户岗位合计 3,685 个；其中小米(1,439)/蔚来(920) 已由迁移 216 入库，本迁移补其余 1,326 个。
--
-- 抽验（live 2026-09-04）：
--   小鹏 501 岗，标题形如「【27届校招】自动驾驶系统开发工程师」，
--     详情 https://xiaopeng.jobs.feishu.cn/campus/position/7681225039793948954/detail 打开含该岗标题；
--   拓竹 165 岗（AI 中台产品经理实习生等），正文随列表直出。
--
-- ⚠️ 这些源**不需要新 adapter**：FeishuRecruitAdapter 从 source_url 的首个路径段派生子门户。
-- ⚠️ 仍然不要给存量社招源加 /index/（`website-path: index` 是子集，蔚来 2055→1801）。
-- ⚠️ 探活数字是「当时那一刻」的，不是承诺；真实产出以 crawl_runs 为准，抓不到的由 watchdog 规则 G 报。
--
-- Idempotent: guarded by source_url。crawl_method 只接受 http/playwright/manual。

insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, notes)
select v.company, v.url, 'official', v.adapter, 'http', 'private', v.notes
from (values
  ('小鹏汽车', 'https://xiaopeng.jobs.feishu.cn/campus/position', 'xpeng_feishu', '小鹏汽车 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：501 岗。'),
  ('拓竹科技', 'https://bambulab.jobs.feishu.cn/campus/position', 'feishu', '拓竹科技 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：165 岗。'),
  ('沐瞳科技', 'https://moonton.jobs.feishu.cn/campus/position', 'feishu', '沐瞳科技 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：94 岗。'),
  ('懂车帝 Dcar', 'https://dcar.jobs.feishu.cn/campus/position', 'feishu', '懂车帝 Dcar 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：91 岗。'),
  ('库洛游戏 Kuro', 'https://kurogame.jobs.feishu.cn/campus/position', 'feishu', '库洛游戏 Kuro 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：84 岗。'),
  ('VAST', 'https://a9ihi0un9c.jobs.feishu.cn/campus/position', 'feishu', 'VAST 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：74 岗。'),
  ('中科创达', 'https://thundersoft.jobs.feishu.cn/campus/position', 'feishu', '中科创达 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：67 岗。'),
  ('脉脉', 'https://maimai.jobs.feishu.cn/campus/position', 'feishu', '脉脉 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：48 岗。'),
  ('面壁智能', 'https://modelbest.jobs.feishu.cn/campus/position', 'feishu', '面壁智能 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：48 岗。'),
  ('轻舟智航科技有限公司', 'https://qcraft.jobs.feishu.cn/campus/position', 'feishu', '轻舟智航科技有限公司 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：31 岗。'),
  ('Momenta', 'https://momenta.jobs.feishu.cn/campus/position', 'feishu', 'Momenta 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：28 岗。'),
  ('莉莉丝游戏 Lilith', 'https://lilithgames.jobs.feishu.cn/campus/position', 'feishu', '莉莉丝游戏 Lilith 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：19 岗。'),
  ('欢乐互娱', 'https://huanle.jobs.feishu.cn/campus/position', 'feishu', '欢乐互娱 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：15 岗。'),
  ('霸王茶姬（北京）餐饮管理有限公司', 'https://chagee.jobs.feishu.cn/campus/position', 'feishu', '霸王茶姬（北京）餐饮管理有限公司 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：14 岗。'),
  ('亚信安全', 'https://asiainfo-sec.jobs.feishu.cn/campus/position', 'feishu', '亚信安全 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：12 岗。'),
  ('XREAL', 'https://xreal.jobs.feishu.cn/campus/position', 'feishu', 'XREAL 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：8 岗。'),
  ('爱奇艺股份有限公司', 'https://iq.jobs.feishu.cn/campus/position', 'feishu', '爱奇艺股份有限公司 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：8 岗。'),
  ('后摩智能 Houmo', 'https://houmo.jobs.feishu.cn/campus/position', 'feishu', '后摩智能 Houmo 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：5 岗。'),
  ('极致游戏', 'https://jzyxgames.jobs.feishu.cn/campus/position', 'feishu', '极致游戏 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：5 岗。'),
  ('北京蓝色光标数据科技', 'https://bluefocus.jobs.feishu.cn/campus/position', 'feishu', '北京蓝色光标数据科技 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：4 岗。'),
  ('海亮集团', 'https://hailiang.jobs.feishu.cn/campus/position', 'feishu', '海亮集团 校园招聘（飞书子门户 website-path=campus，与社招 /index 是两个独立池子）。live 2026-09-04 探活：3 岗。'),
  ('爱奇艺股份有限公司', 'https://iq.jobs.feishu.cn/internship/position', 'feishu', '爱奇艺股份有限公司 实习生招聘（飞书子门户 website-path=internship，与社招 /index 是两个独立池子）。live 2026-09-04 探活：2 岗。')
) as v(company, url, adapter, notes)
where not exists (select 1 from sources s where s.source_url = v.url);
