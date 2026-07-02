# W7 第一方「给-取」众包 — 实施计划（build-ready）

> 承接 `docs/superpowers/specs/2026-06-22-career-insights-remaining-work-codex.md` §W7 + 记忆 `job-radar-insights-crowdsourcing-deferred`。
> 目标读者：执行者（下次会话 / Codex），自包含。写于 2026-07-02。

## 0. 一句话目标 & 为什么

让**本平台用户匿名提交自己对某公司的亲身体验**（实习/入职/年终奖/面试难度/文化/晋升），**给-取解锁**（贡献一条才看全部），经审核+去标识后展示。这是「想要社区高赞帖价值」的**合规终极答案 = 自己当社区**（Glassdoor/Levels.fyi/Blind/脉脉皆此模式）。第一手、可信、越用越厚、最防爬。

## 1. 项目铁律（沿用，必守）

- **TDD**；单测不打真实网络；四件套绿（node --test / crawler unittest / npm build / git diff --check）。
- **合规是本功能第一约束**（装用户 UGC+PII，赶工出错=事故）：知情同意 / 去标识 / 不可反识别 / 用户可删自己数据（PIPL 权利） / 审核后才展示。
- 洞察表在 **Supabase**（不是香港库）。复用现有 `insight_items` 展示池 + `lib/insight-verification.ts` 门 + `/admin/insights` 审核模式 + `lib/apiAuth`（requireUser/requireAdmin）+ `lib/supabaseService`（service-role 写）。
- 迁移放 `supabase/migrations/` 递增前缀，push 自动 apply。

## 2. 关键设计决策（执行前先定这 3 个）

### D1. 展示粒度：个体匿名 vs 纯聚合 —— **推荐：个体匿名（Glassdoor 式）+ 聚合头**
- 第一方是用户**知情同意主动提交自己的经历** → 展示**匿名个体条目**（不露姓名/user_id）合规风险低，且这才是「社区帖」的价值（一条条真实反馈）。
- **硬门防再识别**：某公司**≥N（建议 5）条 approved 才展示任何一条**；顶部给聚合（平均评分 + 条数）。
- 与现有 `insight-verification` 的「群体聚合」口径协调：first_party 条目单独走一条更宽的展示门（个体匿名 + ≥N 公司门 + 审核过），不套用「≥2 publisher」（那是搜索源的门）。**新增 `grade='first_party'` 或 `origin='first_party'` 区分**。

### D2. 给-取门：贡献才解锁 —— **推荐：贡献 ≥1 条（pending 即算）解锁全部 first_party 内容**
- 非贡献者：看**聚合头 + 前 1 条模糊/teaser** + 「贡献一条解锁」CTA。
- 贡献者：看全部 first_party 条目。
- `pending` 即算贡献（别让用户等审核才解锁，体验差；防刷靠审核阶段剔除垃圾）。

### D3. 审核：人工 vs 自动 —— **P1 人工（起步量小）；LLM 预过滤留 P3**
- P1：admin 在后台看 `pending`，approve/reject（复用 `/admin/insights`）。
- 提交时先跑**去标识 lint**（复用 `insight-verification` 的 assertion/attribution 检查 + 加「人名/手机号/身份证」正则）自动拦明显 PII。

## 3. 合规清单（每条都要落实，验收必查）

- [ ] 提交表单含**知情同意勾选**：「我确认这是我的亲身经历、不含他人可识别信息，同意匿名展示」——不勾不能提交。
- [ ] 内容**长度上限**（≤200 字）+ **去标识 lint**（拦人名/手机/身份证/@某人）。
- [ ] 展示**匿名**（无姓名、无 user_id、无精确时间到天）；标注「员工自愿分享·已审核」。
- [ ] **≥N 条公司门**（防单条再识别）。
- [ ] 用户**可删自己的提交**（PIPL 删除权，P2）。
- [ ] RLS：用户只能读/插/删**自己的** submission；approved 的匿名视图对所有登录用户可读；admin 读全部+改 status。
- [ ] 不存超必要 PII；user_id 仅用于给-取计数与删除权，**不对外暴露**。

## 4. 数据模型（迁移，P1）

`supabase/migrations/1XX_insight_submissions.sql`（前缀先 `ls` 确认）：
```sql
create table if not exists insight_submissions (
  id uuid primary key default gen_random_uuid(),
  company text not null,                 -- 归一公司名（对齐 jobs.company，用 lib/insight-match）
  company_id uuid references company_profiles(id),  -- 匹配到则填
  user_id uuid not null,                 -- 提交人（给-取计数+删除权，不外露）
  dimension text not null check (dimension in ('culture','compensation_intensity','path','hiring')),
  topic text not null,                   -- 实习体验/入职体验/年终奖/面试难度/晋升/文化
  rating int check (rating between 1 and 5),
  content text not null,                 -- ≤200 字，去标识
  payload jsonb not null default '{}',   -- 结构化字段（年终奖→months；面试→rounds/result）
  status text not null default 'pending' check (status in ('pending','approved','rejected','retired')),
  moderation jsonb not null default '{}',-- {reviewer_id, reason, reviewed_at}
  employment_verified boolean not null default false,  -- P3
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_insight_submissions_company_status
  on insight_submissions (company, status);
create index if not exists idx_insight_submissions_user
  on insight_submissions (user_id, created_at desc);
alter table insight_submissions enable row level security;
-- 用户读/插/删自己的
create policy "own_rw" on insight_submissions for select using (user_id = auth.uid());
create policy "own_insert" on insight_submissions for insert with check (user_id = auth.uid());
create policy "own_delete" on insight_submissions for delete using (user_id = auth.uid());
-- admin 读全部 + 改（service-role 走后端，绕 RLS；此策略给 admin 页直读）
create policy "admin_all" on insight_submissions for select using (
  exists (select 1 from profiles where id = auth.uid() and role='admin'));
revoke all on insight_submissions from anon;
```
> approved 的匿名展示不走用户 RLS（会露 user_id 归属）→ 由**后端 API 用 service-role 读 approved + 剥 user_id** 后返回（见 §5）。

## 5. API（P1）

- **POST `/api/insights/submit`**（`requireUser`）：校验 dimension/topic/content（长度 + 去标识 lint + 知情同意）→ service-role insert `status='pending'` → 返回 `{ok, contributed:true}`（前端据此解锁）。
- **GET `/api/insights`（扩展）**：现有基础上，追加
  - `first_party`: 该公司 approved submissions（**service-role 读，剥掉 user_id**，匿名），仅当 count ≥ N；含聚合头（avg rating、count）。
  - `first_party_locked`: bool = 当前用户贡献数 == 0（给-取）。锁定时 first_party 只回 teaser（聚合头 + 1 条截断）。
- **admin**：`GET /api/insights/admin/submissions`（`requireAdmin`，列 pending）+ `PATCH`（approve/reject，写 status+moderation）。复用 `app/api/insights/admin/route.ts` 模式。

纯函数（可单测，放 `lib/`）：
- `lib/insight-submission.ts`：`validateSubmission(body)`（长度/必填/去标识 lint/consent）、`aggregateFirstParty(rows, {minCount})`（≥N 门 + 聚合头 + 匿名剥离）、`isFirstPartyLocked(userContributionCount)`。**这些是 P1 测试重点**。

## 6. 前端（P1）

- `components/CompanyInsightDrawer.tsx`：
  - 新增 **first_party 区**（「员工自愿分享 · 已审核」）：聚合头（★平均分·N 条）+ 条目卡（匿名·topic·rating·content·时间到月）。
  - 锁定态（`first_party_locked`）：teaser + 「贡献一条，解锁全部」CTA → 开提交表单。
- 新 `components/InsightSubmitForm.tsx`：topic 选择 + rating + 短文本（带去标识提示 + 字数计）+ 知情同意勾选 + 结构化字段（按 topic 变）→ POST submit → 成功后本地解锁 + 「审核后展示」。
- `app/admin/insights`（或复用 InsightsAdminClient）：加「待审提交」tab，approve/reject。

## 7. 分阶段（每阶段独立可上线、独立 commit）

- **P1（核心闭环）**：迁移 + `validateSubmission`/`aggregateFirstParty` 纯函数 + submit API + GET 扩展（**先不做给-取锁，approved 全员可见**）+ 提交表单 + admin 审核 + 展示。**先跑通「提交→审核→匿名展示」**。
- **P2（给-取 + 删除权）**：`first_party_locked` 逻辑 + teaser/CTA + 用户删自己提交（合规）。
- **P3（信誉/验证）**：邮箱/在职验证（`employment_verified`）+ LLM 预审（拦 PII/辱骂）+ 反刷。

## 8. 冷启动

drawer 不会空——现有搜索聚合 T3（`origin='public_web'`）已填 culture/comp/path。first_party 在其上生长；给-取 CTA 驱动贡献；可请 3–5 内测用户先为自己公司贡献几条打底。

## 9. 测试策略

- 纯函数（P1 重点）：`validateSubmission`（合规/长度/lint/consent 各分支）、`aggregateFirstParty`（<N 不展示 / ≥N 展示 + 匿名剥 user_id + 聚合头正确）、`isFirstPartyLocked`。
- API：submit 鉴权 + 校验拒绝 + 插入 pending；admin approve 改 status；GET 锁定/解锁分支。
- 前端：tsc + build；表单提交流。

## 10. 不做 / 风险

- 不展示个体身份、不存超必要 PII、不做实名。
- 风险：审核不及时（起步人工可控）；刷量（审核 + P3 反刷）；再识别（≥N 门 + 去标识 + 匿名）。任何合规存疑 → 停下确认，别赌。

## 11. 复用锚点

`lib/apiAuth`（鉴权）/ `lib/supabaseService`（service-role）/ `lib/insight-match`（公司归一）/ `lib/insight-verification`（去标识/assertion lint 可复用进 `validateSubmission`）/ `app/api/insights/admin/route.ts`（审核模式）/ `components/CompanyInsightDrawer.tsx`（展示）/ `InsightsAdminClient`（admin UI）。
