# 求职雷达 · 扩源打通方案 HANDOVER

> 本文是「把各公司岗位爬取通道一家家打通」的完整作战方案，供任何接手的 agent 直接照做。
> 读完本文 + `CLAUDE.md` 即可独立推进，无需上下文。

---

## 🔥 接手即用：当前进度 + 立即可做的 backlog（每次更新）

**已新增能力（本系列会话）**：
- `oracle` 适配器（外企自建门户主力，§4①已落地）。
- `feishu` 飞书招聘**泛化**适配器（国内版 Workday，加一家=填一行 `{tenant}.jobs.feishu.cn/index/position`）。
- `beisen` 北森**详情路由发现增强**（3500ms render-verify + 点击捕获兜底 + jobId/jobAdId×Id/JobAdId 双约定）。

**⚡ 立即可探活入库的已确认 host（搜索已确认真实，因 zhiye.com 单会话反爬限流未当场入库 —— 换干净会话/慢速重探即可，禁止未验证直接入库）**：
- 北森(beisen)：`miniso.zhiye.com`(名创优品) `gongniu.zhiye.com`(公牛) `360campus.zhiye.com`(360) `xdf.zhiye.com`(新东方) `cnnc.zhiye.com`(中核·央企) `shenyejituan.zhiye.com`(深业·国企) `coamc.zhiye.com`(中国信达·国企) `siic.zhiye.com`(上实·国企)。列表页试 `/campus/jobs`、`/social/jobs`、`/campus`；探活方式见 §6。央企国企记 `segment='soe'`。
- 飞书(feishu)：`/s/分享页`入口的（月之暗面 `moonshot`、小马智行 `ponyai`、Momenta `momenta`）—— 标准 `/index/position` 拦不到，需给 feishu 适配器补 `/s/` 入口处理（小代码项）。

**🧭 北森(zhiye) 租户三类（实测，决定能否当场打通）**：
- **A 自动加载型**（列表页直接出岗，`/social/jobs`或`/campus/jobs` 触发 `GetJobAdPageList`）：✅ 现适配器直接通。例：迈瑞/汇川/长安/名创/泡泡玛特/chinalife。新增=填列表URL探活（偶发时序失败，重试即可）。
- **B 筛选表单优先型**（默认页是空筛选器「请筛选工作地点及职位类型」，要先**选筛选项**才出 `GetJobAdPageList`）：⚠️当前抓不到。例：新东方(`xdf.zhiye.com/social`)。**注意：单纯点「搜索职位」按钮无效，且会把 A 型租户的已加载列表清空（实测把迈瑞 80→0）——已回退该尝试，勿重试**。正解：需 playwright 程序化「选一个地点/类型筛选项 → 再点搜索」，且只对 B 型生效（要先判断是否 A 型，避免破坏 A）。
- **C 真老版 SSR 型**（无 `GetJobAdPageList`，详情 `?jobId={数字}` + `details2021/overseadetail/szzwxq` 路径，根页无 job API）：⚠️需渲染 HTML 解析。例：公牛/中核/深业/信达/上实/BOE校招。
- 上面 §「立即可探活」里的 8 个 host 多属 B/C 型（名创=A 已收，其余待 B/C 专项）。

**🔨 待写代码的平台（高价值）**：
0. **北森 B 型（筛选优先）支持**：fetch 先检测列表是否自动出岗；若否且页面是筛选表单，则程序化选首个地点/类型项再触发搜索。务必不影响 A 型（A 型禁止点搜索）。
1. **大易 dayee.com 适配器**：隆基绿能(签约大易)、TCL、比亚迪(job.byd.com)、美的(careers.midea.com) 等 500 强用大易/自建门户。先抓包定位大易公开岗位 JSON 接口，建 `adapters/dayee.py`。
2. **北森老版 SSR / 异构**：联影(`united-imaging.zhiye.com` 无 GetJobAdPageList)、蒙牛(`mengniu.zhiye.com`)、BOE(校招 `boe.zhiye.com/details2021?adId=` 老版、社招已迁 `career.boe.com`)。需渲染 HTML 解析路径或 career.* 自建站走 company_spa。
3. **自建大厂 company_spa**：华为 career.huawei.com、阿里 talent.alibaba.com、比亚迪 job.byd.com、美的 careers.midea.com、OPPO careers.oppo.com、商汤 sensetime.com、哈啰 careers.hellobike.com 等（逐家）。

**已 live 验证打通（本系列）**：外企 Oracle(Emerson/霍尼韦尔/美国运通/纽约梅隆)；国内飞书(理想/得物/深言/道旅/智谱/MiniMax/元气森林/MetaApp/VAST/智元机器人/影石/xTool/安克/懂车帝)、Moka(完美世界/远景/搜狐畅游/作业帮/知乎/猿辅导/文远知行/唯品会)、北森(泡泡玛特/迈瑞/汇川/长安)。

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
| `*_feishu`（nio/xpeng/horizon/xiaomi） | 飞书招聘 | 国内私企 | playwright 拦截 `/api/v1/search/job/posts` | ✅ 但**每家硬编码子类**，待泛化 |
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
`mokahr.com`→moka｜`zhiye.com`/`italent.cn`→北森｜`jobs.feishu.cn`→飞书｜`dayee.com`→大易｜`myworkdayjobs.com`→workday｜自有域名 SPA→company_spa。

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
3. [ ] 大易 `dayee` 验证 + 建适配器（§5③）。
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
