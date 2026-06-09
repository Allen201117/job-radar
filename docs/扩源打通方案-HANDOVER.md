# 求职雷达 · 扩源打通方案 HANDOVER

> 本文是「把各公司岗位爬取通道一家家打通」的完整作战方案，供任何接手的 agent 直接照做。
> 读完本文 + `CLAUDE.md` 即可独立推进，无需上下文。

---

## 🔥 接手即用：当前进度 + 立即可做的 backlog（每次更新）

**已新增能力（本系列会话）**：
- `oracle` 适配器（外企自建门户主力，§4①已落地）。
- `feishu` 飞书招聘**泛化**适配器（国内版 Workday，加一家=填一行 `{tenant}.jobs.feishu.cn/index/position`）。
- `beisen` 北森**三大根因修复（migration 062 起，已让北森一探一个准）**：
  1. **详情路由发现去抖**：`_discover_detail_route` 原用 `networkidle`，但北森 SPA 持续轮询（tara-frontend 日志/AI 机器人）→ networkidle 永不静默 → 30s 超时被外层 except 吞成 `None`（NO-DETAIL-ROUTE）。改 `domcontentloaded`。**这才是「C 型打不通」的真因，不是 SSR**。
  2. **取真岗位探测**：`intercept_matches` 含 `"/api/"` 宽匹配会混入搜索条件/地区树/推荐岗，`posts[0]` 常非真岗位（无 JobAdName/Id）→ 探测必失败。改优先取首个有 `JobAdName` 的真岗位。
  3. **render-verify 加主标题强信号**（`_is_job_detail`）：详情页侧栏「推荐职位」露出他岗时不再误判为列表页。
- `beisen` **C 型老版 SSR 解析器**（`_fetch_ssr`）：真无 `GetJobAdPageList` 时（如中核），渲染列表页 HTML → 抽 `a[href*=jobId=]` 锚点 → render-verify 探详情路径（中核=`/szxq?jobId=`、复星=`/campusxq?jobId=`）→ 拼 jd_url。
- `beisen` 老版 SSR 锚点已支持 `adId/jobAdId` 的完整参数值（数字或 GUID），不再只截数字；BOE `social2021` 已 live 打通。
- `feishu` 泛化适配器已支持自定义 portal slug（如 `/{portal}/position/{id}/detail`），不再只拼 `/index/position/{id}/detail`；Pony.ai `/ponyai`、Momenta `/talent` 已 live 打通。
- `hotjob` / wecruit 通用适配器已新增（`wecruit.hotjob.cn/{suiteKey}/pb/{social|school|interns}.html` → 拦截 `positionInfo/listPosition` → `posDetail.html?postId=...&postType=...`）；TCL 社招/校招/实习，以及云南白药/华夏银行/华润电力/先声药业/领益智造/上海宝冶/中煤矿建/润华汽车/华润三九/宜人智科/瑞金医院/开源证券/中国铁建高新装备/招商证券/南京高速齿轮/北京联东/国投证券/华泰证券/广州市规划院/顶点软件/永青集团/海兴电力/迪卡侬中国已 live 打通。
- **🐞 修了致命 bug**：`ChinaSpaAdapter.fetch` 原 `if not self.list_urls` 绑定，但 beisen/company_spa 实例在 run.py/probe.py 是**共享单例**→ 首个源 URL 粘住→后续源全抓首个源→**B 公司入了 A 公司岗位（jd_url 指向 A host）**。改每次绑定当前 source_url。**扩多个北森源前必须有此修复**。

**🗂️ 北森详情路由已落盘**：`crawler/beisen_routes.json`（host→详情 base 字符串/SSR dict `{ssr_path,ssr_param}`）。探到的新路由记得加进去，每日 cron 免重探、避反爬。

**🔎 北森扩源 SOP（一探一个准，本系列已入 15 家）**：
1. zhiye.com **对任意子域都回 HTTP 200**（通配），不能靠 200 判存在 → 必须看**门户 `<title>`**：真租户标题是公司名/「社会招聘」，不存在的返回 `title='Not Found'`。
2. 候选 host = 公司英文/拼音 slug + `.zhiye.com`，先批量抓 title 过滤（脚本思路见会话 `/tmp/verify_beisen_titles.py`），**只保留 title 命中公司名的**（防张冠李戴，handover 曾把 `coamc`=中国东方资产 误标中国信达）。
3. 过滤后跑 `BeisenAdapter` 确认出岗 + 抽样 jd_url，再 `probe.py --all --candidates ... --emit 0NN`。

**🚀 高 ROI 扩源最有效打法 = WebSearch 取真实 URL/slug（远胜盲猜）**：
- **Moka 必须搜**：`app.mokahr.com/{apply|campus_apply}/{tenant}/{orgId}` 的 orgId 不可猜 → WebSearch `app.mokahr.com/apply 社会招聘 <行业>` 直接出带 orgId 的真实 URL，命中率高（本系列 Moka 入 14 家全靠搜）。腾讯系用 `app-tc.mokahr.com`。
- **飞书 slug 要搜准**：盲猜常错（莉莉丝 `lilith`✗→`lilithgames`✓、米哈游不在飞书=自建 jobs.mihoyo.com）；且**批量连打触发反爬**，务必小批(≤5)。
- **北森 slug**：`<公司> zhiye.com` 搜，或 `zhiye.com 社会招聘 <行业>`；zhiye 通配 200，靠 title≠`Not Found` 判真伪。
- 老 SSR/项目入口（BOE social2021、启德 eic `/social?r=`、中国船舶 cssc 网申、cscec 考试入口）= 非标准锚点，留专项。

**本系列已入（live 探活，migration 062–072，北森 33 + Moka 14 + 飞书 4 = 51 家）**：
- 北森 soe 国企央企：中核 cnnc / 深业 shenyejituan / 中国东方资产 coamc / 上实 siic / 江淮 jac / 江铃 jmc。
- 北森 私企新版（`?jobAdId={GUID}`）：公牛 / 360 / 联影 united-imaging / 蒙牛 / 大华 dahua / 奇瑞 chery / 药明康德 wuxiapptec / 通威 tongwei / 卓胜微 maxscend / 传音 transsion / 零跑 leapmotor / 欣旺达 sunwoda / 国轩 gotion / 双汇 shuanghui / 周大福 ctf / 科大讯飞 iflytek / 维达 vinda / 东鹏 dongpeng / 东山精密 dsbj / 蜂巢能源 svolt / 新东方 xdf / 先导智能 leadchina / 博众精工 bozhon。
- 北森 C 型 SSR：中核 cnnc(`szxq`) / 复星医药 fosunpharma(`campusxq`)。
- 北森 old-SSR/2021：BOE 京东方 boe(`zwxq`)。
- 飞书：零一万物 01ai / 鹰角 hypergryph / 小马智行 ponyai(`/ponyai`) / Momenta(`/talent`)。
- HotJob/wecruit：TCL 社招/校招/实习（`wecruit.hotjob.cn/SU64893571.../pb/{social,school,interns}.html`）；云南白药社招、华夏银行校招、华润电力社招、先声药业校招、领益智造校招、上海宝冶校招、中煤矿建校招、润华汽车校招（migration 072）；华润三九校招、宜人智科校招、上海瑞金医院社招、开源证券校招、中国铁建高新装备社招、招商证券校招、南京高速齿轮社招/校招/实习（migration 073）；北京联东校招、国投证券校招、华泰证券社招、广州市规划院校招、顶点软件校招、永青集团校招、海兴电力校招、迪卡侬中国校招（migration 074）。
- 北森详情路由已落 `beisen_routes.json`（38 条）。北森 slug-sweep 命中率约 12–18%（多数大国企/互联网不在北森，返回 `Not Found`）。

**⚠️ 飞书批量 sweep 会触发反爬**：连打 ~34 个 `{tenant}.jobs.feishu.cn` 后大面积 `anti_bot_blocked`（deepseek/mihoyo/weride 等真租户被误杀）。正解=**小批 + 间隔**重探（每批 ≤5、隔几分钟），或单家慢探。已确认存在但被反爬挡的真飞书租户值得换干净会话重试。

**🔨 仍待做（按价值）**：
0. **北森老校招异构 SSR**（`details2021?adId={GUID}` 类，**非数字 jobId**）：BOE `boe.zhiye.com` 已打通（migration 068）；中国建筑 `cscec.zhiye.com` 当前真租户页有标题，但 `/campus` 未拦到岗位 JSON、未暴露 `jobId/adId` 逐岗锚点，暂不入库，需继续定位真实岗位接口/可深链详情。
1. **北森 B 型（筛选优先）**：`vivo.zhiye.com`(拦到 JSON 但 0 岗)、新东方 `xdf.zhiye.com`。默认空筛选器，要程序化选首个地点/类型项再触发搜索，**且只对 B 型生效（A 型点搜索会清空列表，勿误伤）**。脆弱、优先级最低。
2. **飞书非标准 portal 入口**：小马智行 `ponyai.jobs.feishu.cn/ponyai`、Momenta `momenta.jobs.feishu.cn/talent` 已打通（migration 069）；月之暗面 `moonshot.jobs.feishu.cn/social` 当前可触发岗位 API 但页面显示 0 职位，暂不入库。后续遇到 `{tenant}.jobs.feishu.cn/{portal}` 可直接用通用 `feishu` adapter。
3. **大易 dayee.com 适配器**：隆基/TCL/比亚迪等。已复核：TCL 实际落 HotJob/wecruit，已用 `hotjob` 打通社招/校招/实习；隆基官网 career 当前只是品牌页，未定位到公开岗位 JSON；比亚迪为自建 `job.byd.com` API，不是 Dayee。Dayee 仍需继续找真实客户招聘页后再建。
4. **自建大厂**（最硬，放最后）：⚠️ **美的 careers/recruit.midea.com 已验证不可行**——`recruit.midea.com/backend/rec/home/out/official/position/new` 是干净公开 GET（620 社招岗+完整 JD），**但 detail 页无公开稳定 jd_url**（ihr SPA 忽略 positionId 深链、`/position` 重定向 `/index`、疑登录墙）→ 按 #1 铁律不能入。**自建巨头务必先验证「详情页是否公开可深链」再投入**（深链不了=没有合格 jd_url=不做）。华为 reccampportal、比亚迪 job.byd.com(hash-SPA) 待逐家验证详情页可深链性。

**2026-06-08 本轮 HotJob 续扩（migration 072）**：
- 通过并已 emit：云南白药社招 `valid=48/在华=7`，华夏银行校招 `valid=3/在华=2`，华润电力社招 `valid=60/在华=34`，先声药业校招 `valid=60/在华=40`，领益智造校招 `valid=38/在华=22`，上海宝冶校招 `valid=14/在华=9`，中煤矿建校招 `valid=48/在华=15`，润华汽车校招 `valid=4/在华=4`。
- 详情页抽样已逐个用 Playwright 打开验证：样本 `posDetail.html?postId=...&postType={society|campus}` 均渲染具体岗位标题/JD，不是加载页或列表页。
- 未入库：华夏幸福 `SU641d3c5a.../pb/school.html` 本次 probe 未通过（无 valid 输出/未写入迁移），后续若要做需单独定位真实项目参数或有效入口。

**2026-06-08 本轮 HotJob 续扩（migration 073）**：
- 通过并已 emit：华润三九校招 `valid=41/在华=32`，宜人智科校招 `valid=10/在华=10`，上海瑞金医院社招 `valid=29/在华=29`，开源证券校招 `valid=1/在华=1`，中国铁建高新装备社招 `valid=5`（本土源按 `valid>0` 入），招商证券校招 `valid=13/在华=10`，南京高速齿轮社招 `valid=23/在华=19`、校招 `valid=5/在华=3`、实习 `valid=1/在华=1`。
- 详情页抽样已逐个用 Playwright 打开验证：`postType=society/campus/intern` 均渲染具体岗位标题/JD；南高齿实习样本 `postType=intern` 不再卡加载页。

**2026-06-08 本轮 HotJob 续扩（migration 074）**：
- 通过并已 emit：北京联东投资集团校招 `valid=2/在华=2`，国投证券校招 `valid=3/在华=3`，华泰证券社招 `valid=60/在华=59`，广州市规划院校招 `valid=10/在华=10`，顶点软件校招 `valid=7/在华=5`，永青集团校招 `valid=22`（岗位地点含印度尼西亚，本土源按 `valid>0` 入），海兴电力校招 `valid=3/在华=3`，迪卡侬中国校招 `valid=60/在华=34`。
- 详情页抽样已逐个用 Playwright 打开验证：样本均渲染具体岗位标题/JD，且公司/导航文本与候选归属一致；华泰证券社招、迪卡侬中国校招等大源均不是加载页或列表页。
- 未入库：海光信息 `SU66a9aaa5.../pb/school.html`、新毅东 `SU67a415fc.../pb/school.html`、西南证券 `SU61d3efea.../pb/school.html` 本次 probe 未通过（无 valid 输出/未写入迁移），后续需重新定位有效入口或确认是否已下线/空岗。

**已 live 验证打通（往期）**：外企 Oracle(Emerson/霍尼韦尔/美国运通/纽约梅隆)；国内飞书(理想/得物/深言/道旅/智谱/MiniMax/元气森林/MetaApp/VAST/智元机器人/影石/xTool/安克/懂车帝)、Moka(完美世界/远景/搜狐畅游/作业帮/知乎/猿辅导/文远知行/唯品会)、北森(泡泡玛特/迈瑞/汇川/长安/名创)。

---

## 0. 一句话目标 & 铁律

**目标**：为每家公司打通一条**可靠的 per-job `jd_url` 抓取通道**（能稳定拿到该公司逐个岗位的官方详情链接）。
**不是**一次爬光一家所有岗位——通道通了，每日 cron 自然持续供给。

**三条铁律**（违反即残次品，详见 `CLAUDE.md` 核心产品原则）：
1. 精准路由：按用户筛选项/偏好定向抓，不乱爬。
2. 偏好收窄：默认按 `candidate_profiles` + `user_preferences` 收窄。
3. 持续扩源：覆盖面是硬指标，本文就是扩源主线。

**质量门**（每条新通道必过，否则不入库）：
- `jd_url` 准确性 **高于一切**：必须是稳定的逐岗详情页，禁止首页/搜索页/导航页/登录页。
- **china-gate**：外企 ATS 必须有真实在华岗（`is_china_location`）>0 才入库；本土 adapter 按构造即在华，`valid>0` 即可。
- **去重**：按 `jd_url` 去重（Workday 大租户翻页会重复，见 §4 坑）。

---

## 1. 核心打法：平台聚类，不逐家啃

**关键洞察**：大公司（无论外企还是国内 500 强）都**扎堆在少数几个 HR 招聘平台上**。
所以正确做法不是一家家写适配器，而是：

> **给每个平台写 1 个半通用适配器 → 一把解锁一批公司。新增一家公司 = 找到它在该平台的端点 → live 探活 → 在 `sources` 表加一行。**

这就是外企已经跑通的模式（一个 `workday` 适配器覆盖 90+ 家），国内要平行复制这套。

---

## 2. 现状快照（接手时核对 `crawler/coverage.py`）

- **148 条通道**：外企 114 / 国内私企 32 / 国企央企 2。
- 已有适配器（`crawler/adapters/` + `crawler/run.py` 的 `ADAPTERS`）：

| 适配器 | 平台 | 体系 | 机制 | 状态 |
|---|---|---|---|---|
| `workday` | Workday CXS API | 外企 | httpx + location facet 服务端过滤 | ✅ 成熟（主力，90+家） |
| `eightfold` | eightfold.ai | 外企 | httpx 公开 JSON + location | ✅ |
| `greenhouse`/`lever`/`ashby`/`smartrecruiters` | 同名 ATS | 外企 | httpx slug 化公开 API | ✅ |
| `apple`/`apple_cn`/`siemens` | 自建 | 外企 | 专用 | ✅ |
| `moka` | Moka mokahr.com | 国内私企 | **playwright 渲染 DOM**（API 加密） | ✅（15+家） |
| `beisen` | 北森 zhiye.com | 国内/国企 | playwright 拦截 JSON | ✅ 新版模板；⚠️老版 SSR 待做 |
| `feishu` / `*_feishu` | 飞书招聘 | 国内私企 | playwright 拦截 `/api/v1/search/job/posts` | ✅ 通用层支持标准 `/index/position` 与自定义 portal |
| `hotjob` | HotJob / wecruit | 国内私企 | playwright 拦截 `/wecruit/positionInfo/listPosition/` | ✅ TCL 社招/校招/实习已验证；详情页必须带正确 `postType` |
| `bytedance`/`tencent`/`baidu`/`jd`/`haier` | 各自官网 SPA | 国内私企 | playwright/专用 | ✅ |
| `company_spa` | 通用自建站 | 国内/国企 | playwright 拦截站点 JSON | ✅（逐家） |

`run.py` 的 `DOMESTIC_ADAPTERS` 集合标记哪些是本土源（每日 cron 优先抓）。

---

## 3. 工具与工作流（接手必读，照此操作）

### 3.1 探活器 `crawler/probe.py`（打通通道的核心管线）
```bash
cd crawler
set -a; source ../.env.local; set +a          # 载入 Supabase 凭证（绝不打印/提交）

# A) 定向探活：手写候选 JSON → 只把 live 验证有在华岗的写迁移
python3 probe.py --candidates /tmp/candXXX.json --emit 0NN

# B) 发现模式：对内置公司名 × ATS × slug 自动猜+验证（greenhouse/lever/ashby/SR/eightfold）
python3 probe.py --discover --emit 0NN
```
候选 JSON 格式（每条一家）：
```json
[{"company":"英特尔 Intel","adapter":"workday","industry":"半导体",
  "url":"https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs"}]
```
- `url` 各 adapter 的格式见 §4/§5。
- probe 自动过 china-gate + 质量门 + 去重，**只把通过的 emit 成迁移**，未通过自动丢弃（符合「禁止猜 slug 入库」）。
- **本机跑，且 live 网络调用要加 `dangerouslyDisableSandbox: true`**（沙箱默认断网）。

### 3.2 覆盖度报告 `crawler/coverage.py`
```bash
cd crawler; set -a; source ../.env.local; set +a; python3 coverage.py
```
按 segment(外企/私企/国企) × 行业 统计已打通通道数。

### 3.3 迁移 = 全自动，零手动 SQL
- 新迁移放 `supabase/migrations/0NN_xxx.sql`，前缀递增。
- `git push` 到 main → GitHub Actions（`.github/workflows/migrate.yml`）自动 apply 到生产库。
- **绝不再手动进 Supabase 跑 SQL。**

### 3.4 提交规范
- 用户说「提交/commit」→ 自动 commit + push 到 origin/main，无需再确认。
- commit message 结尾加：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 改了 adapter 代码 → 跑回归：`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`。

### 3.5 找端点的搜索话术（WebSearch）
- Workday：`"<公司> careers myworkdayjobs.com"` → 取 `{tenant}.wd{N}.myworkdayjobs.com/{site}`。
- Eightfold：`"<公司> careers eightfold"` → `{tenant}.eightfold.ai`。
- Oracle：`"<公司> careers oraclecloud"` 或看 careers 页跳转 → `{tenant}.fa.{region}.oraclecloud.com` + `siteNumber=CX_xxxx`。
- Moka：`"<公司> mokahr.com 招聘"` → `app.mokahr.com/...` 或 `{tenant}.mokahr.com`。
- 北森：`"<公司> zhiye.com 招聘"` → `{tenant}.zhiye.com/...`。
- 飞书：`"<公司> jobs.feishu.cn"` → `{tenant}.jobs.feishu.cn`。

---

## 4. 外企体系方案（按平台）

外企共通性最强：补一个通用 ATS 适配器就解锁一批。**优先级 = 覆盖面 × 可行性。**

### ✅ 已成熟（直接加候选 probe 即可扩）
| 平台 | url 格式（候选 JSON 的 `url`） | 备注 |
|---|---|---|
| workday | `https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` | site/wd 号必须搜来，不可猜 |
| eightfold | `https://{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}` | 部分有 403 反爬 |
| greenhouse | slug 化，见 probe.py `_ATS_URL` | discover 可自动猜 |
| lever/ashby/smartrecruiters | 同上 | discover 可自动猜 |

**Workday 适配器关键逻辑（已修，接手须知）**：
- Workday 的 `total` 字段**极不可靠**（报 180 实际能翻 600+），**不要用它选 facet 或比较**。
- 已实现：所有大中华区 facet 组**各自翻页后并集去重**（可信全收）；facet 取到 <25 条（嵌套/截断场景，如 GE医疗只露香港漏上海）才用 `searchText=China/Hong Kong/Macau` 文本补充，parse 按 `is_china_location` 严格过滤。
- `is_china_location`（`normalizer.py`）已兼容 `China`/城市/`Hong, Kong`(逗号)/`CHN`/`CN` 等格式，且词边界防 `macao→Humacao` 误判。

### 🔨 待建（高优，每个解锁一大批自建巨头）

#### ① Oracle 招聘云 Recruiting（**已 live 验证可行，最高优**）
- **覆盖**：霍尼韦尔、美国运通、诺基亚、纽约梅隆、Akamai、Emerson、NetApp 等大批「自建」巨头其实都是 Oracle HCM。
- **已验证**：`https://hdjq.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&limit=N&finder=findReqs;siteNumber=CX_1001` → HTTP 200 JSON，Emerson 返 800+ 岗。
- **技术规格**（照 workday 模式建 `adapters/oracle.py`）：
  - 响应 `items[0].locationsFacet` = 扁平地点列表 `[{Id, Name:"China"/"Shanghai, China"/..., TotalCount}]`。找 Name 含 China/Hong Kong/Macau（排除 Taiwan）的 `Id`。
  - 过滤：`finder=findReqs;siteNumber={site},selectedLocationsFacet={Id}`；翻页 `,offset=N,limit=20` 或响应里的 `Offset/Limit`。
  - 岗位列表在 `requisitionList`（需正确 finder/limit 才填充）；字段 `Id`/`Title`/`PrimaryLocation`。
  - **jd_url** = `https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}`（live 验证渲染对应岗）。
  - **host+site 发现**：访问公司 careers 页会跳转到 `{tenant}.fa.{region}.oraclecloud.com`；`siteNumber` 在页面 JS config 或 URL（CX_1/CX_1001/CX_2…，探活试几个取岗位最多的）。
- onboard：`{"company":..,"adapter":"oracle","url":"https://{host}/hcmRestApi/.../recruitingCEJobRequisitions?finder=findReqs;siteNumber={site}"}` → probe。

#### ② Phenom People（中优）
- **覆盖**：高露洁、康宁、达能、嘉吉、英飞凌、Lam Research、Zimmer Biomet、辉门等（careers/jobs.{公司}.com 自建域名，Phenom 承载）。
- **待定位接口**：Phenom 通常有 `/api/...` 或 `widgets` JSON 搜索端点（POST 带 facets）；先用浏览器/抓包定位一家（如 jobs.colgate.com）的真实 JSON 端点，再建 `adapters/phenom.py`。
- 验证状态：⚠️ 我试的 `/api/jobs` 猜测端点返 HTML，需进一步定位真实路径。

#### ③ 大厂独立系统（单价高，逐个做，公开 JSON API）
- **微软** `careers.microsoft.com`：公开 API `gcsservices.careers.microsoft.com/search/api/v1/search?lc=China...`。
- **亚马逊** `amazon.jobs`：`/search.json?normalized_country_code[]=CN&...`。
- **谷歌** `careers.google.com`：`/api/v3/search/?location=China...`。
- 各写一个小适配器即可（China 过滤都是原生参数），是冲外企 100 强尾部的关键。

#### ④ SAP SuccessFactors（最难，放最后）
- **覆盖**：阿迪达斯、雀巢、ABB、施耐德、大陆集团、汉高、勃林格、Schindler。
- 多为自建 CMS/OData，常要鉴权或每家结构不同（巴斯夫=自建 CMS、西门子=Avature，已知是深坑）。**性价比最低，最后再碰。**

---

## 5. 国内体系方案（按平台）— 与外企平行的一套

国内 500 强同样扎堆在少数本土 HR SaaS + 自建站。**主攻方向 = 把这些平台适配器做全。**

### ✅ 已有（继续加候选扩）
| 平台 | 覆盖 | url 格式 | 机制/状态 |
|---|---|---|---|
| Moka `mokahr.com` | 消费/互联网/游戏/制造私企（SHEIN/Shopee/宁德/携程/虎牙/高途/WPS/雪球/好未来…） | `https://app.mokahr.com/{apply\|campus_apply\|...}/{tenant}/{id}` 或 `{tenant}.mokahr.com/...` | **playwright 渲染 DOM**（list API 加密 `necromancer`），jd_url=`{base}#/job/{uuid}` |
| 北森 `zhiye.com` | 大型国企/集团（中国人寿/三一/潍柴/横店…） | `https://{tenant}.zhiye.com/...` | playwright 拦截 JSON（**新版**模板） |
| 飞书招聘 `jobs.feishu.cn` | 造车新势力/科技（蔚来/小鹏/地平线/小米…字节系） | `https://{tenant}.jobs.feishu.cn/...` | playwright 拦截 `/api/v1/search/job/posts` |
| HotJob `wecruit.hotjob.cn` | TCL 等本土集团 | `https://wecruit.hotjob.cn/{suiteKey}/pb/{social|school|interns}.html` | playwright 拦截 `positionInfo/listPosition`，详情页 `postType=society/campus/intern` |
| company_spa / 各官网 | BAT/京东/海尔 | 各自 | 逐家 |

### 🔨 待建（高优 backlog）

#### ① 飞书招聘**泛化**（**最高优，国内版 Workday**）
- 现状：`adapters/feishu.py` 的 `FeishuRecruitAdapter` 是 base，但 nio/xpeng/horizon/xiaomi 各硬编码 `host`+`company_name` 子类。
- 改造：建一个**数据驱动的 `feishu` 通用适配器**——`host` 从 `source_url` 解析（如 `https://{tenant}.jobs.feishu.cn`），不再每家一个子类。拦截逻辑/字段映射（`/api/v1/search/job/posts` → `id/title/city_info/job_category`，jd_url=`https://{host}/index/position/{id}/detail`）已现成。
- 收益：一把覆盖所有用飞书招聘的公司（理想/众多互联网与科技中企）。onboard = 加一行 sources 填 `{tenant}.jobs.feishu.cn`。

#### ② 北森**老版 SSR**（中优，解锁一批国企）
- BOE京东方/中车/航天等用老版北森模板（`social2021`/`details2021`/`campusxq`，服务端渲染、无 JSON 可拦截，现 `beisen` 抓不到）。
- 改造：给 `BeisenAdapter` 加「playwright 渲染列表页 → selectolax 解析岗位卡 → 详情链接按 `?adId=`/`?jobId=`+数字 id 拼装并 render 验证」路径。同模板一通则解锁一批。

#### ③ 大易 `dayee.com`（待验证）
- 部分 500 强用大易 ATS。先定位 1-2 家已知用户的公开招聘页 + JSON 接口，验证可行后建 `adapters/dayee.py`。

#### ④ Workday 中国租户（低成本，复用现有）
- 联想等国际化中企用 Workday → 直接用现有 `workday` 适配器加候选即可（segment 标 `private`）。

#### ⑤ 自建大厂 / 国央企（逐家，最硬）
- 华为 `career.huawei.com`、阿里 `talent.alibaba.com`、美的/比亚迪/格力官网、工行/中石化/国家电网门户 → 多为自建 SPA/SSR。用 `company_spa` 拦截站点 JSON 逐家打通；SSR 的复用 §5②的渲染解析路径。
- **国央企最难**（自建门户多、结构各异），放最后；优先用北森老版能覆盖的那批。

### 国内平台识别速查（搜公司官网招聘页落地到哪个域名）
`mokahr.com`→moka｜`zhiye.com`/`italent.cn`→北森｜`jobs.feishu.cn`→飞书｜`wecruit.hotjob.cn`→hotjob｜`dayee.com`→大易｜`myworkdayjobs.com`→workday｜自有域名 SPA→company_spa。

---

## 6. 「打通一家」标准流程 SOP（外企/国内通用）

1. **定位平台**：WebSearch 公司招聘页，看落到哪个域名（§3.5 / §5 速查）。
2. **取端点**：按平台 url 格式拼出候选（site/slug/host 必须来自真实页面，**不猜**）。
3. **写候选 JSON**：`/tmp/candXXX.json`，带 `company/adapter/industry/url`。
4. **probe 探活**：`python3 probe.py --candidates ... --emit 0NN`（本机 + `dangerouslyDisableSandbox`）。
5. **只入库通过的**：probe 自动过 china-gate + 质量门 + 去重；失败的查死因（无在华岗？端点错？反爬？）。
6. **提交**：`git add 迁移 && commit && push` → 自动迁移生效。
7. **核对**：`coverage.py` 看通道数涨；样本 `jd_url` 浏览器能打开对应岗。

---

## 7. 优先级 Backlog（可直接领取执行）

**外企**（按收益排序）：
1. [ ] 建 `oracle` 适配器（规格见 §4①，已验证）→ probe 霍尼韦尔/美国运通/诺基亚/纽约梅隆/Akamai/Emerson。
2. [ ] 建 `phenom` 适配器 → 高露洁/康宁/达能/嘉吉/英飞凌/Lam/Zimmer。
3. [ ] 微软/亚马逊/谷歌 各自小适配器（公开 JSON，China 原生过滤）。
4. [ ] 继续 discover 收割 greenhouse/lever/ashby/SR/eightfold 尾部。
5. [ ] （最后）SuccessFactors 调研。

**国内**（按收益排序）：
1. [ ] **飞书招聘泛化**为数据驱动 `feishu` 适配器（§5①）→ 理想等一批飞书系公司。
2. [ ] 北森**老版 SSR** 渲染解析路径（§5②）→ BOE/中车/航天等国企一批。
3. [ ] 大易 `dayee` 继续验证真实客户页；TCL 已改走 HotJob，隆基/比亚迪本轮未证明 Dayee。
4. [ ] Moka/北森**新版**继续加候选（搜更多 mokahr.com/zhiye.com 用户）。
5. [ ] 自建大厂逐家 `company_spa`（华为/阿里/美的/比亚迪…）；国央企门户最后。

---

## 8. 关键约束与坑（血泪，务必遵守）

- **禁猜 slug/host 入库**：入库前提永远是 probe live 验证通过。
- **jd_url 质量门最高**：拿不到稳定逐岗链接的只记 `partial_success`，不标完整成功。
- **Workday `total` 字段不可信** + **必须按 jd_url 去重**（否则翻页重复灌岗，NVIDIA 曾虚标 500 实为 189）。
- **is_china_location**：latin 标记用词边界（防 `macao→Humacao`），已兼容逗号/连字符格式。改它必跑 `test_normalizer.py`。
- **沙箱断网**：所有 live 探活/网络验证本机跑 + `dangerouslyDisableSandbox: true`；端口监听/百度千帆 live 也受限。
- **不读/不打印/不提交** `.env*`、`SUPABASE_SERVICE_ROLE_KEY` 等密钥。
- **改 schema 必同步 migrations + 测试**；schema 以 migrations 为准。
- **build 与 dev 不同时**（会改写 `.next`）。
- **百度千帆**免费搜索每日 50 次，耗尽设 `BAIDU_QIANFAN_SEARCH_DISABLED=true`，别反复点发现。
- 改 adapter 代码后回归：`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`（当前 131 全绿）。

---

## 9. 关键文件索引

- 适配器：`crawler/adapters/{workday,eightfold,greenhouse,lever,ashby,smartrecruiters,china_ats,feishu,company_spa…}.py`
- 注册表：`crawler/run.py`（`ADAPTERS` + `DOMESTIC_ADAPTERS`）
- ATS 白名单（前端 admin 加源用）：`lib/source-adapters.ts`（须与 run.py 对齐）
- 探活器/覆盖度：`crawler/probe.py`、`crawler/coverage.py`
- 在华判定/质量门：`crawler/normalizer.py`（`is_china_location`、`validate_job_quality`）
- 迁移：`supabase/migrations/`（push 自动 apply）
- 测试：`crawler/test_*.py`
- 规范：根 `CLAUDE.md`（核心产品原则/数据质量/边界）

> 接手第一步：跑 `coverage.py` 核对现状 → 从 §7 backlog 顶部领一项 → 按 §6 SOP 执行。
