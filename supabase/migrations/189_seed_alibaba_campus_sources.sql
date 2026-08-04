-- 189 — seed：阿里 13 个 BU 的**校招**频道源（2027 届秋招供给基座）
--
-- 背景：阿里 13 个 BU 源此前全部指向 `…/off-campus/position-list`——字面就是**社招**频道
-- （adapter 里原注释还写着「校招在另一套系统」）。结果库里阿里校招岗常年 = 1 个。
--
-- 2026-08-04 live 对拍（淘天域，浏览器内同源发请求，逐 channel 值实测）钉死真相：
--   channel="GROUP_OFFICIAL_SITE"       → totalCount=605，batchName=null                      ← 社招
--   channel=""（服务端不认的任意值同）   → totalCount=34， batchName=淘天集团2026届秋季应届生招聘 ← 校招
--   channel="campus_group_official_site" → totalCount=0（这是**岗位上**的 channels 取值，不是入参取值）
-- 即：校招不在另一套系统，就是同一个 position/search 接口的**默认频道**。
-- 详情页 https://{host}/campus/position-detail?lang=zh&positionId={id} 已 live 打开验证
-- （positionId=199902900003 → 渲染出「算法工程师- AIGC方向（T-Star Lab26届秋招）」）。
--
-- ⚠️ 为什么不能只靠 channel 入参：那是服务端 fallback 行为、不是文档化契约。若哪天默认集
-- 改成社招，我们就会把 3000 个社招岗当校招灌进校招专区（比漏抓更糟——用户按校招投了社招岗）。
-- 所以 AlibabaCampusAdapter._map 用 **payload 自证**：只放行 categoryType='freshman' 或
-- batchName 含「届」的行，自证不过一律丢弃，宁可这轮抓 0 条。
--
-- 诚实边界：本迁移应用时 13 个 BU 的校招频道**大多是 0 条**（淘天 34、菜鸟 2，其余 0），
-- 因为阿里 2027 届秋招正式批还没开闸，现存的还是 2026 届尾巴。这正是本工程的意义——
-- 管子先接好，闸门一开（预计 8 月中下旬）由 campus-crawl 车道每小时刷、开闸即捞。
-- 抓 0 条不是失败：adapter 抓不到岗只会记 partial_success，不影响其他源。

insert into sources (company, source_url, adapter_name, crawl_method, regions, segment, industry, enabled)
values
  ('淘天集团',           'https://talent.taotian.com/campus/position-list?lang=zh',        'alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('阿里巴巴控股集团',   'https://talent-holding.alibaba.com/campus/position-list?lang=zh','alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('阿里云',             'https://careers.aliyun.com/campus/position-list?lang=zh',        'alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('高德地图',           'https://talent.amap.com/campus/position-list?lang=zh',           'alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('菜鸟',               'https://cn-jobs.cainiao.com/campus/position-list?lang=zh',       'alibaba_campus', 'http', '{CN}', 'private', '物流', true),
  ('菜鸟驿站',           'https://talent-post.alibaba.com/campus/position-list?lang=zh',   'alibaba_campus', 'http', '{CN}', 'private', '物流', true),
  ('饿了么',             'https://talent.ele.me/campus/position-list?lang=zh',             'alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('钉钉',               'https://talent.dingtalk.com/campus/position-list?lang=zh',       'alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('阿里国际数字商业',   'https://aidc-jobs.alibaba.com/campus/position-list?lang=zh',     'alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('通义',               'https://careers-tongyi.alibaba.com/campus/position-list?lang=zh','alibaba_campus', 'http', '{CN}', 'private', '互联网', true),
  ('灵犀互娱',           'https://talent.lingxigames.com/campus/position-list?lang=zh',    'alibaba_campus', 'http', '{CN}', 'private', '游戏', true),
  ('虎鲸文娱',           'https://jobs.hujing-dme.com/campus/position-list?lang=zh',       'alibaba_campus', 'http', '{CN}', 'private', '文娱', true),
  ('亚博科技',           'https://talent.agtech.com/campus/position-list?lang=zh',         'alibaba_campus', 'http', '{CN}', 'private', '互联网', true)
on conflict (source_url) do nothing;   -- 迁移 180 的 sources_unique_source_url，重复应用幂等
