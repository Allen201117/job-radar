# 模块细节备查（从 CLAUDE.md 拆出）

> ⚠️ **优先级：本文是「归档细节」，与 `CLAUDE.md` 冲突时一律以 `CLAUDE.md` 为准。**
> 红线看正文，这里只查数字、来由和个案；正文更新后本文可能滞后，别拿它推翻正文。

> 这里是**个案细节 / 实测数字 / 决策来由**，原文照搬未改一字。
> CLAUDE.md 正文只留「触发条件 + 不可越的红线 + 指到这里」。
> 读法：正文那条红线让你来查什么，就搜对应小节。


---

## 设计组件库（原 CLAUDE.md 全文，现精简为红线 + 指向 DESIGN.md）

### 设计组件库：新代码一律走 `@/components/ui`，别再手写（2026-09-04 立）

产品有自己的组件库了。**写任何前端之前先看一眼有没有现成的**，别再各写各的
——改造前 28 个文件各写各的 `<button>`、9 个各写各的转圈、6 个各写各的「锁滚动 + ESC」、
`inputCls` 同一串样式存在**三份**、全站 5 个弹层**一个焦点陷阱都没有**。

- **看长什么样**：`/design`（管理员可见）。那页的组件就是产品里真实跑的那一个、用同一份 CSS，
  所以它不会说谎。**完整用法与运维规矩见 `DESIGN.md` 的「组件库」一节**，决策来由见
  `docs/superpowers/specs/2026-09-04-design-system-component-library-design.md`。
- **现有 21 个**：`Button` · `Badge` · `Banner` · `Separator` · `Spinner` · `Progress` ·
  `EmptyState` · `Field`+`Input`+`Textarea`+`Select` · `Switch` · `Segmented` · `TagInput` ·
  `Tabs`+`TabPanel` · `Accordion` · `Stepper` · `Modal` · `Sheet`（底部抽屉可拖拽关闭）·
  `Popover` · `Tooltip` · `DropdownMenu` · `AlertDialog`（替掉 `window.confirm`）；
  hooks 在 `lib/ui/hooks.ts`（`useBodyScrollLock` / `useEscapeKey` / `useFocusTrap` /
  `useClickOutside` / `useAnchoredPosition` / `useClipboard` / `useAsyncAction`）。
- ⚠️ **动效一律走令牌，别写死毫秒和贝塞尔**：四条弹簧曲线 `--spring-{smooth,snappy,bouncy,press}`
  + 四档时长 `--dur-{press,toggle,panel,sheet}`。标杆是 iPhone —— iOS 动效的核心是**用弹簧
  不用贝塞尔**。曲线按 SwiftUI 的 `spring(response:dampingFraction:)` 方程解出来的，
  调手感改 `scripts/gen-spring-easing.py` 跑一次。按压反馈用 `.press-feedback`（scale 0.97，
  不是 0.9——0.9 会读成「这东西要被删掉了」）。契约测试会拦写死的时长与曲线。
- ⚠️ **只有 4 个组件用 Radix**（Tooltip/DropdownMenu/Tabs/Accordion），因为这四个自己写
  一定会漏（贴边翻转、首字母跳转、roving tabindex、aria-controls 配对）。视觉全是自己的皮肤。
  Switch/Sheet/AlertDialog/Progress/Separator/Stepper **刻意不用**——价值在手感，引依赖无收益。
- 🚫 **Tailwind UI 是商业授权**（很多人误以为开源）、**Aceternity** 禁止转售衍生品且风格冲突、
  **Magic UI / Motion Primitives** 要装 `motion` 包（已有 GSAP，不引第二个动画运行时）。
  抄 MIT 代码进仓库必须在 `LICENSES/` 留版权声明——那是 MIT 唯一的强制要求。
- ⚠️ **颜色一律用 `--tone-*` 令牌，不要再写 hex**：七族语义色（sky 社招 / green 校招·已核实 /
  amber 实习·转陈 / teal 招聘动态 / rose 失败·风险 / lilac 职业洞察 / neutral 不表态），
  写成 `text-tone-sky-fg` / `bg-tone-sky-bg` / `border-tone-sky-border`，明暗自动切换。
  **要加新颜色 → 先在 `globals.css` 定义变量（明暗各一套）+ `tailwind.config.js` 登记**，
  再用语义类名。`components/ui` 与 `lib/ui` 内出现 hex 会被契约测试判红。
- ⚠️ **变体表（cva）写在 `lib/ui/variants.ts` 这个 `.ts` 里，不要写进组件的 `.tsx`**：
  `tests/_load-ts.js` 只认 `.ts`，放对地方契约测试才能真的加载它做断言，而不是只能 grep 文本。
- ⚠️ **cva 只加尺寸轴，颜色继续由 `.btn-*` 等既有类提供**（靠 Tailwind 的
  components→utilities 层序覆盖 padding）。往变体表里抄颜色 = 制造第二份颜色定义，正是要消灭的东西。
- ⚠️ **可访问性做进原语，不靠调用方记得**：`Modal` 默认带焦点陷阱 + `role="dialog"` +
  `aria-modal` + 锁滚动 + ESC；`Segmented` 的 `ariaLabel` 是**必填 prop**。凡是「靠人记得写」
  的 aria 迟早会漏——改造前 4 处分段控件有 3 处漏了组标签。
- **废弃组件搬进 `components/ui/deprecated/` + 打 `@deprecated`，不要直接删**（学 GitHub Primer）。
  直接删 = 全站必须同一天跟着改完，几个人的团队做不到，结果就是没人敢改组件库。
- **存量迁移的节奏 = 新代码必须用库、老代码碰到再换**，不做一次性全站替换
  （`JobCard` 906 行 / `InsightsAdminClient` 1466 行这些巨型文件回归面太大）。
  ⚠️ **迁移的判据是「能不能证明像素不变」，不是「看起来差不多」**：只有亮暗成对出现在
  同一个类串里才换成令牌；只有亮色没有 `dark:` 的地方一律跳过（换了会让它在暗色下变色）。
  归并「差一点点」的同类颜色属于**有意的视觉改动**，要单独提出来由创始人拍板，不能顺手改掉。
- 契约测试 `tests/design-system-contract.test.js`（13 条）守着以上规矩，新增组件请顺手补断言。

---

## 中文地名词表：逐条选词理由与 live 对拍数字

### 🚫 中文地名不许用「含 省/市/区/县/自治州 → 中国」那条规则（2026-09-05 立）

同一个词表还有一半是**中文地名**：旧表的中文标记只有「中国」+21 个一线城市 ——
认得 `Changchun`，认不得「长春市」。live 实测 27.8 万个「中文地点 + 在招」的岗里 **8.3 万个
`country_code` 为空**，它们的国内外归属**完全押在 `sources.regions` 一个字段上**
（`derive_job_scope` 的「抽不出国家就问源」分支）。而海外扩展一直在放开源的 regions，
某个源哪天被加上 US，它名下这批岗就**静默**翻成 overseas —— 不报错，只是国内供给少一块。

⚠️ 修它时最诱人的写法是「地点含 省/市/区/县/自治州 → 中国」，实测能覆盖 84% 的缺口，
**但它会把「新北市 / 大阪市 / 東京都 / 首尔市」一起判成中国**，直接踩台湾红线。
✅ 正解 = `CHINA_CJK_PLACE_MARKERS` 显式列名（省级 34 + 地级市/自治州/地区/盟，352 条；
**县区级不收**，「保定市-莲池区」靠上级前缀命中）+ `TAIWAN/JAPAN/KOREA_CJK_MARKERS` 配套兜底。
上线后 89.4% 的缺口被认出（61,292 个在招岗），回填 104,158 行。

**三条不许改坏的不变量**：
1. **顺序是设计的一部分**：`TW` 在 `CN` **前**（「Taipei, Taiwan, Province of China」含 "china"，
   排后面会被判成大陆放行）；`JP`/`KR` 在 `CN` **后**（「青岛市、日本、潍坊市」这类一岗多地写法
   要保住 CN —— 不能因为多写一个国名就把中国岗翻成海外）。
2. **选词按「宁可漏判、不可错杀」**：漏判一个台湾岗只是回到 `code=None`，非远程照样被
   `location_in_scope` 丢掉（**无害**）；错判一个大陆岗是把在招岗**静默删掉**（有害）。
   所以有重叠的一律只收「繁体裸名 + 简体带后缀名」：常州有**新北区** → TW 只收「新北市」；
   福州有**连江县** → 只收繁体「連江」；日本**北海道**含「北海」→ CN 只收「北海市」；
   「邢台南和区」含「台南」→ TW 只收「台南市」。韩国的「大田/光州/汉城」刻意不收
   （福建有大田县、潢川古称光州、「武汉城市圈」含汉城）。
3. **词表两端逐条一致**：`tests/geo.test.js` 会读 `crawler/geo.py` 抽四个词表做 deepEqual，
   改一边不改另一边直接红（已做变异验证）。

📌 **改词表的验收方法**（别只跑单测）：把全库 `select distinct location` 拉下来（约 2 万个写法），
拿改前 / 改后两份 `derive_country_code` **逐条对拍**，「大中华 → 境外」这个方向**必须为 0**——
那是唯一会让国内岗凭空消失的方向。
⚠️ **回填期间只要有 crawl 在跑就会被刷回去**：`country_code`/`job_scope` 在 `_UPDATE_COLS` 里、
不在 `_PRESERVE_IF_EMPTY` 里，列表重抓会用**当时 CI 上那版代码**覆盖。2026-09-05 实测：
开跑前查了没有 workflow 在跑，回填完 3 分钟后 `campus-crawl` 起来，用旧代码把 11,613 行刷回 NULL。
**正确顺序是「先推代码、再回填」**，或者回填后复查一遍。

| Source | 状态 | 详情链接格式 |
|---|---|---|
| Apple | 可用（crawler + 已知源刷新） | `jobs.apple.com/en-us/details/...` |
| Siemens | 可用（crawler） | `jobs.siemens.com/en_US/externaljobs/JobDetail/...` |
| 百度 | 可用 | `talent.baidu.com/jobs/detail/{recruitType}/{postId}` |
| 京东 | 可用 | `zhaopin.jd.com/web/job-info-detail?requementId=...` |
| 美团 | 可用（httpx） | `zhaopin.meituan.com/web/position/detail?jobUnionId=...` |
| 快手 | 可用（Playwright 签名拦截 + 全分页） | `zhaopin.kuaishou.cn/#/official/social/job-info/{id}` |
| 哔哩哔哩 | 可用（匿名 CSRF + httpx） | `jobs.bilibili.com/social/positions/{id}` |
| 拼多多 | 可用（httpx，校招） | `careers.pddglobalhr.com/campus/grad/detail?positionId=...` |
| vivo | 可用（httpx） | `hr.vivo.com/job-detail?_irjc=...&_irjid=...` |
| 比亚迪 | 可用（公开全列表 + Playwright 批量加密 URL） | `job.byd.com/portal/pc/#/social/socialPositionDetails?...` |
| 顺丰 | 可用（httpx，最近 50 页诚实 cap） | `hr.sf-express.com/JobSearchById/{id},{positionType}` |
| 海尔 | **暂不可用** | 只解析到入口页，保持 `partial_success` |

---

## 必投清单 aliases：壳牌影子源全过程与 scope 口径实测数字

## ⚠️ 名字对不上 ≠ 没有源：必投清单的别名 aliases（2026-09-04 立）

`resolve_owner` 那套是**单向子串**（清单名 ⊂ 库里名），救不了「字面完全不重叠」这一类：
壳牌在库里记的是英文 `Shell`，缺口普查拿中文「壳牌」匹配 `sources.company` 匹配不上
→ 判「零源缺口」→ **插了第二条源** → 与已有源是同一个 Workday 站点仅大小写不同
（`shell/ShellCareers` vs `shell/shellcareers`）→ 大小写带进 jd_url、`canonical_jd_url` 区分大小写
→ 唯一索引拦不住 → **同一个岗在库里存两行**（迁移 225 已修）。
📌 **「有岗但指标显示 0」比「真没岗」更危险——它会驱动人去重复补源。**

✅ 修法 = 清单条目可选 `"aliases": ["%Continental%"]`（ILIKE 模式，与 `pattern` 同语义）：
- 两端共读同一份 JSON：TS `mustApplyPatterns()` / Python `must_apply.company_patterns()`，
  **改一边的语义必须同改另一边**，否则北极星与缺口台账会给出两个互相打架的数字。
- 生效点：`gap_census.classify_company`（源 + 岗）、北极星 `computeMustApplyCoverage`、
  `must_apply.patterns()`（探活倾斜/富化的成员判断）、缺口漏斗验收门 `_sample_that_passes`
  （新源抓回英文公司名时不再被当张冠李戴删掉）、`owner_index()`（归属判定认英文名）。
- ⚠️ `owner_index()` 不传 scope = 国内+海外并集，此时**规范名恒压过别名**（同一家公司
  两份清单两个名字：国内「大陆集团」/ 海外「Continental」）；要跨语言归属就明确传 `scope`。
- ⚠️ 加别名 = **改北极星口径**，必须逐条有据（库里真有这一行公司名）。
  `tests/must-apply-list.test.js` 把当前别名清单钉死 + 张冠李戴门（别名不得命中同清单另一家）。
- ⚠️ **别拿改名当修法**：把清单里的「大陆集团」改成 `Continental` 会把 352 个海外岗
  算成国内供给。别名只改「怎么匹配」，不改「这家公司归哪份清单」。
- 🔎 复查同类：`sources`/`jobs` 里纯 ASCII 公司名 × 国内清单（2026-09-04 实测只剩
  Continental=大陆集团、Bayer=拜耳），中文公司名 × 海外清单（实测 18 家，见同日 commit）。

✅ **配套口径变更（2026-09-05 创始人拍板）：必投覆盖率只数「本 scope 自己的岗」。**
此前北极星与缺口普查的岗位聚合都**不看 `job_scope`**，两份清单共吃一个合计 →
海外清单的星巴克显示 1,920 个健康岗（实际全是中国门店岗）、国内清单的松下显示 226 个
（实际 18,318 个岗全在海外）。现在：
- 北极星 `computeMustApplyCoverage(list, aggregates, scope)` 按 scope 取数；主聚合改成
  `group by company, job_scope` 后在 JS 合并（live 实测与「加 8 个 count filter」耗时同档，
  1.71s vs 1.80s，但不必给 43.8 万行每行多算 8 个表达式）。平铺字段仍是**两 scope 合计**，
  老语义不变；scope 拆分在 `byScope`。
- 缺口普查 `_JOB_AGGREGATE_SQL` 计数带 `job_scope = %(scope)s`（**参数绑定，不拼字符串**），
  品牌 rollup 列同样过滤，否则海外岗会从父公司门户后门漏进国内覆盖。
- **口径影响（live 实测，别再重算）**：国内 329 家 healthy 228→227（松下）；
  海外 327 家 162→132（星巴克/优衣库/凯德/特斯拉/DHL…共 31 家状态改变）。
- ⚠️ **「本范围 0」必须解释**，否则会被读成「供给没了」：台账 evidence 记
  `other_scope_healthy_jobs`，看板每家公司标签追加「另有 N 个岗在海外/国内」
  （`otherScopeNote`）。两者处置完全不同——前者要补源，后者什么都不用做。
- ⚠️ `job_scope` 只有 `domestic`/`overseas` 两个取值、无 NULL（2026-09-05 全库实测
  32.7 万 + 11.1 万 = 43.8 万 active 全覆盖）。真冒出第三种取值时**宁可不计入任一 scope**，
  也不要偷偷算进国内（`mergeScopeRows` 已如此，有断言钉死）。
- ⚠️ `unstable_cache` 条目跨部署存活（TTL 180s），上线那一小段缓存里是**旧形状**的行 →
  `scopedCounts()` 没有 byScope 时回退平铺合计（**不许改成直接 `byScope[scope]`**，会把
  /admin/health 打挂）。

---

## 校招专区首屏：分面方案的实测数字与 EXPLAIN

## ⚠️ 校招专区首屏：只下发聚合分面，绝不逐条下发岗位（2026-09-02 立）

`/campus` 首屏曾 **responseEnd 10.1s / 单页 2.09 MB HTML**，而 TTFB 只有 189ms ——
**慢的不是取数排队，是 SSR 那一段本身**：把 30 家必投公司的 16,494 个校招岗逐条序列化进 props。
判读法记住：`TTFB 快 + responseEnd 慢` = 生成/传输页面本身的问题，别去查连接池和数据库排队。

现行形态（改动前务必读懂，别改回去）：
1. **页面一条岗位记录都不下发**，只下发 `lib/campus-facets.ts` 的聚合分面
   `[城市下标, 学历下标, 职能下标, 届别, 计数]`。依据：客户端拿逐条记录只做两件事——填筛选下拉、
   算「当前筛选下有几个岗」，**两件事都只依赖这四个维度**，与具体是哪个岗无关。
   live 实测 16,494 条压成 1,917 个四元组，props 2,086 KB → 52.6 KB。
   ⚠️ **构建（buildCampusFacets）与匹配（countMatchingFacets）刻意放同一文件**：下标口径两端一漂，
   卡面就安静地报错数字——不报错、不崩，只骗用户。等价性由 `tests/campus-facets.test.js`
   穷举全部筛选组合钉死，改分面必须让它继续绿。
2. **重活按行业清单缓存**（`unstable_cache`，10 分钟）。它只依赖必投清单、不含用户私有数据，所以能跨请求共享。
   ⚠️ `windowStatus` 与排序**刻意留在缓存外每请求现算**——它们依赖「此刻」（72h 新鲜度阈值），
   一起缓存会把徽章冻住。缓存里只放 `lastSeenAtMs` 这类原始输入。
   ⚠️ 缓存函数体内不得读 `cookies()`/`headers()`（unstable_cache 限制）。
3. **聚合 SQL 不用 `company ilike any()`**：带前导 % 用不了任何索引 → 39 万 active 行并行全表扫
   （live EXPLAIN 2567ms / 127,726 buffers）。改成先用 `jobs_active_company_idx` 取全部 active
   公司名（`allActiveCompanyNames`，5 分钟进程内缓存），JS 按同样的「不区分大小写子串」语义解析出
   确切名字，再 `company = any()` 走 Bitmap Index Scan（957ms / 46,413 buffers，结果集逐行相同）。
4. **展开某家公司走 `/api/campus-zone/jobs`（按 公司+模式），不按 id**：按 id 取就得先把 16,494 个
   uuid 下发到浏览器，光 uuid 就 0.59 MB，白白抵消收益。
   ⚠️ 旧的 by-ids 调法有个真 bug：把 campus 与 intern 的 id 拼一起再截前 200 →
   **大厂的实习桶被校招桶挤没，实习模式展开必然空白**。按模式取从根上没有这个问题。
   ⚠️ 取数分两段：准入门 `campusAdmission` 要看 JD 正文，但**排序键 deadline/first_seen_at 与
   归属键 company 都是轻字段** → 先只取轻字段排好序，再顺着顺序分批（500）取完整行跑准入门，
   收满 200 就停。一次性拉完整行 live 实测字节 5.8s，分段后 0.5~0.9s，语义完全一致。
5. **归属规则三处必须一致**（getCampusZone / getCampusCompanyJobs / 分面计数）：
   list 里第一个 pattern 命中者得（`腾讯音乐 TME` 归 `%腾讯音乐%` 不归 `%腾讯%`）。
   任一处漂移 → 卡面计数与展开列表对不上。live 交叉验证法：卡面计数（来自分面）与
   `/api/campus-zone/jobs` 返回条数（独立重算）在未截断的公司上必须逐个相等。

---

## crawl_runs `skipped` 的成分拆解（2026-09-05 实测快照，原文照搬）

### 第三类：连不上曾被 `should_skip` 吞成 `skipped`（已修，留碑是为了另一个教训）

全表 3,455 条 `skipped` 拆开（2026-09-05 实测）：**3,383 真跳过 + 72 没收尾 + 0 第三形态**
（`finished_at`/`error_message` 两个判据完全同构，不存在「有收尾无原因」或「无收尾有原因」）。
但在那 3,383「真跳过」内部有 **53 条根本不是设计跳过**：`Connection failed: timed out` /
`_ssl.c:999 handshake timed out` / `Errno 101 Network is unreachable` —— 是 HEAD 预检连不上对方，
被 `return f"Connection failed: {e}"` 记成了「跳过」。
真正的设计跳过是这几种：iguopin 详情核验 2,046 / wecruit 板块未发布 506 / feishu 门户 404 504 /
robots 禁止 218 / wecruit 门户不存在 55。

危险在于：**规则 F「源连续失败」只认 `status='failed'`**，被吞成 `skipped` 的源永远凑不满
「全部 failed」→ 一个永久连不上的源可以无限期静默。

✅ **已修**：`729df39`（2026-08-28 02:00）把那行改成 `except Exception: return None`
（fail-open 且不进 host 缓存）→ 连不上就照常往下抓、抓不动落 `failed`，规则 F 认得出。
live 复核：修复前 53 条、**修复后 0 条**，最后一次 2026-08-27 07:59。
AST 扫过全部 36 个 `should_skip` 覆写，**没有一个**在 `except` 里 return 跳过原因，路径已封死。

⚠️ **真正要记的教训是别的：我差点把这个已修的洞又修一遍。**
症状是从**线上存量数据**里查出来的（54 条历史行还躺在表里），读起来像「现在还在发生」，
而它其实 9 天前就停了。**看到存量里的坏数据，第一件事是查「最后一次发生是什么时候」**，
不是直接去改代码 —— `select max(started_at)` 一句话的事，能省掉一整轮返工，
更能避免「修一个不存在的问题」顺手把好代码改坏。

### `crawl_runs` 终态没写成 → 看 `ops_runs.metrics.crawl_run_unrecorded`（2026-09-05 加）

`_process_one_source` 里成功路径的 `update_crawl_run` 抛错会落进 `except`，那里再写一次 `failed`；
**两次都失败**时旧代码只 `print` 一行就放过 —— 行停在 `running` 占位符上，规则 I 能看见这条孤儿，
却看不出成因。现在这种情况会计进 `daily_crawl` 台账的 `crawl_run_unrecorded`，并打一条
`::warning::`。它是**唯一**能区分「进程被杀」和「进程活着但回写失败」的证据：
2026-09-04 那 7 个 workday 源就卡在这个岔口 —— enrichment-crawl 六片全 success、guard 也 success，
GitHub 日志又已被截断，事后无从复原。⚠️ 目前没有告警规则读这个指标，排查规则 I 时要手动对读。
