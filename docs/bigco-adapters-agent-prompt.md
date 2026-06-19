# 任务交接 Prompt：求职雷达 — 缺失大厂专用 adapter 攻坚

> 把本文件整段交给执行 agent。它是自包含的：执行者对本次会话无记忆，所需上下文都在这里。
> 完成后由主 agent 按「验收标准」逐项核验。

---

## 你的角色与使命

你是「求职雷达 / Job Radar」项目（`/Users/bytedance/Desktop/求职雷达`）的爬虫工程师。
本项目抓取**公开企业官网岗位**，标准化入库，给用户做岗位雷达看板。

**使命**：为下列**自建门户、岗位 API 登录态/签名拦截**的大厂，各打通一条能稳定抓到**在华真岗**的抓取链路，
并按项目规范入库。这些是公认的硬骨头（所以至今没进库）。**不是每家都能成——能成的做实，不能成的诚实记录为不可行。**

目标公司（7 家）：**快手 Kuaishou、哔哩哔哩 bilibili、拼多多 Pinduoduo、vivo、顺丰 SF Express、比亚迪 BYD**；
外加 **美团 Meituan**（已作为 `company_spa` 探路源入库，见下「先决检查」）。

---

## ⚠️ 铁律（违反即判定失败，最高优先级）

1. **不许编造、不许猜。** 禁止猜测 API slug / tenant / 端点路径入库（项目原则#3 明令「禁止猜 slug 入库」）。
   每个声称「打通」的源，必须有**你亲手 live 抓到的真实在华岗位证据**（真实岗位标题 + 可打开的逐岗详情 URL）。
2. **`jd_url` 质量高于一切。** 必须是**逐岗详情页真实链接**（HTTP 200、页面含岗位标题/正文），
   **禁止**写入：招聘首页 / 搜索页 / 列表页 / 登录页 / 猜测拼接的链接。拿不到稳定逐岗链接的源 = 不算打通。
3. **诚实记录不可行。** 若某公司 anti-bot 连无头浏览器都拦（如签名校验 + 设备指纹 + 验证码），
   **如实写明「不可行 + 你试了什么 + 卡在哪」**，不要伪造成功、不要塞垃圾岗占数。项目原则#4：指标诚实，不拿失活/假岗滥竽充数。
4. **只抓在华岗**（中国大陆 + 港澳，排除台湾）。海外岗一律不入库。
5. **最小化改动**：复用现有适配器基类与抽象，不做无关重构。

---

## 攻坚顺序（每家公司按此从便宜到贵依次试，能在前一档成就别上下一档）

1. **先试通用 `company_spa`**（零新代码）：本项目有通用浏览器拦截适配器 `company_spa`
   （`crawler/adapters/china_ats.py` 的 `CompanySpaAdapter`，渲染页面 + 拦截**所有 JSON** 响应 + 启发式抽岗）。
   做法：把该公司公开招聘页填成一个 `company_spa` 源，本地用浏览器档跑一遍，看是否抓到真岗。
   - 成 → 不用写 bespoke，直接加 `company_spa` 源即可（最省）。
2. **再找半公开 httpx 端点**（次省，最优产物）：很多「自建门户」其实有**不挂签名的公开/半公开 JSON 接口**，
   常在 `careers.` / `apply.` / `api.` 等子域，或某个 `getJobAd` / `position/list` 端点不校验 token。
   参照已打通的 `ctrip`（`careers.ctrip.com` getJobAd 公开接口，零浏览器）、`netease/oppo/xiaohongshu/alibaba/huawei`
   （都是 PlaywrightAdapter 子类但**自带 httpx fetch**、找到了公开端点）。**curl 实测**该端点不带登录态也能返回在华真岗 → 写一个 httpx adapter。
3. **最后才 playwright-intercept bespoke**：若列表 API 必须带 **JS 计算的签名/token**（直连 401/40003/40008/token 过期），
   则渲染公开招聘页让**浏览器自己带签名发请求**，你**拦截那条响应**取岗（签名由页面 JS 完成，你不用逆向它）。
   参照 `bytedance` / `tencent`（浏览器档）与 `company_spa` 的拦截机制。
4. **都不行** → 记为不可行（见铁律#3）。

---

## 各公司情报（探活已知，省你重复踩坑；2026-06-19 实测）

| 公司 | 公开招聘站 | 已知岗位接口 & 拦截 | 提示 |
|---|---|---|---|
| 美团 Meituan | `zhaopin.meituan.com/web/position` | `/api/web/position/list` → `401 未登陆`（带 page cookie 仍 401）；**mtgsig 签名** | **已作 `company_spa` 源入库探路**，先查它产没产岗（见先决检查）；产了就别重做，没产再走 bespoke/判不可行 |
| 快手 Kuaishou | `zhaopin.kuaishou.cn` | `/recruit/e/api/official/job/list` → `40008 用户未登录` | 签名/登录态 |
| 拼多多 Pinduoduo | `careers.pinduoduo.com` | `/api/...` → `40003`（token-gated） | |
| vivo | `hr.vivo.com` | `/api/recruit/position/list` → `TOKEN已过期`（uuc.vivo.xyz SSO） | |
| 顺丰 SF Express | `campus.sf-express.com`（另有社招站，自己找） | → `401 Unauthorized` | campus 是校招，社招站可能另有域名 |
| 比亚迪 BYD | `job.byd.com` | `/portal/api/position/list` → `Token无效`；另见 `careersite.tupu360.com`（tupu360 平台，本项目暂不支持） | |
| 哔哩哔哩 bilibili | `jobs.bilibili.com` | 自建 SPA（`zhaopin-toc`，资源在 hdslb.com CDN）；旧 moka slug `bilibili01`/`bilibili` 已死 | 纯自建，无现成平台 |

> 这些 401/token 多半意味着「列表接口要页面 JS 给的签名」——正是攻坚顺序第 3 档 playwright-intercept 的典型场景。
> 但也可能 anti-bot 连无头都拦（铁律#3 如实记录）。

---

## 先决检查（动手前必做）

美团已于本轮作为 `company_spa` 源入库（`supabase/migrations/153_seed_add_honor_webank_meituan.sql`）。
**先确认它在最近一次浏览器档抓取里产没产岗**（查香港库 jobs 表 `jd_url like '%zhaopin.meituan.com%'` 的 active 数）：
- 若 >0 且 jd_url 是逐岗详情：美团**已通**，company_spa 打法成立 → 对快手/B站/拼多多优先复用 company_spa，别造轮子。
- 若 =0：company_spa 对强反爬不通 → 美团也纳入 bespoke 攻坚或判不可行。

---

## 项目规范（务必遵守，否则爬虫找不到你的 adapter / 入库失败）

**新增一个 adapter 必须同步接线 4 处**（漏一处则次日爬虫拿不到 adapter）：
1. `crawler/run.py`：① `from adapters.xxx import XxxAdapter` ② `ADAPTERS` 字典加 `"xxx": XxxAdapter()`
   ③ 分类：是中国公司 → 加入 `DOMESTIC_ADAPTERS`（优先抓）；④ 若是**纯 httpx 零浏览器** → 加入 `_HTTPX_SAFE_ADAPTERS`（享并发档）；**用浏览器的绝不能加** `_HTTPX_SAFE_ADAPTERS`（Playwright 非线程安全，必须落串行档）。
2. `crawler/probe.py`：`from run import ADAPTERS` 已自动带入；若是 httpx adapter，把名字加进 `_HTTPX_ADAPTERS` 集合。
3. `lib/source-adapters.ts`：`SOURCE_ADAPTERS` 数组加一项（value=adapter 名、label、hint、crawl_method 建议），值必须与 run.py 的 ADAPTERS 对齐。

**适配器实现要点**：
- 参照最接近的现成实现：httpx 自建门户看 `crawler/adapters/ctrip.py`（PlaywrightAdapter 子类 + 自带 httpx fetch）；
  浏览器拦截看 `crawler/adapters/china_ats.py`（`CompanyAtsBase` / `CompanySpaAdapter` / `MokaAdapter` / `BeisenAdapter`）、`bytedance.py`、`tencent.py`。
- ⚠️ **adapter 实例可能被多源共享**：`run.py` 现已对每源 `type(adapter)()` 新建实例隔离（见 `_process_one_source`），
  但你的 adapter **仍应把 per-source 状态（host/site/分页游标等）当局部、或每次 fetch 重新绑定**，别假设跨源持久。
- **在华过滤**：用 `crawler/normalizer.py` 的 `is_china_location`；海外岗丢弃。
- **JD 正文**：列表接口通常不含正文 → 逐岗 detail 端点抓 `jobDescription`/正文填 `summary`（参照各 adapter 的 detail 抓取；
  `run.py` 的 `CRAWL_DETAIL_CAP` 控制每源逐岗抓取上限）。抓不到正文不阻断入库，但有正文质量更高。
- **质量门**：入库前过 `normalizer.validate_job_quality`（company/title/jd_url 非空 + jd_url 是真实详情页）。

**入库（加 source 行）**：用 migration seed，**不要手改 DB**。
- 文件名：`supabase/migrations/<下一个序号>_seed_<desc>.sql`（序号先 `ls supabase/migrations` 取最大 +1；**文件名必须含 `_seed_`**）。
- 格式照抄 `152_seed_add_huolala_beisen.sql` / `153_seed_add_honor_webank_meituan.sql`（`insert into sources(company,source_url,source_type,adapter_name,crawl_method,segment,industry,notes) select ... where not exists(...)` 幂等）。
- push 到 main 自动应用（`.github/workflows/migrate.yml`），无需手跑 SQL。

**测试**：每个新 adapter 加 `crawler/test_<name>.py`（unittest，**不打真实网络**——喂样例 JSON/HTML 给 parse，断言抽出的岗位字段 + jd_url 格式）。参照 `crawler/test_workday_adapter.py` 等。
提交前回归：`cd crawler && python3 -m unittest discover -s . -t . -p "test_*.py"`。

---

## Live 访问 / 运行 / 验证（沙箱注意）

- 一切 DB / 联网 curl **必须**用 Bash 工具的 `dangerouslyDisableSandbox: true`（普通沙箱会阻断/抹掉网络）。
- 载入环境：`set -a && source /Users/bytedance/Desktop/求职雷达/.env.local && set +a`（在项目目录跑）。**绝不 echo/打印任何密钥**。
- 香港 jobs 库（jobs 表）：`psql "$JOBS_DATABASE_URL" -c "..."`；**会话 TZ 是 Asia/Shanghai，比时间用 `last_seen_at at time zone 'utc'`**。
- sources 表在 Supabase（不在香港库）：用 node + `@supabase/supabase-js`（`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`，REST 分页 1000/页）。
- 本地跑单源（验证 adapter）：`cd crawler && set -a; source ../.env.local; set +a; python3 run.py --source <adapter_name>`
  （浏览器档需 `python -m playwright install chromium`；本机若无 chromium 需先装）。
- 真正端到端验证产岗，靠 CI：push 后 `gh workflow run daily-crawl.yml`（httpx 档）或 `enrich-crawl.yml`（浏览器档），
  跑完查香港库该源 active 数 + 抽样 jd_url curl 看是否 200 真详情页。

---

## 交付物 & 验收标准（主 agent 将逐项核验）

对**每一家**公司，交付下列之一：

**A. 打通**（需全部满足，缺一不算）：
- [ ] adapter 实现（新文件或复用 company_spa/已有），**4 处接线**齐全（run.py×2 类、probe.py、source-adapters.ts）。
- [ ] `crawler/test_<name>.py` 单测，断言 parse 抽岗 + jd_url 格式，且**全量 crawler 单测绿**。
- [ ] source 行经 `_seed_` migration 入库。
- [ ] **live 证据**：本地或 CI 实抓到 ≥1 页**在华真岗**，附 3-5 个真实岗位标题 + 对应 `jd_url`，且**随机抽 1 条 curl 实测 HTTP 200 且是逐岗详情页**（非列表/首页）。
- [ ] 香港库该源 active 数 > 0 且 jd_url 为逐岗详情链接。

**B. 不可行**（同样是合格交付）：
- [ ] 写明该公司**用什么平台/端点**、**卡在哪**（贴出 curl/渲染实测的错误证据：状态码、anti-bot 提示、是否拦无头）、**试过哪几档**（company_spa / httpx 端点 / playwright-intercept）。
- [ ] 给出结论：暂不可行 / 需要项目暂不具备的能力（如打码、设备指纹、登录态）。

**最终请返回一张总表**：公司 | 结论(打通/不可行) | adapter | source_url | live 实抓岗位数 + 样例标题 | 抽样 jd_url 及其 HTTP 状态 | 备注。
诚实第一：**1 家做实的「打通」远胜 7 家注水的「打通」**。

---

## 提交方式

- 每家公司或每个逻辑块一个清晰 commit（说清改了什么、为什么、live 验证结果）。
- 同步所有描述改动的文件（CLAUDE.md「当前 source 状态」表、source-adapters.ts、目录结构若涉及）。
- 不要 `git push` 前与主 agent / 用户确认（push 会触发生产迁移与抓取）。除非另有授权，push 留作确认点。
