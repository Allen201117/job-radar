-- 停用 10 条「对方入口已作废 / 已被别的入口取代」的来源（2026-09-23 创始人拍板，逐条 live 核实过）。
--
-- 背景：结构性审计「连续 7 天报成功却零产出」当天 25 条，逐个渲染对方页面核实后（见迁移 292 同批提交），
--       这 10 条属于**结构性**作废——不是「这一批招完、下一批没开」的季节性休眠（那 14 条一条没动）。
--
-- 逐条证据：
--   · 阿里 6 个子公司校招页（亚博科技 / 灵犀互娱 / 菜鸟驿站 / 通义 / 阿里云 / 饿了么）：
--     页面自写「在招职位共 0 个」，批次横幅还停在 24 届 / 26 届；crawl_runs 有记录以来（2026-05-20 起）一个岗都没出过。
--     阿里 27 届校招统一走集团主站 campus-talent.alibaba.com（listBatch 自报 1,076 岗，我们的集团主站源每天抓 ~1,061），
--     那边的岗位自带「可投子公司」（阿里云 217 / 灵犀互娱 81 / 淘宝闪购 19 …），供给没有缺口。
--   · 极米社招 social-recruitment/xgimi/142344：从没配置过的 Moka 默认模板（「模块标题 / 链接标题 / © 公司名称」占位字）+ 0 岗；
--     平台别名 social-recruitment/xgimi 302 回到它自己，官网「加入我们」链到的 apply/xgimi/42935 已 404 —— 对方没有可用的公开社招入口。
--     极米校招另一条源（迁移 292 已改到当期门户）照常。
--   · 华润三九 hotjob 旧租户 校招 / 实习：页面「在招职位0个」。公司招聘已搬到华润集团自建平台 runjob.crc.com.cn
--     （迁移 288 的 crc 源，校招 56 / 实习 25 / 社招 127 三渠道都抓），旧租户社招那条还挂着 1 个岗，**本迁移不动它**。
--   · 南孚 social-recruitment/nanfu/40971：Moka 页「尚无任何相关职位」。官网 nanfu.com「招贤纳士」改为自建页面，
--     每个岗位点开是「上传简历 + 验证码」的表单，无职位描述、无发布日期——不接（无法判断在不在招，进来也只是空壳卡）。
--
-- 影响面（2026-09-23 按 jobs.source_id 精确点名核过，香港 jobs 库）：10 条源名下 **0 行**（含任何 status）。
-- 必投覆盖：「阿里巴巴」校招由集团主站供给，仍 healthy；「菜鸟」保留自有校招源 cn-jobs.cainiao.com，campus_channel 仍 idle，不变。
--
-- 只关开关、保留行，随时把 enabled 改回 true 即可回滚（本项目一贯做法：disable 不 delete）。
update sources set enabled = false
 where source_url in (
   'https://talent.agtech.com/campus/position-list?lang=zh',
   'https://talent.lingxigames.com/campus/position-list?lang=zh',
   'https://talent-post.alibaba.com/campus/position-list?lang=zh',
   'https://careers-tongyi.alibaba.com/campus/position-list?lang=zh',
   'https://careers.aliyun.com/campus/position-list?lang=zh',
   'https://talent.ele.me/campus/position-list?lang=zh',
   'https://app.mokahr.com/social-recruitment/xgimi/142344',
   'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/school.html',
   'https://wecruit.hotjob.cn/SU613834ecbef57c3b6383b50e/pb/interns.html',
   'https://app.mokahr.com/social-recruitment/nanfu/40971'
 );
