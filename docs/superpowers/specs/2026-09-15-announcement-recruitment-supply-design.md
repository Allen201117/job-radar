# 公告制招聘供给方案设计（事业单位/体制内）

> 2026-09-15。创始人拍板方向后落文档。目标：把 `/programs`「公告制招聘」从**纯手工 ~20 条**做成**可自动扩量、带时效治理**的供给。范围：应届 + 社会都做。优先解决**供给**与**时效**，UI 校招/社招归属往后放。

## 1. 问题与现状（事实）

- `/programs` 现在读 `apply_programs` 表（迁移 226），**纯手工 seed、人工核实、约 20 行**，无抓取管道，**无任何机制回头复查一条公告是否过期**（[[job-radar-a-class-gap-sweep]] 已立碑）。这是「投递量太少」的根因。
- `apply_programs` 的可见性门 = `verified_at`（人工核实过才展示）；截止日期存**自由文本** `window_text`（226 里刻意「不存 date 怕造假精度」，那是给手工小量定的）。这两条正好挡在扩量路上。
- 产品红线：① jd_url 精度（公告页本就进不了 jobs，`/programs` 是它的合法归宿）；② **第三方平台禁令**（中公/华图/搬运公众号一律不用，只有国聘例外）；③ 指标诚实、归属准确、工程化底线（台账/告警/先量后改）。

## 2. 研究结论（2026-09-15 live 实测，决定方案边界）

- **只靠官方源就够，不碰公众号、不碰第三方。** 广东 `hrss.gd.gov.cn/zwgk/sydwzp/`、北京 `rsj.beijing.gov.cn/xxgk/gkzp/` 的人社厅「事业单位公开招聘」栏目实测为**当天更新、带日期、URL 稳定的静态 HTML**，httpx 直接可抓。公众号内容 = 官网栏目同一份东西的另一个入口，且文章列表无法程序化枚举 → **放弃公众号**。
- **技术栈按省碎片化**：5 省样本出现 3 类形态——静态好抓（广东/北京）、UA 敏感（江苏，裸 curl 403、带 Chrome UA 200）、JS SPA 难抓（浙江/四川，需浏览器）。**不能一个爬虫通吃全国**，逐省适配。
- **公告 = 一文覆盖多岗位 + 一个报名截止日**，与「一 jd_url = 一岗位」模型不匹配。
- 覆盖率判断：官方来源足够（政务公开条例强先验，31 省应都有对应栏目，但只逐一验证了 5 省，非扫全集）。军队文职有 `81rc.81.cn`（JS 分页）、央国企有国聘（已有 adapter，注意其 84% 归属错配历史，复用现有归属校验）。
- ❌ 不可用：`www.gjzhaopin.cn`（DNS 无法解析，WebSearch 给出但实测证伪）。

## 3. 核心设计决策（创始人已确认三点）

### 决策① 数据单元 = 公告本身，**不拆成岗位**
一条公告 = 一个投递入口，用户点进官方公告原文按公告报名。理由：契合现有 `announcement` 档、零新范式、绝不污染岗位库；保住「公告链接好拿」的成本优势；事业单位求职者本就以「读公告」为最小单位。
- YAGNI：**不建**「公告→岗位」解析层，除非日后证明必需。

### 决策② 时效 = 抽结构化截止日 + 过期自动下架
新增结构化 `deadline` 日期列（**软化 226「只存文本」的决定**，创始人已点头）。规则：
- 能可靠抽到报名截止日 → 存 `deadline`，`deadline < 今天` 自动隐藏（`status=expired`）。
- 抽不到 → `deadline=null` + `deadline_text` 存原文兜底 + 按 `published_at + 保守 TTL` 兜底过期（默认 45 天，可配）。
- 原文照抄仍保留（`deadline_text`），避免硬解析造假精度——**只有高置信抽取才写结构化 date**。

### 决策③ 自动质量门替代人工核实，归属靠白名单**天然正确**
四道门：**只从官方政府域名白名单抓（归属由构造保证，不会张冠李戴）→ 探活能打开 → 截止日没过 → 带发布日排序**。企业爬取最头疼的「张冠李戴」在此免费解决——因为只抓 gov 官方域名。

## 4. 存储：新建独立表 `announcement_postings`（不扩 apply_programs）

**为什么新表**：质量模型（自动探活+自动过期 vs 人工核实永久有效）、量级（数千 vs 数十）、查询形态（地区/受众/截止日分面）都不同；新表可保住 `apply_programs`「人工核实」不变量完整。`/programs` 读侧 **union 两张表**统一渲染为「招聘公告」卡。

```
announcement_postings
  id              uuid pk
  source_portal   text not null      -- 官方源标识，如 'gd_hrss' / 'bj_rsj'（白名单键）
  source_url      text not null unique -- 公告详情页 URL（必须官方 gov 域名）
  title           text not null      -- 公告标题
  region          text               -- 省/市，如 '广东省' / '北京市'
  employer_type   text               -- 粗分类：事业单位/军队文职/央国企/高校（可空）
  audience        text not null default 'unknown'
                  check (audience in ('fresh_grad','experienced','both','unknown')) -- 应届/社会/两者/未知
  published_at    date               -- 公告发布日期（列表页自带）
  deadline        date               -- 报名截止日（高置信抽到才填）
  deadline_text   text               -- 截止日原文兜底
  status          text not null default 'active'
                  check (status in ('active','expired','dead')) -- 可投/过期/探活失败
  first_seen_at   timestamptz not null default now()
  last_seen_at    timestamptz not null default now() -- 列表页最近一次还挂着它
  last_checked_at timestamptz        -- 最近一次探活时间
  created_at/updated_at timestamptz
```

- 可见性 index + RLS：所有人可读 `status='active' and (deadline is null or deadline >= current_date)`；写仅 service_role。对齐 226 的 RLS 写法。
- 唯一约束 `source_url`：官方公告 URL 天然稳定唯一，做去重键（不需要 canonical 那套 tracking 归一，gov 站无 tracking 参数——若发现有，再补最小归一）。
- **白名单是唯一的归属门**：`source_portal` 必须在代码里的官方源注册表中；插入端硬校验 `source_url` 的 host 属于该 portal 声明的官方域名，否则拒收。

## 5. 抓取管道（新建，独立于 jobs adapter）

`crawler/announcements/`（新目录，不混进 `crawler/adapters/` 的 jobs adapter 体系）：
- `portals.py`：官方源注册表——每个 portal = `{key, name, region, list_url(s), domain(s), fetch_kind: 'static'|'ua'|'browser', parser}`。MVP 只登记 `gd_hrss` / `bj_rsj`（均 static/ua）。
- `harvest.py`：主流程。逐 portal：取列表页 → 解析出 `{title, source_url, published_at, deadline?}` → 校验 host 属于该 portal 官方域名 → upsert 到 `announcement_postings`（`last_seen_at=now`）。**列表页缺席不立即判死**（见 §6 时效），只更新看到的。
- `deadline_extract.py`：**规则优先**（正则覆盖常见写法：「报名时间：X年X月X日至X年X月X日」「截止X月X日」「自公告发布之日起X个工作日」等），抽不到返回 None（绝不瞎猜）。**先不接 LLM**（成本纪律 + 「别塞进散文」）；日后规则不够再评估。
- `expire.py`：过期治理——`deadline < today` 或 `published_at + TTL < today`（deadline 为空时）→ `status=expired`；探活失败 → `status=dead`。可与 harvest 同一 workflow 收尾跑。
- `ops`：每次 harvest 写 `ops_runs` 台账（复用 `crawler/ops_runs.record_ops_run`），指标含**分 portal**：抓到条数 / 新增 / 更新 / 抽到截止日的比例 / 过期下架数 / 零产出标记。「绿灯零产出」必须出声。

## 6. 时效与探活

- **列表页缺席 ≠ 撤岗**（对齐 CLAUDE.md「列表里没有 ≠ 已撤岗」红线）：政府栏目列表会翻页/归档，缺席不判死。判死只靠 ① `deadline` 过期（结构化，最可靠）② 兜底 TTL ③ 详情页探活 404/明确下架文案。
- 探活：MVP 阶段廉价做——harvest 时对**新抓到**的 `source_url` 探一次 HTTP 200 + 页面含公告特征；存量的定时低频探活放二期（政府站相对稳定，先靠 deadline 治理）。

## 7. 展示（/programs）

- `lib/announcement-postings-store.ts`（镜像 `apply-programs-store.ts`）：读 `status=active and 未过期`，时间桶缓存（复刻既有防陈旧缓存写法）。
- `lib/apply-programs.ts` 的读模型扩展或并列一个 `AnnouncementPosting` 模型；`/programs` 页 `announcement` 区 union 手工 `apply_programs.announcement` 行 + 抓取的 `announcement_postings`，统一渲染为「招聘公告」卡。
- 新增分面：**地区** + **应届/社会**（`audience`）。排序：`published_at` 倒序。截止日醒目（琥珀色，复用现有 windowText 样式），加「发布于 N 天前」新鲜度标（走 `lib/relative-time`，SSR 时区安全）。
- 保住 `/programs` 设计红线：不可点整卡、显式标「招聘公告」、说清「为什么没有逐岗列表」。
- 校招/社招界面归属（从 /campus /jobs 导流到 audience 子集）= **二期**，本期只在 /programs 内做 audience 分面。

## 8. 落地节奏（先量后做）

- **Phase 0（先量，本次先做）**：写一次性 probe，对广东+北京 live 抓列表 + 抽样详情，产出**真实数字**：能抓到多少条公告、其中多少能抽到结构化截止日、URL 是否稳定官方域名。这是 go/no-go 闸——若截止日抽取率过低，回头调「兜底 TTL 为主、结构化 deadline 为辅」的口径。
- **Phase 1（MVP）**：广东+北京端到端——迁移建表 + `crawler/announcements/` 管道 + 过期治理 + 读侧 store + /programs 展示 + ops 台账 + 单测（规则抽取纯函数、host 白名单校验、可见性过滤）。
- **Phase 2**：逐省铺开（静态省优先，UA 省次之，JS SPA 省用浏览器道）；接军队人才网；复用国聘公告（带归属校验）；存量定时探活。
- **Phase 3**：高校/科研长尾，单独立项（数千独立站）。

## 8.5 Phase 0 实测结果（2026-09-15，先量已完成）

throwaway probe（httpx + selectolax，纯官方域名）实测：

| 源 | 形态 | 首页可报名公告 | 截止日抽取率(粗规则) | URL 是否自带日期 |
|---|---|---|---|---|
| 北京 `rsj.beijing.gov.cn/xxgk/gkzp/` | 静态 HTML | 11 | 4/5 | 是 `t{YYYYMMDD}_{id}.html` |
| 广东 `hrss.gd.gov.cn/zwgk/sydwzp/zpgg/` | 静态 HTML | 7（剔除2条成绩/公示） | 4/7 | 否 `post_{id}.html`（用列表页日期） |

**据此确认/修正的设计点：**
- ✅ 供给真实、纯 httpx 可抓、官方域名、当天更新 —— 建管道成立。
- ✅ 截止日抽取 8/12≈67%（粗规则），抽不到走 TTL 兜底不丢件 —— 自动过期成立。
- 🔧 **新增设计要求（实测逼出）**：栏目里混着**成绩/公示/政策/分数线**类非报名通知，必须 ① 抓**招聘公告子栏目**（广东走 `/zpgg/` 而非栏目根）② 内容过滤（INCLUDE `招聘|引进|招募|遴选|选聘` 且 EXCLUDE `成绩|分数线|公示|拟聘|名单|递补|政策法规|资格复审|体检|考察|准考证|取消|延期|更正|补充`）。**「能抽到未来截止日」本身就是「这是可报名公告」的强信号。**
- 北京 URL 自带发布日期（免解析），广东用列表页日期。

## 9. 测试

- 纯函数单测：`deadline_extract`（多种真实写法 → 期望日期/None）、host 白名单校验（非官方域名拒收）、可见性/过期过滤、audience 归类。
- crawler 侧 unittest 不打真实网络（用固定 HTML 夹具）。
- 前端契约：/programs union 渲染、SSR 日期走 `formatDateLabel`。

## 10. 公开仓与安全

- 本仓 PUBLIC：写进代码/迁移的只有**官方政府 URL**（本就公开），无密钥、无绝对路径、无公司内部信息。
- `announcement_postings` 表在 **Supabase**（同 apply_programs，小表、非 jobs 热表；不进香港库）。迁移走 CI 自动 apply。

## 11. 明确不做（YAGNI 边界）

- 不拆公告为岗位；不接 LLM 抽取（先规则）；不做公众号抓取；不碰第三方平台；不做校招/社招界面导流（二期）；不做高校长尾（三期）；存量高频探活延后（先靠 deadline 治理）。
