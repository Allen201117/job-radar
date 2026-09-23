-- 极米科技校招门户换期（2026-09-23 live 核实）。同迁移 286 那一类：Moka 每一期校招新建一个门户 id。
--
-- 现象：这条源（campus_apply/xgimi/5463）天天记 failed，报错「moka portal closed: page says 当前网页已关停」。
-- 证据：平台自己的无 id 别名 app.mokahr.com/campus_apply/xgimi 302 到该租户当前生效的校招门户 164562
--       （是平台的重定向，不是猜的 id）；用本仓库 MokaAdapter 对别名地址真抓一次：1 个在招岗
--       「【2027届校招】储备岗位」（四川·成都市），抓全（分页器无第二页）。
-- 写法同 286：存无 id 别名，下次换期自动跟过去；库里没有指向别名或 164562 的另一条源（已查，0 行）。
-- 顺带：极米社招那条（social-recruitment/xgimi/142344）是从没配置过的 Moka 默认模板（满屏「模块标题 /
--       链接标题 / © 公司名称」占位字）+ 0 岗，官网「加入我们」链到的 apply/xgimi/42935 已 404 ——
--       对方目前没有可用的公开社招入口。那条要不要停用等创始人拍板，本迁移不动它。
update sources set source_url = 'https://app.mokahr.com/campus_apply/xgimi'
 where source_url = 'https://app.mokahr.com/campus_apply/xgimi/5463';
