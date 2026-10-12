-- 326 — 停用 28 条「门户里的岗全部超出发布年限」的 Moka 源（2026-10-12，创始人同意；保留行可回滚）
--
-- 起因：Moka 发布年限口径（卡片上的发布日期早于 730 天前的岗不收，2026-10-12 上线，见
-- docs/crawler-adapter-notes.md「moka 翻页与抓全率」一段）之后，这 28 条源的门户仍列着岗，但每一个都是两年多以前发布的，
-- 口径后每轮报成功、一个岗都不出。留着启用只会每晚白开一次浏览器，其中 15 条社招源连续 7 天后还会被
-- 「报成功却零产出」的体检点名。
--
-- 逐条核过的事实（2026-10-12 北京 20:00 重查，不是照搬上线时的名单）：
--   · 28 条都仍是启用状态；年限口径上线后只跑过一轮抓取，这一轮每条都是「成功 + 门户自报有岗 + 收到 0 个」；
--   · 28 个门户合计列出 461 个岗，上线前拿这些门户的全部卡片预演过：发布日期全部早于 730 天前；
--   · 库里这 28 条源名下的行全部是 removed（年限口径下架的），没有一行 active——停用不会留下没人管的在招岗；
--   · 13 条校招源逐个问过平台的无编号别名（campus_apply/{租户}），都仍指向我们存的这个门户编号，
--     不是「换了新一期门户、旧门户留着」那种情况。
--
-- 没验的：这些公司是不是换到了别的招聘系统（Moka 以外）。停用后必投清单里的果麦文化、微众银行、天合光能
-- 在缺口台账上会从「有源零岗」变成「没有源」，由缺口漏斗去找新入口。
-- 麦当劳校招门户（mcdchina/4328）另有会话查过：自称「系统默认校园招聘门户」，34 个岗全是广州 7 家店的门店岗，最后发布 2023-11。
--
-- 名单（渠道 / 公司 / 门户列出的岗数 / 门户）：
--   校招  国双科技（北京）有限公司  门户列出 34 个  campus-recruitment/gridsum/101877
--   校招  麦当劳  门户列出 34 个  campus-recruitment/mcdchina/4328
--   校招  云从科技  门户列出 27 个  campus-recruitment/cloudwalk/4872
--   校招  卡宾服饰（中国）有限公司  门户列出 11 个  campus-recruitment/cabbeen/29324
--   校招  轻松集团  门户列出 6 个  campus_apply/qsc/2817
--   校招  聚水潭  门户列出 4 个  campus-recruitment/jushuitan/94413
--   校招  斗鱼  门户列出 4 个  campus_apply/douyu/21995
--   校招  丁香园  门户列出 3 个  campus_apply/dxy/1488
--   校招  向日葵远程 Oray  门户列出 2 个  campus-recruitment/oray/44937
--   校招  火花思维  门户列出 1 个  campus-recruitment/huohua/1989
--   校招  凤凰网  门户列出 1 个  campus-recruitment/ifeng/7542
--   校招  科兴控股  门户列出 1 个  campus-recruitment/sinovac/4916
--   校招  喜临门家具股份有限公司  门户列出 1 个  campus-recruitment/sleemon/102129
--   社招  云从科技  门户列出 97 个  social-recruitment/cloudwalk/4871
--   社招  知道创宇  门户列出 60 个  social-recruitment/zhidaochuangyu/5123
--   社招  卡宾服饰（中国）有限公司  门户列出 37 个  social-recruitment/cabbeen/29323
--   社招  果麦文化  门户列出 29 个  social-recruitment/guomai/100111
--   社招  盖雅工场  门户列出 21 个  social-recruitment/gaiaworks/36846
--   社招  白山云  门户列出 20 个  social-recruitment/baishanyun/5295
--   社招  微播易  门户列出 18 个  social-recruitment/weiboyi/28976
--   社招  国双科技（北京）有限公司  门户列出 14 个  social-recruitment/gridsum/74006
--   社招  雪球  门户列出 12 个  apply/xueqiu/3591
--   社招  推想医疗 InferVision  门户列出 11 个  apply/infervision/2064
--   社招  掌趣科技 Playcrab  门户列出 4 个  apply/playcrab/24831
--   社招  天合光能 Trina  门户列出 3 个  apply/trinasolar/39871
--   社招  深圳前海微众银行  门户列出 3 个  social-recruitment/webank/38244
--   社招  三维家信息科技有限公司  门户列出 2 个  social-recruitment/3vjia/46197
--   社招  科沃斯  门户列出 1 个  social-recruitment/ecovacs/102402
--
-- 回滚：update sources set enabled = true where source_url in (下面这 28 个地址);
--       岗位行不用动——对方重新发布（日期变新）后，下一轮抓取会把同一行从 removed 收回 active。

update sources
   set enabled = false,
       notes = coalesce(notes, '') || E'\n\n' || $md$2026-10-12 停用（迁移 326）：门户列出的岗发布日期全部早于 730 天前（Moka 发布年限口径），口径后每轮报成功却一个岗都不出；名下的行已全部是 removed。对方发新岗或重新发布后可恢复：enabled=true，岗位行会在下一轮抓取自动收回。$md$
 where adapter_name = 'moka'
   and enabled
   and source_url in (
    'https://app.mokahr.com/campus-recruitment/gridsum/101877',
    'https://app.mokahr.com/campus-recruitment/mcdchina/4328',
    'https://app.mokahr.com/campus-recruitment/cloudwalk/4872',
    'https://app.mokahr.com/campus-recruitment/cabbeen/29324',
    'https://app.mokahr.com/campus_apply/qsc/2817',
    'https://app.mokahr.com/campus-recruitment/jushuitan/94413',
    'https://app.mokahr.com/campus_apply/douyu/21995',
    'https://app.mokahr.com/campus_apply/dxy/1488',
    'https://app.mokahr.com/campus-recruitment/oray/44937',
    'https://app.mokahr.com/campus-recruitment/huohua/1989',
    'https://app.mokahr.com/campus-recruitment/ifeng/7542',
    'https://app.mokahr.com/campus-recruitment/sinovac/4916',
    'https://app.mokahr.com/campus-recruitment/sleemon/102129',
    'https://app.mokahr.com/social-recruitment/cloudwalk/4871',
    'https://app.mokahr.com/social-recruitment/zhidaochuangyu/5123',
    'https://app.mokahr.com/social-recruitment/cabbeen/29323',
    'https://app.mokahr.com/social-recruitment/guomai/100111',
    'https://app.mokahr.com/social-recruitment/gaiaworks/36846',
    'https://app.mokahr.com/social-recruitment/baishanyun/5295',
    'https://app.mokahr.com/social-recruitment/weiboyi/28976',
    'https://app.mokahr.com/social-recruitment/gridsum/74006',
    'https://app.mokahr.com/apply/xueqiu/3591',
    'https://app.mokahr.com/apply/infervision/2064',
    'https://app.mokahr.com/apply/playcrab/24831',
    'https://app.mokahr.com/apply/trinasolar/39871',
    'https://app.mokahr.com/social-recruitment/webank/38244',
    'https://app.mokahr.com/social-recruitment/3vjia/46197',
    'https://app.mokahr.com/social-recruitment/ecovacs/102402'
   );
