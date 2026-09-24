-- 303 — 停用小马智行重复的 /index/ 飞书源（保留 /ponyai/ 那条）
--
-- 为什么：飞书 adapter 2026-09-23 改成主门户按「租户自报门户 ∪ index」抓（7632c445）。小马智行首页自报门户是
-- `ponyai`、没有 index 门户（-9000003 site not exist），于是这条 /index/position 源与已有的 /ponyai/position 源
-- 抓的是**同一批 82 个岗、同一个链接前缀**——两条源抢同一批行，没有新增任何覆盖。
-- 这条 /index/ 源改前库里只挂着 5 个在招岗，逐岗核在自己链接门户上 5/5 为「已下线」（由对账工具下架）。
-- 可逆：改回 enabled=true 即可。只动这一行（id + source_url 双重限定）。
update public.sources
   set enabled = false
 where id = '0bc3faec-cbf8-49e0-bfbb-c7eec4583d35'
   and source_url = 'https://ponyai.jobs.feishu.cn/index/position';
