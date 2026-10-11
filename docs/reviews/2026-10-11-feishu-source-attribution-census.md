# 飞书系源「库里公司名 ↔ 门户自报名」全量普查（2026-10-11）

状态：只核实、没改任何线上数据和代码。下面的处置与改法都等创始人确认后再动。

## 一、结论

飞书系源共 138 条（`feishu` 129、`xiaomi_feishu` 4、`nio_feishu` 2、`xpeng_feishu` 2、`horizon_feishu` 1），分布在 110 个主机上。全部取到了门户首页，逐条和库里公司名对过；机器判「对不上 / 判不了」的 15 条，加上机器判「对得上」里人工看出不对的 1 条，都在浏览器里实开过门户页。

- 在用 134 条：对得上 127 / 对不上 4 / 判不了 3
- 停用 4 条：对得上 3 / 对不上 0 / 判不了 1

真挂错名的在用源有 4 条，其中 3 条是另一家公司，1 条是名字写错一个字。除字节那条外，另外 3 条都不是自动扩源放进来的，是 2026-09-04 那批外部清单经 `probe.py` 入库的（迁移 218），那条路上没有任何核名。

## 二、对不上（4 条，全部在用）

| 库里公司名 | 门户地址 | 门户自报（租户名 / 页面标题） | 在招岗 | 结论 | 依据 |
|---|---|---|---:|---|---|
| 抖音 | bytedance.jobs.feishu.cn/index | ByteDance / （无标题） | 8351 | 对不上：另一家公司 | 门户自报字节跳动（租户名 ByteDance，关键词「字节跳动招聘官网」）；只靠岗位标题里的业务线名「抖音生活服务」过的核名门 |
| 英科医疗 | global-intco.jobs.feishu.cn/index | 英科 / 英科再生社会招聘官网 | 87 | 对不上：同集团的另一家上市公司 | 门户标题「英科再生社会招聘官网」；87 个岗里「手套」0 个，有「再生塑料粒子」「回收设备」「框条」；租户名只写「英科」 |
| 容知日新 | mammotion.jobs.feishu.cn/index | 深圳库犸创新科技集团有限公司 / 加入深圳库犸科技有限公司 | 84 | 对不上：另一家公司 | 门户自报深圳库犸科技（Mammotion，庭院割草机器人）；页面正文「库犸」21 处、「容知」0 处；岗位在深圳 / 杜塞尔多夫 |
| 千署科技 | tranxmart.jobs.feishu.cn/index | 千曙科技 / 加入千曙科技 | 8 | 对不上：名字写错一个字 | 门户自报「千曙科技」（千方科技的自动驾驶子公司），库里写成「千署科技」 |

补充事实：

- 这 4 条源名下的岗没有任何用户收藏 / 投递 / 忽略；只有字节那条有 1 个用户的 2 次浏览记录。
- 容知日新、英科医疗、千署科技三条的岗位详情页在浏览器里都能正常打开（各实开 1 条），问题只在公司名。字节那条的详情页打不开（Not Found），见记忆库里上一轮的结论。
- 洞察库里「容知日新」「英科医疗」两个画像各挂着 8 条按在招岗算出来的说法（例：「容知日新在招岗位数 84 个」），算的是库犸和英科再生的岗；同一画像下来自年报的 2~3 条说法是真的。
- 英科这个租户是集团共用的：公开门户（标题「英科再生社会招聘官网」）87 个岗，我们现在抓的就是这 87 个；租户里另有 381 个岗不在这个门户上（淮北 111、安庆 58、九江 38、潍坊 32，正文有「手套」「丁腈」「轮椅」），应是英科医疗一侧的，挂在哪个公开门户没查到。9 月 24 日飞书改成按公开门户抓之前，这批是抓得到的（洞察里记着「30 天前 488 个」）。

## 三、判不了（4 条：在用 3、停用 1）

| 库里公司名 | 状态 | 门户地址 | 门户自报（租户名 / 页面标题） | 在招岗 | 为什么判不了 |
|---|---|---|---|---:|---|
| 算秩未来 | 在用 | acnizrso7ikb.jobs.feishu.cn/index | 算力业务线 / 加入算力业务线 | 1 | 门户自报「算力业务线」，不是公司名；公开门户只有 1 个岗，正文没写公司；外部搜索没找到这个域名的归属 |
| 上海航天电子技术研究所 | 在用 | toa7dmu9bq.jobs.feishu.cn/index | 电子所 / 欢迎加入电子所 | 18 | 门户只自报简称「电子所」；岗位全在上海，内容是箭载电源 / 整星试验 / 雷达信号处理，与库名吻合，没有反证，也没有正面证据 |
| 地平线 | 停用 | horizon.jobs.feishu.cn/index | 汉森 / 加入汉森 | 0 | 门户现在自报「汉森」，0 个岗；源已停用，库里没有它的行 |
| 道旅科技 Dida | 在用 | didatravel.jobs.feishu.cn/index | （无） / （无） | 0 | 门户首页 404，浏览器里是 Not Found；库里 0 个在招；这条源最近 4 轮都是「抓到 0 个、记成功」 |

## 四、名字不一样、但核过是同一家（8 条）

机器按字面判「对不上」，逐条看过是品牌名和法人名的差别。

| 库里公司名 | 状态 | 门户地址 | 门户自报（租户名 / 页面标题） | 判成同一家的依据 |
|---|---|---|---|---|
| 凯叔讲故事 | 停用 | kaishu.jobs.feishu.cn/index | 北京凯声文化传媒有限责任公司 / 加入北京凯声文化传媒有限责任公司 | 法人名：北京凯声文化传媒（入库备注里就写了） |
| 光轮智能 | 在用 | lightwheel.jobs.feishu.cn/index | 启数光轮科技（上海）有限公司 / 加入启数光轮科技（上海）有限公司 | 法人名：启数光轮科技（上海）；域名前缀 lightwheel |
| 中际旭创 | 在用 | zj-innolight.jobs.feishu.cn/index | 苏州旭创科技有限公司 / 加入苏州旭创科技有限公司 | 法人名：苏州旭创科技是中际旭创的经营主体；域名前缀 zj-innolight。门户页里没有「中际旭创」四个字，靠公开资料 |
| 千岛 | 在用 | echotech.jobs.feishu.cn/index | 回响科技 / 加入回响科技 | 运营公司名：回响科技；门户路径 qiandaozhaopin，页面正文有「千岛」 |
| 心动网络 | 在用 | xd.jobs.feishu.cn/index | XD Inc. / 加入XD Inc. | 英文公司名 XD Inc.；页面正文「工作在心动」。浏览器里会跳到 xd-legacy.jobs.feishu.cn，详情页能开 |
| 北电数智 | 在用 | caz6yhvgk5z.jobs.feishu.cn/index | 北京电子数智科技有限责任公司 / 加入北京电子数智科技有限责任公司 | 法人名：北京电子数智科技；页面导航写着「北电数智招聘官网」 |
| 哪吒汽车 | 在用 | hozonauto.jobs.feishu.cn/index | 合众新能源汽车股份有限公司 / 加入合众新能源汽车有限公司 | 法人名：合众新能源汽车；页面正文有「哪吒」 |
| 游戏精酿 | 在用 | gamealestudio.jobs.feishu.cn/index | GameAle / 匠心酿制，精品游戏！ | 英文品牌名 GameAle；页面正文有「游戏精酿」 |

## 五、核名门改成「只认门户自报」的影响

重放口径：在用的 134 条源，用库里公司名的中文部分当候选名；旧门 = 首页 `<title>` 含公司名，或不带门户头探到的前 5 个岗位标题里有一个含公司名（与 `discover_domestic.feishu_probe` 逐字相同的请求）；新门 = 首页自报的租户名 / `<title>` / 浏览器标签名 / 关键词里含公司名，不看岗位标题。

| | 旧门 | 新门 |
|---|---:|---:|
| 通过 | 110 | 112 |
| 不通过 | 24 | 22 |

- 旧门通过 → 新门不通过：1 条，就是「抖音」。其中真挂错 1 条，被误伤的正常源 0 条。
- 旧门不通过 → 新门通过：3 条（卡尔动力、洋葱学园、网眼科技），都是归属正确的源，因为新门多读了租户名和关键词。
- 旧门里只靠岗位标题过关的共 2 条：「抖音」（挂错）和「美图公司」（首页标题写的是子品牌 Pixocial，但租户名就是美图公司，新门照样过）。
- 只看自动扩源放进来的 17 条：旧门今天重放 16 过 1 不过，新门 15 过 2 不过，变化的也只有「抖音」。

两个要钉死的细节：

- 「门户自报」不能包含页面简介（meta description）。字节首页的简介里列着「今日头条、抖音、西瓜视频、飞书」，把简介算进去「抖音」照样能过。
- 新门用现有的 `_verify`（库名的核心词必须出现在门户文本里，单方向）。周检用的 `names_agree` 会反过来拿门户名去库名里找，租户名只有两个字时会误放：它把「英科医疗」对「英科」判成对得上。

另外三条挂错的（容知日新、千署科技、英科医疗）放到新门下也都不通过，只是它们当初走的是没有核名的那条路。新门会拒掉的正常源是「品牌名对法人名 / 英文名」这一类，现有 134 条里有 15 条；旧门同样拒它们，所以不是新增损失。

重放的局限：岗位标题用的是今天的前 5 条，不是入库那天的；候选名用的是库名，不是当时清单里的名字。例：「心动网络」7 月 7 日经自动扩源入库，今天新旧两道门都不过。

## 六、入库前按岗位编号查重

拿全部 110 个主机现在探到的岗位编号去库里查「同一个编号挂在别的域名下」，两种取法结果不同：

| 取编号的方式 | 探针编号数 | 命中 | 其中真重复 | 其中误命中 |
|---|---:|---:|---:|---:|
| 不带门户头（租户全集） | 1,774 | 2 对 | 1（字节） | 1（得物） |
| 带门户自报路径的头（该门户自己的岗） | 1,751 | 1 对 | 1（字节） | 0 |

得物那一对是同一个租户的两个门户：校招挂在自己的域名上，社招挂在飞书域名上，两条源抓的岗不重复，不该拦。所以查重必须用门户自己的编号。

耗时：一次查询要全表扫一遍 jobs（约 50 万行、读 15 万个数据块），实测 1.2 秒；按「每轮把所有通过核名的候选的编号合成一条查询」做，一轮多一次。

另一个不花钱的信号：首页自报的 `portal_domain`（租户自己绑的官网域名）。110 个主机里只有字节这一个非空（`job.toutiao.com`）。

## 七、方案（等确认）

### 存量处置

| 源 | 建议 | 步骤 |
|---|---|---|
| 抖音（bytedance.jobs.feishu.cn） | 停源 + 清掉名下的行 | 沿用上一轮已报的方案：停源迁移 → 等在飞的抓取轮过完 → `remove-jobs-by-url-prefix`（前缀 `https://bytedance.jobs.feishu.cn/`、公司「抖音」）→ 回读计数 |
| 容知日新 → 库犸科技 | 改名，不删行 | 迁移改 `sources.company` 与备注 → 等在飞的抓取轮过完 → `rename-job-company`（先 dry-run）→ 回读 84 行 |
| 英科医疗 → 英科再生 | 改名，不删行 | 同上，87 行。其中 15 个淮北「凯泽」岗是集团里另一家公司挂在这个门户上的，跟着门户名走 |
| 千署科技 → 千曙科技 | 改名，不删行 | 同上，8 行 |
| 道旅科技 Dida | 停用 | 门户已不存在，库里 0 在招；停用只是让它不再每轮报「成功 0 岗」 |
| 上海航天电子技术研究所、算秩未来 | 不动 | 进周检的「判不了」名单，有新证据再判 |

改名连带要做的三件事：

- 洞察库「容知日新」「英科医疗」画像下各 8 条按岗位算出来的说法要下架；改名后它们会不会自动下架，这条没验，执行时要回读。
- 新名字的画像走统一入口建（先认别名，没有才建），不直接往画像表里写。
- 改 `jobs.company` 会把招聘类别的物化列置空等回填，改完到回填跑完之间这 179 行在校招 / 实习筛选里会暂时消失。

### 核名门怎么改

1. `discover_domestic.feishu_probe`：核名只认首页自报的租户名 / `<title>` / 浏览器标签名 / 关键词，去掉「岗位标题里含公司名也算」，不读页面简介。
2. 同一处：`portal_domain` 非空且不是当前主机时不自动入库，记进台账单列，由人看。
3. `probe.py` 这条路（外部清单 → 探活 → 生成迁移）对飞书候选加同一道核名：对不上的不写进迁移，除非逐条写明理由。这次 4 条里的 3 条是从这里进来的。
4. 自动扩源入库前加岗位编号查重：用门户自己的编号，每轮合成一条只读查询；命中就不入库，计进台账。
5. 周检 `audit_hotjob_attribution` 加飞书系：三类计数进台账；第四节那 8 条写进「核过是同一家」的名单；反向只靠两个字对上的单列出来给人看。

每一条都配回归用例：字节首页（简介含「抖音」、关键词是字节跳动）必须不过；美图（标题是子品牌、租户名对）必须过；得物两个门户不许被查重拦掉。

### 顺带发现，没动

- 英科医疗自己的岗（约 381 个）现在一条都没抓到，要先找到它挂在哪个公开门户。
- 心动网络的飞书域名在浏览器里跳到 `xd-legacy`，岗位还能开；「legacy」是不是意味着主门户搬了，没查。
- 周检结果目前只进台账和 CI 日志，不进晨报（CLAUDE.md 里已有这条记载）。

## 八、怎么复现

- 源清单：Supabase `sources` 分页取全（1,730 行，2 页），按 `adapter_name` 取飞书系 138 行；另按地址特征反查，没有「地址像飞书但 adapter 不是飞书系」的行。
- 门户自报：对每个主机取 `https://{host}/`，对每条源再取它自己的 `source_url`；读 `<title>`、meta keywords、`"tenant_name"`、`"website_info"` 的名字与路径、`"browser_label_name"`、`"portal_domain"`。110 个主机里 109 个首页返回 200，1 个 404（道旅）。
- 名字比对：`audit_hotjob_attribution.names_agree` 加拉丁品牌词；机器结果 在用 121 对得上 / 12 对不上 / 1 判不了，人工复核后是上面的数。「对得上」的 123 条逐条过目过一遍，改判 1 条（英科医疗）。
- 岗位侧：香港 jobs 库只读查询，按 jd_url 主机 × 公司名 × 状态计数；飞书系域名下在招 33,096 行，一个主机挂两个公司名的只有小马智行（旧名的行都已是 removed）。

## 附：对得上的其余 122 条

| 库里公司名 | 状态 | 门户地址 | 租户名 | 页面标题 |
|---|---|---|---|---|
| Aibee | 在用 | aibee.jobs.feishu.cn/index | Aibee | 欢迎加入Aibee |
| MetaApp | 在用 | meta.jobs.feishu.cn/index | MetaApp | 加入MetaApp |
| MiniMax 稀宇科技 | 在用 | vrfi1sk8a0.jobs.feishu.cn/index | MiniMax | 加入MiniMax |
| Momenta | 在用 | momenta.jobs.feishu.cn/campus | Momenta | Momenta Talent |
| Momenta | 在用 | momenta.jobs.feishu.cn/index | Momenta | Momenta Talent |
| Soul | 在用 | soulapp.jobs.feishu.cn/index | 上海任意门科技有限公司 | Soul年轻人的社交元宇宙 |
| VAST | 在用 | a9ihi0un9c.jobs.feishu.cn/index | VAST | JOIN VAST |
| VAST | 在用 | a9ihi0un9c.jobs.feishu.cn/campus | VAST | JOIN VAST |
| XREAL | 在用 | xreal.jobs.feishu.cn/campus | XREAL | 加入XREAL |
| XREAL | 在用 | xreal.jobs.feishu.cn/index | XREAL | 加入XREAL |
| xTool | 在用 | xtool.jobs.feishu.cn/index | xTool | 来 xTool ，让更多人享受创造的乐趣 |
| 七匹狼实业股份有限公司 | 在用 | septwolves.jobs.feishu.cn/index | 七匹狼 | 加入七匹狼集团 |
| 上海龙旗科技 | 在用 | longcheer.jobs.feishu.cn/index | 上海龙旗科技股份有限公司 | 加入上海龙旗科技股份有限公司 |
| 东软集团股份有限公司 | 在用 | neusoft.jobs.feishu.cn/index | 东软集团 | 加入东软集团 |
| 中科创达 | 在用 | thundersoft.jobs.feishu.cn/index | ThunderSoft | ThunderSoft｜中科创达是领先的智能操作系统产品和技术提供商 |
| 中科创达 | 在用 | thundersoft.jobs.feishu.cn/campus | ThunderSoft | ThunderSoft｜中科创达是领先的智能操作系统产品和技术提供商 |
| 亚信安全 | 在用 | asiainfo-sec.jobs.feishu.cn/campus | 亚信 | 加入亚信安全 |
| 亚信安全 | 在用 | asiainfo-sec.jobs.feishu.cn/index | 亚信 | 加入亚信安全 |
| 会通股份 | 在用 | orinko-ht.jobs.feishu.cn/index | 会通新材料股份有限公司 | 加入会通新材料股份有限公司 |
| 元气森林 | 在用 | k11pnjpvz1.jobs.feishu.cn/index | 元气森林 | 加入元气森林 |
| 其域创新 | 在用 | pecivkvtit.jobs.feishu.cn/index | 深圳市其域创新科技有限公司 | 加入深圳市其域创新科技有限公司 |
| 分贝通 | 在用 | fenbeitong.jobs.feishu.cn/index | 北京分贝通科技有限公司 | 分贝通招聘 |
| 创梦天地 | 在用 | idreamsky.jobs.feishu.cn/index | 深圳市创梦天地科技有限公司 | 加入创梦天地 |
| 利欧集团 | 在用 | leoglobal.jobs.feishu.cn/index | 利欧集团 | 加入利欧集团 |
| 北京蓝色光标数据科技 | 在用 | bluefocus.jobs.feishu.cn/index | 蓝色光标集团 | 加入北京蓝色光标数据科技股份有限公司 |
| 北京蓝色光标数据科技 | 在用 | bluefocus.jobs.feishu.cn/campus | 蓝色光标集团 | 加入北京蓝色光标数据科技股份有限公司 |
| 半鞅私募基金 | 在用 | banyangcap.jobs.feishu.cn/index | 半鞅私募基金 | 加入半鞅私募基金 |
| 华米科技 | 在用 | zepp.jobs.feishu.cn/index | Zepp Health | 加入华米科技 |
| 卡尔动力 | 在用 | kargobot.jobs.feishu.cn/index | 卡尔动力 | 加入KargoBot |
| 卡方科技 | 在用 | kafangtech.jobs.feishu.cn/index | 上海卡方信息科技有限公司 | 加入上海卡方信息科技有限公司 |
| 原力灵机 | 在用 | dexmal-inc.jobs.feishu.cn/index | 原力灵机 | 欢迎加入原力灵机 |
| 厦门艾德生物医药科技股份有限公司 | 在用 | amoydiagnostics.jobs.feishu.cn/index | 艾德生物 | 艾德生物 Careers |
| 去哪儿旅行 | 在用 | hf7l9aiqzx.jobs.feishu.cn/index | 北京趣拿软件科技有限公司 | 去哪儿旅行招聘 |
| 后摩智能 Houmo | 在用 | houmo.jobs.feishu.cn/campus | 北京后摩智能科技有限公司 | 后摩智能 |
| 后摩智能 Houmo | 在用 | houmo.jobs.feishu.cn/index | 北京后摩智能科技有限公司 | 后摩智能 |
| 启元机器人 | 在用 | primebot.jobs.feishu.cn/index | 启元业务部 | 加入启元机器人 |
| 商汤科技 SenseTime | 在用 | sensetime.jobs.feishu.cn/index | 商汤科技 | 加入商汤科技 |
| 地素时尚股份有限公司 | 在用 | dazzle-fashion.jobs.feishu.cn/index | 地素时尚股份有限公司 | 加入地素时尚股份有限公司 |
| 多点DMALL | 在用 | duodian.jobs.feishu.cn/index | 多点Dmall | 多点Dmall招聘官网 |
| 它石智航 TARS | 在用 | tarsrobot.jobs.feishu.cn/index | 它石智航 | 加入它石智航 |
| 安克创新 Anker | 在用 | anker-in.jobs.feishu.cn/index | Anker Innovations | 加入安克创新 |
| 小米 | 在用 | xiaomi.jobs.f.mioffice.cn/campus | 小米科技 | 小米社会招聘 |
| 小米 | 在用 | xiaomi.jobs.f.mioffice.cn/index | 小米科技 | 小米社会招聘 |
| 小米 | 在用 | xiaomi.jobs.f.mioffice.cn/newretailing | 小米科技 | 小米社会招聘 |
| 小米 | 在用 | xiaomi.jobs.f.mioffice.cn/internship | 小米科技 | 小米社会招聘 |
| 小马智行 Pony.ai | 在用 | ponyai.jobs.feishu.cn/ponyai | 小马智行 | 小马智行Pony.ai 招聘 |
| 小鹏汽车 | 在用 | xiaopeng.jobs.feishu.cn/index | 小鹏集团 | 加入小鹏集团 |
| 小鹏汽车 | 在用 | xiaopeng.jobs.feishu.cn/campus | 小鹏集团 | 加入小鹏集团 |
| 库洛游戏 Kuro | 在用 | kurogame.jobs.feishu.cn/campus | 广州库洛科技有限公司 | 库洛游戏招聘 |
| 库洛游戏 Kuro | 在用 | kurogame.jobs.feishu.cn/index | 广州库洛科技有限公司 | 库洛游戏招聘 |
| 度小满金融科技（北京）有限公司 | 在用 | duxiaoman.jobs.feishu.cn/index | 度小满科技（北京）有限公司 | 加入度小满 |
| 康师傅控股有限公司 | 在用 | masterkong.jobs.feishu.cn/index | 康师傅控股 | 加入康师傅控股 |
| 得到 | 在用 | dedao.jobs.feishu.cn/index | 得到APP | 得到-社会招聘 |
| 得物 POIZON | 在用 | campus.dewu.com/578078 | 上海得物信息集团有限公司 | 得物App校园招聘 |
| 得物 POIZON | 在用 | poizon.jobs.feishu.cn/index | 上海得物信息集团有限公司 | 加入得物App |
| 恺英网络 | 在用 | kingnet.jobs.feishu.cn/index | 恺英网络股份有限公司 | 加入恺英网络股份有限公司 |
| 懂车帝 Dcar | 在用 | dcar.jobs.feishu.cn/campus | 懂车帝 | 懂车帝招聘 |
| 懂车帝 Dcar | 在用 | dcar.jobs.feishu.cn/index | 懂车帝 | 懂车帝招聘 |
| 拓竹科技 | 在用 | bambulab.jobs.feishu.cn/index | Bambulab | 加入拓竹科技 |
| 拓竹科技 | 在用 | bambulab.jobs.feishu.cn/campus | Bambulab | 加入拓竹科技 |
| 掌阅科技 | 在用 | q7w8vltyes.jobs.feishu.cn/index | 掌阅科技 | 加入掌阅科技 |
| 无问芯穹 | 在用 | infinigence.jobs.feishu.cn/index | 无问芯穹 | 加入无问芯穹 |
| 旭辉控股（集团）有限公司 | 在用 | cifigroup.jobs.feishu.cn/index | 旭辉 | 加入旭辉集团股份有限公司 |
| 易宝支付 | 在用 | yeepay.jobs.feishu.cn/index | 易宝支付 | 加入易宝支付 |
| 星辉游戏 | 在用 | rastargame.jobs.feishu.cn/index | 星辉天拓 | 星辉游戏招聘 |
| 普源精电 | 在用 | rigolportal.jobs.feishu.cn/index | 普源精电 | 加入普源精电 |
| 智元机器人 AGIBot | 在用 | agirobot.jobs.feishu.cn/index | 智元创新（上海）科技股份有限公司 | 欢迎加入智元AGIBOT！ |
| 智谱AI Zhipu | 在用 | zhipu-ai.jobs.feishu.cn/index | 北京智谱华章科技股份有限公司 | 加入北京智谱华章科技有限公司 |
| 极兔速递 | 在用 | jtexpress.jobs.feishu.cn/index | 极兔速递 | 加入极兔速递 |
| 极致游戏 | 在用 | jzyxgames.jobs.feishu.cn/index | 厦门极致互动网络技术股份有限公司 | 极致游戏社招 |
| 极致游戏 | 在用 | jzyxgames.jobs.feishu.cn/campus | 厦门极致互动网络技术股份有限公司 | 极致游戏社招 |
| 梅花集团 | 在用 | j8fq0c3gg7.jobs.feishu.cn/index | 梅花生物科技集团股份有限公司 | 梅花集团-社会招聘 |
| 欢乐互娱 | 在用 | huanle.jobs.feishu.cn/campus | 欢乐互娱 | 欢乐互娱 |
| 欢乐互娱 | 在用 | huanle.jobs.feishu.cn/index | 欢乐互娱 | 欢乐互娱 |
| 歌尔丹拿 | 在用 | k13pqewe7i.jobs.feishu.cn/index | 歌尔丹拿 | 加入歌尔丹拿 |
| 正浩创新 EcoFlow | 在用 | ecoflow.jobs.feishu.cn/index | EcoFlow | EcoFlow 正浩创新 ｜ 社会招聘 |
| 水滴 | 在用 | wdh.jobs.feishu.cn/index | 水滴公司 | 加入水滴公司 |
| 永卓控股 | 在用 | everrising.jobs.feishu.cn/index | 永卓控股有限公司 | 永卓控股社会招聘 |
| 沐瞳科技 | 在用 | moonton.jobs.feishu.cn/index | 沐瞳科技 | 加入沐瞳科技 |
| 沐瞳科技 | 在用 | moonton.jobs.feishu.cn/campus | 沐瞳科技 | 加入沐瞳科技 |
| 波克城市 | 在用 | boke.jobs.feishu.cn/index | 波克科技集团 | 加入波克 |
| 洋葱学园 | 在用 | guanghe.jobs.feishu.cn/index | 洋葱学园 | 一起做教育的梦想家和冒险家 |
| 海亮集团 | 在用 | hailiang.jobs.feishu.cn/index | 海亮集团有限公司 | 加入海亮集团有限公司 |
| 海亮集团 | 在用 | hailiang.jobs.feishu.cn/campus | 海亮集团有限公司 | 加入海亮集团有限公司 |
| 海底捞 | 在用 | haidilao.jobs.feishu.cn/index | 海底捞 | 加入海底捞 |
| 深圳自变量机器人 | 在用 | x2-robot.jobs.feishu.cn/index | 自变量机器人科技（深圳）有限公司 | 加入自变量机器人 ｜ 社会招聘 |
| 深言科技 Deeplang | 在用 | deeplang.jobs.feishu.cn/index | DeepLang | 加入深言 |
| 爱奇艺股份有限公司 | 在用 | iq.jobs.feishu.cn/campus | 爱奇艺 | 爱奇艺社招 |
| 爱奇艺股份有限公司 | 在用 | iq.jobs.feishu.cn/index | 爱奇艺 | 爱奇艺社招 |
| 爱奇艺股份有限公司 | 在用 | iq.jobs.feishu.cn/internship | 爱奇艺 | 爱奇艺社招 |
| 物美科技集团 | 在用 | wumart.jobs.feishu.cn/index | Wumart | 加入北京物美商业集团股份有限公司 |
| 理想汽车 Li Auto | 在用 | li.jobs.feishu.cn/index | 理想汽车 | 加入理想汽车 |
| 生数科技 | 在用 | shengshu.jobs.feishu.cn/index | 生数科技 | 欢迎加入生数科技 |
| 知存科技 | 在用 | iucylxooqp.jobs.feishu.cn/index | 知存科技 | 加入知存科技 |
| 禾赛科技 | 在用 | kwh0jtf778.jobs.feishu.cn/index | 上海禾赛科技有限公司 | 禾赛科技社会招聘职位 |
| 网眼科技 | 在用 | webeye.jobs.feishu.cn/index | WebEye网眼集团 | 加入WebEye |
| 美图公司 | 在用 | meitu.jobs.feishu.cn/index | 美图公司 | 加入Pixocial 像素互联 |
| 美宜佳 | 在用 | meiyijia.jobs.feishu.cn/campus | 美宜佳控股有限公司 | 加入美宜佳控股有限公司 |
| 美宜佳 | 在用 | meiyijia.jobs.feishu.cn/index | 美宜佳控股有限公司 | 加入美宜佳控股有限公司 |
| 老虎国际 Tiger Brokers | 在用 | tigertech.jobs.feishu.cn/index | 老虎国际 | 加入老虎国际 |
| 脉脉 | 在用 | maimai.jobs.feishu.cn/campus | 脉脉 | 加入脉脉 |
| 脉脉 | 在用 | maimai.jobs.feishu.cn/index | 脉脉 | 加入脉脉 |
| 自如 | 在用 | ziroom.jobs.feishu.cn/index | 北京自如信息科技有限公司 | 加入北京自如信息科技有限公司 |
| 舒客电商 | 在用 | tianzhulingshan.jobs.feishu.cn/index | 天竺灵山 | 加入舒客电商 |
| 芯耀辉科技 | 在用 | geg7eg8cyc.jobs.feishu.cn/index | 芯耀辉 | 加入芯耀辉科技有限公司 |
| 莉莉丝游戏 Lilith | 在用 | lilithgames.jobs.feishu.cn/index | 莉莉丝 | 莉莉丝社会招聘 |
| 莉莉丝游戏 Lilith | 在用 | lilithgames.jobs.feishu.cn/campus | 莉莉丝 | 莉莉丝社会招聘 |
| 蔚来 | 在用 | nio.jobs.feishu.cn/campus | NIO | NIO蔚来-社会招聘 |
| 蔚来 | 在用 | nio.jobs.feishu.cn/index | NIO | NIO蔚来-社会招聘 |
| 超级猩猩（深圳）健康管理有限公司 | 在用 | supermonkey.jobs.feishu.cn/index | 深圳市超级猩猩健身管理有限公司 | 加入SUPERMONKEY超级猩猩 |
| 轻舟智航科技有限公司 | 在用 | qcraft.jobs.feishu.cn/campus | 轻舟智航QCraft | 加入轻舟智航QCraft |
| 轻舟智航科技有限公司 | 在用 | qcraft.jobs.feishu.cn/index | 轻舟智航QCraft | 加入轻舟智航QCraft |
| 量派投资 | 在用 | jo0ikgajg1.jobs.feishu.cn/index | 上海量派投资管理有限公司 | 加入上海量派投资管理有限公司 |
| 零一万物 01AI | 在用 | 01ai.jobs.feishu.cn/index | 零一万物 | 加入零一万物AGI |
| 霸王茶姬（北京）餐饮管理有限公司 | 在用 | chagee.jobs.feishu.cn/campus | 霸王茶姬 | 欢迎加入霸王茶姬 |
| 霸王茶姬（北京）餐饮管理有限公司 | 在用 | chagee.jobs.feishu.cn/index | 霸王茶姬 | 欢迎加入霸王茶姬 |
| 面壁智能 | 在用 | modelbest.jobs.feishu.cn/index | 面壁智能 | 加入面壁智能 |
| 面壁智能 | 在用 | modelbest.jobs.feishu.cn/campus | 面壁智能 | 加入面壁智能 |
| 鹰角网络 Hypergryph | 在用 | hypergryph.jobs.feishu.cn/index | 鹰角 | 加入鹰角 |
| 麦瑞克科技（广东）有限公司 | 在用 | merach.jobs.feishu.cn/index | 浙江麦瑞克科技有限公司 | 加入麦瑞克 |
| 小马智行 | 停用 | ponyai.jobs.feishu.cn/index | 小马智行 | 小马智行Pony.ai 招聘 |
| 影石 Insta360 | 停用 | arashivision.jobs.feishu.cn/index | 影石创新科技股份有限公司 | Join Insta360! |
