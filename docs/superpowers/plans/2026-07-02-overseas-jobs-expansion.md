# 海外岗位打通 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把美国/新加坡/全球远程的大公司岗位接入现有求职雷达，与国内岗共库但逻辑隔离，中文简历/岗位卡标签/岗位库治理机制全部复用到英文 JD，零新增 per-job LLM。

**Architecture:** 现有 14 个外企 ATS 适配器早已打通只是写死「只抓中国」。本计划把「只抓中国」按 `sources.regions` 参数化放开（默认 `{CN}` 行为字节级不变）；给 jobs 加 `country_code`/`job_scope` 结构化字段；用全局「求职范围」开关做隔离；岗位卡标签靠确定性正则/词典扩英文；治理栈按源挂直接复用。分 Phase 0（地基+回归护栏）→1（放闸入库）→2（标签+匹配）→3（开关+UI+英文简历）→4（定向补大厂）。

**Tech Stack:** Next.js 14 App Router / React 18 / TypeScript / Tailwind；Supabase（Auth + 用户小表）；自建香港 Postgres 17（jobs 热表，`jobs-db/schema.sql` + `gh workflow run jobs-db-migrate`）；Python crawler（httpx + selectolax + Playwright）；GitHub Actions。测试：`node --test tests/*.test.js` + `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`。

**权威 spec：** [`docs/superpowers/specs/2026-07-02-overseas-jobs-expansion-design.md`](../specs/2026-07-02-overseas-jobs-expansion-design.md)。本计划任一处与 spec 冲突以 spec 为准。

---

## 全局红线（每个 Task 都适用，违反即打回）

1. **零新增 per-job LLM**：打标签全确定性正则/词典；中英词典离线固化成静态文件；简历解析复用现有单次调用。
2. **默认 domestic 字节级不变**：所有 scope-aware 分支在 `regions={CN}` / `job_scope='domestic'` 下与改动前输出完全一致——每个引入分支的 Task 必须带 domestic 快照回归测试。
3. **canonical 三处同步**：若触碰归一逻辑，`lib/canonical-url.js` + `crawler/normalizer.py` + `jobs-db/schema.sql` SQL 函数三处字节级一致（本计划默认不改 canonical 规则；只新增 country_code/job_scope 派生，crawler 与 app 写层口径须一致）。
4. **schema 改动通道**：jobs 列走 `jobs-db/schema.sql` + `gh workflow run jobs-db-migrate`（幂等）；用户表走 `supabase/migrations/`（新前缀先 `ls supabase/migrations` 确认未占用；纯 seed 带 `_seed_`）。**不手动进 SQL Editor。**
5. **JS + Python 双侧同步**：任何岗位卡标签规则（职能/招聘类型/教育/经验/城市/sponsorship）改 JS 读时纯函数必同步改 crawler 写入端，反之亦然，且两侧各补测试。
6. **不碰密钥**：`.env*` / service_role / `JOBS_DATABASE_URL` 值不读不打印。沙箱 live 验证走 `dangerouslyDisableSandbox + source ../.env.local`，DDL 写走 jobs-db-migrate。
7. **最小化改动**：不做无关重构/格式化；改一处必同步描述它的项目文件（CLAUDE.md/目录结构/测试）。
8. **worktree 隔离**：草稿分支自动 commit（每个 Task 收口 commit），**push 等用户明确指令**。
9. **每个 Task 收口**跑该 Task 相关测试 + 提交前回归四件套（`node --test tests/*.test.js && python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && npm run build && git diff --check`）。

---

## 文件结构地图（先锁边界）

| 文件 | 责任 | 动作 |
|---|---|---|
| `jobs-db/schema.sql` | jobs 加 `country_code`/`job_scope`/`sponsorship_signal` 列 + 回填 | 修改 |
| `supabase/migrations/167_overseas_prefs.sql` | user_preferences/candidate_profiles 加范围+地区+英文档案字段 | 新建 |
| `crawler/geo.py` | **新**纯函数模块：`derive_country_code` / `derive_job_scope` / `location_in_scope` / 海外城市别名 | 新建 |
| `crawler/normalizer.py` | 接 geo.py 派生字段；extract_education/extract_job_type/经验 补英文；sponsorship 识别 | 修改 |
| `crawler/adapters/*.py` | 服务端 location 参数 + 客户端过滤按 `source.regions` 参数化 | 修改 |
| `crawler/run.py` | 读 `source.regions` 传给 adapter；country_code/job_scope/sponsorship 入库 | 修改 |
| `crawler/jobs_db.py` | upsert 写入新列（保 `_PRESERVE_IF_EMPTY` 不变量） | 修改 |
| `lib/geo.js` | **新**：JS 侧海外城市别名 + `deriveJobScope`（读时/前端复用，与 crawler/geo.py 同口径） | 新建 |
| `lib/china-keyword-expansion.js` | CITY_ALIASES 扩海外城市；recruitmentCategory/经验补英文；接中英词典 | 修改 |
| `lib/role-lexicon-en.js` | **新**：中英岗位名/技能静态对照词典（离线生成后固化） | 新建 |
| `lib/education-rank.js` | educationRank 补英文学历变体 | 修改 |
| `lib/job-function.js`（或现所在文件） | classifyJobFunction 边缘英文岗位名 | 修改 |
| `lib/sponsorship.js` | **新**：sponsorship 识别纯函数（JS 侧，与 crawler 同规则） | 新建 |
| `lib/scoring.ts` | 地点走别名归一匹配；海外范围并入 en_* + 中英展开词 | 修改 |
| `lib/jobs-store/search.ts` | location 归一走别名；scope/region 过滤 | 修改 |
| `lib/jobs-store/read.ts` | 召回按 scope/region | 修改 |
| `lib/opportunities/eligibility.ts` | locationState scope-aware | 修改 |
| `lib/opportunities/service.ts` | 召回 scope-aware + 海外用 en_* 档案 | 修改 |
| `lib/resume-extract.js` / `app/api/resume/route.ts` | 可选英文简历→en_* 字段（复用现有解析） | 修改 |
| `components/Navbar.tsx` | 全局「求职范围」开关 | 修改 |
| `components/JobFilters.tsx` | 地区/国家筛选 + sponsorship 可选过滤 | 修改 |
| `components/JobCard.tsx` | 渲染 sponsorship 标签 | 修改 |
| `app/api/preferences/*` | job_scope/target_regions 读写 | 修改 |
| `.github/workflows/{daily-crawl,enrich-*,liveness-sweep,dead-link-audit}.yml` | 海外源登记进矩阵 | 修改 |

---

# Phase 0 — 地基 & 回归护栏

> 目标：所有结构化字段、纯函数、迁移就位，且**默认 domestic 行为字节级不变**。此 Phase 不改变任何用户可见行为。

## Task 0.1: 新建 crawler 地理纯函数模块 `crawler/geo.py`

**Files:**
- Create: `crawler/geo.py`
- Test: `crawler/test_geo.py`

- [ ] **Step 1: 写失败测试 `crawler/test_geo.py`**

```python
import unittest
from geo import derive_country_code, derive_job_scope, location_in_scope

class TestDeriveCountryCode(unittest.TestCase):
    def test_china_cities(self):
        self.assertEqual(derive_country_code("Beijing, China"), "CN")
        self.assertEqual(derive_country_code("上海"), "CN")
        self.assertEqual(derive_country_code("Hong Kong"), "HK")
    def test_us_cities(self):
        self.assertEqual(derive_country_code("New York, NY"), "US")
        self.assertEqual(derive_country_code("Sunnyvale, CA, United States"), "US")
        self.assertEqual(derive_country_code("Seattle"), "US")
    def test_singapore(self):
        self.assertEqual(derive_country_code("Singapore"), "SG")
    def test_remote_with_country(self):
        self.assertEqual(derive_country_code("Remote - US"), "US")
    def test_bare_remote_unknown(self):
        self.assertIsNone(derive_country_code("Remote"))
    def test_unknown(self):
        self.assertIsNone(derive_country_code(""))
        self.assertIsNone(derive_country_code("Multiple Locations"))

class TestDeriveJobScope(unittest.TestCase):
    def test_greater_china_is_domestic(self):
        self.assertEqual(derive_job_scope("Beijing, China"), "domestic")
        self.assertEqual(derive_job_scope("Hong Kong"), "domestic")
        self.assertEqual(derive_job_scope("澳门"), "domestic")
    def test_overseas(self):
        self.assertEqual(derive_job_scope("New York, NY"), "overseas")
        self.assertEqual(derive_job_scope("Singapore"), "overseas")
        self.assertEqual(derive_job_scope("Remote - US"), "overseas")
    def test_bare_remote_defaults_domestic(self):
        # 裸 Remote 无国家 token → 不误判为海外
        self.assertEqual(derive_job_scope("Remote"), "domestic")
    def test_unknown_defaults_domestic(self):
        self.assertEqual(derive_job_scope(""), "domestic")

class TestLocationInScope(unittest.TestCase):
    def test_default_cn_matches_today(self):
        # regions={CN} 必须与旧 is_china_location 口径一致
        self.assertTrue(location_in_scope("Beijing, China", {"CN"}))
        self.assertTrue(location_in_scope("Hong Kong", {"CN"}))
        self.assertFalse(location_in_scope("New York", {"CN"}))
        self.assertFalse(location_in_scope("Singapore", {"CN"}))
    def test_overseas_regions(self):
        self.assertTrue(location_in_scope("New York", {"US"}))
        self.assertTrue(location_in_scope("Singapore", {"SG"}))
        self.assertFalse(location_in_scope("London", {"US", "SG"}))
    def test_remote_region(self):
        self.assertTrue(location_in_scope("Remote - US", {"US"}))
        self.assertTrue(location_in_scope("Remote", {"Remote"}))
    def test_multi_region(self):
        self.assertTrue(location_in_scope("Beijing", {"CN", "US", "SG"}))
        self.assertTrue(location_in_scope("Singapore", {"CN", "US", "SG"}))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd crawler && python3 -m unittest test_geo -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'geo'`）

- [ ] **Step 3: 实现 `crawler/geo.py`**

先读 `crawler/normalizer.py` 里现有的 `CHINA_LOCATION_MARKERS`、`OVERSEAS_LOCATION_TOKENS`、`is_china_location`、`is_remote_location`、`normalize_city`，把「大中华判定」逻辑迁移/复用进 geo.py（不要复制两份口径）。实现：

```python
"""地理归属纯函数：country_code / job_scope / 地区范围过滤。
与 lib/geo.js 同口径。大中华判定复用 normalizer 现有 marker 集，避免口径漂移。"""

# ISO-2 国家 token → code。key 全小写，匹配时对 location 小写化后子串/词边界匹配。
# 覆盖本期地区 + 常见大中华。可增量扩。
_COUNTRY_TOKENS = {
    "CN": ["china", "中国", "beijing", "北京", "shanghai", "上海", "shenzhen", "深圳",
           "guangzhou", "广州", "hangzhou", "杭州", "chengdu", "成都", "nanjing", "南京",
           "wuhan", "武汉", "xi'an", "西安", "suzhou", "苏州", "tianjin", "天津"],
    "HK": ["hong kong", "香港", "hongkong"],
    "MO": ["macau", "macao", "澳门"],
    "US": ["united states", "usa", "u.s.", "u.s.a", "america",
           "new york", "纽约", "san francisco", "旧金山", "sf bay", "bay area",
           "seattle", "西雅图", "sunnyvale", "mountain view", "cupertino", "san jose",
           "santa clara", "palo alto", "austin", "boston", "chicago", "los angeles",
           "washington", "atlanta", "denver", "dallas", "houston", "san diego",
           "redmond", "menlo park", ", ca", ", ny", ", wa", ", tx", ", ma"],
    "SG": ["singapore", "新加坡"],
}

_GREATER_CHINA = {"CN", "HK", "MO"}

def _norm(text):
    return (text or "").strip().lower()

def derive_country_code(location):
    """从 location 文本推导 ISO-2 国家码；推不出返 None。多国命中取先声明顺序里最先命中的强 token。"""
    t = _norm(location)
    if not t or t in ("unknown", "multiple locations"):
        return None
    # Remote - US 之类：优先国家 token
    for code, tokens in _COUNTRY_TOKENS.items():
        for tok in tokens:
            if tok in t:
                return code
    return None

def derive_job_scope(location):
    """domestic = 大中华区 (CN/HK/MO) + 无法判定/裸 Remote（不误判海外）；overseas = 其余可判定国家。"""
    code = derive_country_code(location)
    if code is None:
        return "domestic"  # 未知/裸 Remote 默认国内，防误判
    return "domestic" if code in _GREATER_CHINA else "overseas"

def location_in_scope(location, regions):
    """该 location 是否落在 source 配置的地区集合内。
    regions 是 set，元素为 'CN'/'US'/'SG'/'Remote' 等。
    'Remote' 作为伪地区：location 判定为纯远程（无国家 token）时匹配它。
    regions={'CN'} 时必须与旧 is_china_location 口径一致。"""
    regions = set(regions or {"CN"})
    code = derive_country_code(location)
    if code is not None:
        if code in regions:
            return True
        # CN 请求应覆盖整个大中华（HK/MO）——与旧口径一致
        if "CN" in regions and code in _GREATER_CHINA:
            return True
        return False
    # 推不出国家：可能是裸 Remote
    t = _norm(location)
    if "remote" in t or "远程" in t:
        return "Remote" in regions or "CN" in regions  # 裸远程旧口径归国内
    return False
```

> 注：`derive_country_code` 里 CN 的 marker 应与 `normalizer.CHINA_LOCATION_MARKERS` 保持一致；实现时**从 normalizer 导入或共享该集合**，不要维护两份。若 normalizer 的集合更全，以它为准扩充这里。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd crawler && python3 -m unittest test_geo -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add crawler/geo.py crawler/test_geo.py
git commit -m "feat(crawler): geo.py 地理归属纯函数 (country_code/job_scope/location_in_scope), 默认{CN}口径不变"
```

---

## Task 0.2: 新建 JS 侧地理模块 `lib/geo.js`（与 crawler/geo.py 同口径）

**Files:**
- Create: `lib/geo.js`
- Test: `tests/geo.test.js`

- [ ] **Step 1: 写失败测试 `tests/geo.test.js`**

```js
const test = require("node:test");
const assert = require("node:assert");
const { deriveCountryCode, deriveJobScope } = require("../lib/geo.js");

test("deriveCountryCode: greater china", () => {
  assert.equal(deriveCountryCode("Beijing, China"), "CN");
  assert.equal(deriveCountryCode("Hong Kong"), "HK");
});
test("deriveCountryCode: overseas", () => {
  assert.equal(deriveCountryCode("New York, NY"), "US");
  assert.equal(deriveCountryCode("Singapore"), "SG");
  assert.equal(deriveCountryCode("Remote - US"), "US");
});
test("deriveCountryCode: unknown", () => {
  assert.equal(deriveCountryCode("Remote"), null);
  assert.equal(deriveCountryCode(""), null);
});
test("deriveJobScope: domestic vs overseas", () => {
  assert.equal(deriveJobScope("Beijing, China"), "domestic");
  assert.equal(deriveJobScope("Hong Kong"), "domestic");
  assert.equal(deriveJobScope("New York"), "overseas");
  assert.equal(deriveJobScope("Singapore"), "overseas");
  assert.equal(deriveJobScope("Remote"), "domestic"); // 裸 remote 不误判
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/geo.test.js`
Expected: FAIL（Cannot find module '../lib/geo.js'）

- [ ] **Step 3: 实现 `lib/geo.js`**

移植 `crawler/geo.py` 的 `_COUNTRY_TOKENS`/`_GREATER_CHINA` 与三个函数为 JS（CommonJS `module.exports`，与仓库现有 lib 风格一致——参考 `lib/china-keyword-expansion.js` 的导出方式）。逻辑逐行对齐 Python 版，保证同口径。导出 `deriveCountryCode` / `deriveJobScope`（`locationInScope` 前端暂不需要，可不导出）。

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/geo.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/geo.js tests/geo.test.js
git commit -m "feat(lib): geo.js 地理归属纯函数 (JS侧, 与 crawler/geo.py 同口径)"
```

---

## Task 0.3: jobs 表加结构化列（香港库 schema）

**Files:**
- Modify: `jobs-db/schema.sql`

- [ ] **Step 1: 读现状**

读 `jobs-db/schema.sql` 里 `create table jobs (...)`、`count_valid_active_jobs`、canonical 触发器、索引段。确认 `location`、`status`、`summary` 列位置。

- [ ] **Step 2: 加列 + 回填 + 索引**

在 jobs 建表段加两列（若走 ALTER 风格则在文件相应位置加幂等 `alter table ... add column if not exists`）：

```sql
alter table jobs add column if not exists country_code text;
alter table jobs add column if not exists job_scope text not null default 'domestic';
alter table jobs add column if not exists sponsorship_signal text; -- Phase 2 填, 先建列

-- 存量全部视为 domestic（本次上线前库里都是国内岗）
update jobs set job_scope = 'domestic' where job_scope is null;

-- scope-aware 查询用部分索引（雷达/列表按 job_scope 过滤会用到）
create index if not exists jobs_job_scope_status_idx
  on jobs (job_scope, status) where status = 'active';
```

> ⚠️ 若这是对 10 万级大表回填，遵守迁移超时铁律：在事务内加 `set local statement_timeout = '1800s';`（本 default 回填几乎瞬时，但建索引可能慢，稳妥起见加上）。

- [ ] **Step 3: 幂等 apply 到香港库**

Run: `gh workflow run jobs-db-migrate`（等 CI 绿）。本地无法直接跑 DDL（classifier 拦）。

- [ ] **Step 4: 验证列已生效**

沙箱直连香港库核对（`dangerouslyDisableSandbox` + `source ../.env.local` + psql，不打印密钥）：
Run: `psql "$JOBS_DATABASE_URL" -c "select column_name from information_schema.columns where table_name='jobs' and column_name in ('country_code','job_scope','sponsorship_signal');"`
Expected: 三列都在。

- [ ] **Step 5: Commit**

```bash
git add jobs-db/schema.sql
git commit -m "feat(jobs-db): jobs 加 country_code/job_scope/sponsorship_signal 列 + 存量回填 domestic + scope 部分索引"
```

---

## Task 0.4: 用户表迁移（求职范围 + 目标地区 + 英文档案字段）

**Files:**
- Create: `supabase/migrations/167_overseas_prefs.sql`（**先 `ls supabase/migrations` 确认 167 未占用**，被占则顺延）

- [ ] **Step 1: 确认前缀未占用**

Run: `ls supabase/migrations | tail -20`
若 167 已存在，用下一个可用数字，文件名与内容里的注释同步改。

- [ ] **Step 2: 写迁移**

```sql
-- 167_overseas_prefs.sql — 海外岗位: 求职范围 + 目标地区 + 英文档案字段
alter table user_preferences add column if not exists job_scope text not null default 'domestic';
alter table user_preferences add column if not exists target_regions text[] not null default '{}';

alter table candidate_profiles add column if not exists target_regions text[] not null default '{}';
alter table candidate_profiles add column if not exists en_target_roles text[] not null default '{}';
alter table candidate_profiles add column if not exists en_skills text[] not null default '{}';
alter table candidate_profiles add column if not exists en_target_keywords text[] not null default '{}';
alter table candidate_profiles add column if not exists has_en_resume boolean not null default false;
```

> RLS 不用新增策略（这些列挂在已有的自读写表上，沿用原表策略）。

- [ ] **Step 3: apply（push main 时 migrate.yml 自动跑；本地不手动 SQL）**

本 Task 只写文件 + commit。真正 apply 在合并 main 后由 `migrate.yml` 自动执行（`SUPABASE_DB_URL` secret 已配）。

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/167_overseas_prefs.sql
git commit -m "feat(db): user_preferences/candidate_profiles 加 job_scope/target_regions + 英文档案字段"
```

---

## Task 0.5: sources 加 regions 列 + run.py 读取（默认 {CN} 行为不变）

**Files:**
- Create: `supabase/migrations/168_sources_regions.sql`
- Modify: `crawler/run.py`
- Test: `crawler/test_run_regions.py`（新建，mock 不打网络）

- [ ] **Step 1: 写迁移 `168_sources_regions.sql`**

```sql
-- 168_sources_regions.sql — 源级地区配置, 默认只抓大中华
alter table sources add column if not exists regions text[] not null default '{CN}';
```

- [ ] **Step 2: 写失败测试 `crawler/test_run_regions.py`**

测试 `run.py` 把 `source.regions` 透传给 adapter，且缺省为 `{CN}`。读 `crawler/run.py` 现有 `_process_one_source`/adapter 构造签名后，写针对「regions 缺省=CN」「regions=US,SG 透传」的断言（用假 source dict + mock adapter，断言 adapter 收到的 regions 参数）。

```python
import unittest
from unittest import mock
# 依据 run.py 实际结构补 import
class TestRunRegions(unittest.TestCase):
    def test_default_regions_cn(self):
        source = {"adapter_name": "greenhouse", "source_url": "x"}  # 无 regions
        # 断言传给 adapter 的 regions == {"CN"}
        ...
    def test_regions_passthrough(self):
        source = {"adapter_name": "greenhouse", "source_url": "x", "regions": ["US", "SG"]}
        # 断言传给 adapter 的 regions == {"US","SG"}
        ...
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd crawler && python3 -m unittest test_run_regions -v`
Expected: FAIL

- [ ] **Step 4: 改 `crawler/run.py`**

读 source 时取 `source.get("regions") or ["CN"]`，转 set，透传给 adapter 构造/`parse`。**不改 adapter 内部逻辑（Task 1.1 做）**，此处只把参数打通，adapter 暂时忽略也不报错。

- [ ] **Step 5: 跑测试确认通过 + Commit**

Run: `cd crawler && python3 -m unittest test_run_regions -v` → PASS

```bash
git add supabase/migrations/168_sources_regions.sql crawler/run.py crawler/test_run_regions.py
git commit -m "feat(crawler): sources.regions 列 + run.py 透传给 adapter, 默认{CN}"
```

---

## Task 0.6: Workday `_host` 并发隔离回归确认

**Files:**
- Test: `crawler/test_workday_isolation.py`（若已存在同类测试则扩充，不重复造）

- [ ] **Step 1: 查现有隔离测试**

Run: `grep -rn "_host\|per.source\|type()(" crawler/ | grep -i workday`
读 commit fba4c56 引入的「每源新实例隔离」代码（`_process_one_source` 里 `type(adapter)()` 新实例）。

- [ ] **Step 2: 写/扩并发隔离测试**

模拟两个不同 workday 租户源**并发**处理，断言各自 jd_url 的 host 不串（A 源产出的链接 host 全属 A 租户，B 全属 B）。若已有等价测试，仅补一条「多租户并发」断言。

- [ ] **Step 3: 跑测试确认通过**

Run: `cd crawler && python3 -m unittest test_workday_isolation -v`
Expected: PASS（隔离已修，应绿；若红说明扩源前必须先修）

- [ ] **Step 4: Commit**

```bash
git add crawler/test_workday_isolation.py
git commit -m "test(crawler): workday 多租户并发 _host 隔离回归 (海外扩源前置护栏)"
```

---

## Task 0.7: Phase 0 收口回归

- [ ] **Step 1: 跑回归四件套**

Run:
```bash
node --test tests/*.test.js && \
python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && \
npm run build && git diff --check
```
Expected: 全绿。

- [ ] **Step 2: 确认 domestic 零变化**

人工核对：Phase 0 未改任何 adapter 抓取逻辑、未改任何读时纯函数分支，仅新增列/新函数/透传参数。若 build 或任一现有测试变红，说明引入了 domestic 回归，必须修到绿。

---

# Phase 1 — 放闸抓美/新/远程 + 结构化入库 + 治理登记

> 目标：给已打通的外企源配 `regions` 含海外，海外岗真入库、带可靠 jd_url、结构化 country_code/job_scope 落库，并纳入治理矩阵。

## Task 1.1: adapter 服务端参数 + 客户端过滤按 regions 参数化

**Files:**
- Modify: `crawler/adapters/{workday,amazon,phenom,microsoft,google,greenhouse,lever,oracle,eightfold,smartrecruiters,ashby,apple}.py`
- Modify: `crawler/normalizer.py`（`keep_for_china_radar` 旁边加 scope-aware 入口，或让 adapter 直接调 `geo.location_in_scope`）
- Test: `crawler/test_adapter_regions.py`

- [ ] **Step 1: 读每个 adapter 的 location 过滤/参数点**

逐个读 spec §3.1 列出的过滤点：
- 服务端参数型：`amazon.py`（`normalized_country_code[]=CHN`）、`phenom.py`（`?location=China`）、`google.py`（`?location=China`）、`microsoft.py`（`_CN_LOCS` 14 城）、`workday.py`（facet）
- 客户端过滤型：`greenhouse.py`/`lever.py`/`apple.py`（调 `keep_for_china_radar`）、`oracle/eightfold/smartrecruiters/ashby`（调 `is_china_location`）

- [ ] **Step 2: 写失败测试 `crawler/test_adapter_regions.py`**

对**至少三类代表** adapter（服务端参数型选 amazon，客户端过滤型选 greenhouse，facet 型选 workday）写测试：喂 mock 列表响应（含中国岗 + 美国岗 + 新加坡岗），断言：
- `regions={CN}`：只保留中国岗（与今天一致）
- `regions={US,SG}`：保留美/新岗，剔除中国岗
- `regions={CN,US,SG}`：三者都留

```python
# 示例断言骨架（按各 adapter 真实 parse 签名补）
def test_greenhouse_cn_only(self):
    jobs = greenhouse_parse(MOCK_LIST, regions={"CN"})
    locs = {j.location for j in jobs}
    assert all(is_greater_china(l) for l in locs)
def test_greenhouse_overseas(self):
    jobs = greenhouse_parse(MOCK_LIST, regions={"US", "SG"})
    assert any("New York" in j.location for j in jobs)
    assert not any("Beijing" in j.location for j in jobs)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd crawler && python3 -m unittest test_adapter_regions -v`
Expected: FAIL

- [ ] **Step 4: 参数化实现**

原则：
- **客户端过滤**统一改成调 `geo.location_in_scope(location, regions)`（替换写死的 `is_china_location`/`keep_for_china_radar`）；`regions` 从 adapter 构造参数拿（Task 0.5 已透传）。
- **服务端参数**按 `regions` 生成：amazon 的 country code 列表映射（CN→CHN, US→USA…）、phenom/google 的 location 参数、microsoft 的城市集（US 时用美国主要办公城市集）、workday facet（US/SG facet id 需从源 URL 或抓包确定——**若某源 facet id 未知，客户端过滤兜底：服务端不加地区参数、全量拉再用 `location_in_scope` 过滤**，遵守 spec「不猜未验证的板块」）。
- **`regions={CN}` 分支必须与改造前字节级一致**（回归护栏）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd crawler && python3 -m unittest test_adapter_regions -v` → PASS
再跑全 crawler 回归：`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` → 全绿（domestic 不回归）

- [ ] **Step 6: Commit**

```bash
git add crawler/adapters/ crawler/normalizer.py crawler/test_adapter_regions.py
git commit -m "feat(crawler): adapter location 过滤/参数按 source.regions 参数化, 默认{CN}字节不变"
```

---

## Task 1.2: country_code/job_scope 入库（run.py + jobs_db.py）

**Files:**
- Modify: `crawler/run.py`（normalize 后写 country_code/job_scope）
- Modify: `crawler/normalizer.py`（normalize 时调 geo 派生）
- Modify: `crawler/jobs_db.py`（upsert 写新列，保 `_PRESERVE_IF_EMPTY` 不变量）
- Modify: `lib/jobs-store/write.ts`（app 写层同口径派生 job_scope，镜像 crawler）
- Test: `crawler/test_normalizer_geo.py`

- [ ] **Step 1: 写失败测试**

断言 normalize 一条 location="New York, NY" 的 RawJob，产出 `country_code="US"`, `job_scope="overseas"`；location="Beijing" 产出 `CN`/`domestic`。

- [ ] **Step 2: 跑失败 → 实现**

`normalizer.normalize()` 里调 `geo.derive_country_code`/`derive_job_scope` 填字段；`jobs_db` upsert 的 INSERT/UPDATE 列加 country_code/job_scope。**job_scope 属确定派生字段，UPDATE 时可随 location 一起更新（不进 `_PRESERVE_IF_EMPTY`）；但 upsert 的 `status` CASE 黏 expired、`_UPDATE_COLS` 不含 enrich 簿记这两条既有不变量必须保住**（见 CLAUDE.md §4）。`lib/jobs-store/write.ts` app 写层同步派生（用 `lib/geo.js`）。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add crawler/run.py crawler/normalizer.py crawler/jobs_db.py lib/jobs-store/write.ts crawler/test_normalizer_geo.py
git commit -m "feat(crawler): normalize 派生 country_code/job_scope 入库 (crawler+app写层同口径)"
```

---

## Task 1.3: 给已打通外企源配 regions（seed 迁移）

**Files:**
- Create: `supabase/migrations/169_seed_overseas_regions.sql`（**带 `_seed_` 标识**，先 `ls` 确认前缀）

- [ ] **Step 1: 圈定海外源清单**

沙箱查库列出现有外企源（adapter ∈ {workday,amazon,phenom,microsoft,google,greenhouse,lever,oracle,eightfold,smartrecruiters,ashby} 且公司为外企）：
Run（只读）: `psql "$SUPABASE_DB_URL" -c "select id, company, adapter_name, source_url from sources where adapter_name in ('workday','amazon','phenom','microsoft','google','greenhouse','lever','oracle','eightfold','smartrecruiters','ashby') order by company;"`
> `SUPABASE_DB_URL` 不在 `.env.local`——若无法取得，改用 app 只读接口或让用户提供源清单；**不猜**。

- [ ] **Step 2: 写 seed 迁移**

对圈定的外企源 UPDATE `regions`：
```sql
-- 169_seed_overseas_regions.sql — 给已打通外企源放开美/新/远程
update sources set regions = '{CN,US,SG,Remote}'
where adapter_name in ('workday','amazon','phenom','microsoft','google','greenhouse','lever','oracle','eightfold','smartrecruiters','ashby')
  and id in ( /* Step1 圈定的外企源 id 列表 */ );
```
> 保守起见先配 `{CN,US,SG,Remote}`（继续抓在华 + 放开海外），不影响这些源原有在华产出。**长尾/浏览器源不要一次性全放**——先放 httpx 稳定源，浏览器源单独评估（daily 抓不过来的降频）。

- [ ] **Step 3: Commit（apply 随 push main 自动）**

```bash
git add supabase/migrations/169_seed_overseas_regions.sql
git commit -m "feat(db): seed 已打通外企源 regions 放开 CN/US/SG/Remote"
```

---

## Task 1.4: 海外源登记进治理 workflow 矩阵

**Files:**
- Modify: `.github/workflows/liveness-sweep.yml`、`.github/workflows/dead-link-audit.yml`、`.github/workflows/enrich-*.yml`、`.github/workflows/daily-crawl.yml`（按需）

- [ ] **Step 1: 读现有 matrix**

读各 workflow 的 adapter matrix。海外源用的 adapter（workday/greenhouse/lever/amazon…）**大概率已在 matrix 里**（它们本来就抓在华岗）——若是，海外岗自动吃到探活/富化，**无需改 matrix**，本 Task 仅确认。

- [ ] **Step 2: 补缺 + list-absence 地区一致性**

- 若某海外 adapter 不在 liveness-sweep/dead-link-audit matrix，补进去。
- **关键**：若某源用 list-absence 探活（feishu 式），确认其 list-crawl 与 list-absence 用**同一 regions**，否则「本次没抓到」误判死岗（spec §8.2）。审 `enrich_backlog.py --sweep` / list-absence 逻辑是否读同一 `source.regions`。

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/
git commit -m "chore(ci): 确认/补齐海外源进 liveness/enrich 矩阵 + list-absence 地区一致"
```

---

## Task 1.5: Phase 1 live 验收（需真实网络，沙箱 dangerouslyDisableSandbox）

- [ ] **Step 1: 单源 live 抓一个海外源**

Run（沙箱放开 + 真 env）:
```bash
cd crawler && set -a && source ../.env.local && set +a && python3 run.py --source <某已配regions的greenhouse外企>
```
Expected: 产出含美/新岗，每条有 jd_url。

- [ ] **Step 2: 抽 3 条海外 jd_url 验活**

对产出的 3 条 jd_url `curl -sS -o /dev/null -w "%{http_code}"`，Expected 200，且页面含岗位标题。

- [ ] **Step 3: 查库确认结构化字段**

Run: `psql "$JOBS_DATABASE_URL" -c "select job_scope, country_code, count(*) from jobs where job_scope='overseas' group by 1,2 order by 3 desc limit 20;"`
Expected: 有 overseas 行，country_code ∈ {US,SG}，count>0。

- [ ] **Step 4: 记录到 spec §15**

把 live 数字（哪个源、产出几条、jd_url 200 率、overseas 入库数）回填 spec 实施记录。

---

# Phase 2 — 标签英文化 + sponsorship + 中英桥 + 打分

> 目标：英文 JD 在岗位卡上标签正确；中文简历用户能召回相关英文岗。全部确定性规则，零 LLM。每处 JS+Python 双侧 + 测试。

## Task 2.1: 教育学历英文变体

**Files:**
- Modify: `lib/education-rank.js`（educationRank 正则，约 9-20 行）
- Modify: `crawler/normalizer.py`（extract_education，约 236-251 行）
- Test: `tests/education-rank.test.js`、`crawler/test_education_en.py`

- [ ] **Step 1: 写失败测试（JS + Python 各一）**

`tests/education-rank.test.js` 补：
```js
test("education english variants", () => {
  assert.equal(educationRank("Bachelor's degree required"), educationRank("本科")); // 本科档
  assert.equal(educationRank("Master's degree"), educationRank("硕士"));
  assert.equal(educationRank("B.S. in CS"), educationRank("本科"));
  assert.equal(educationRank("M.S. or equivalent"), educationRank("硕士"));
  assert.equal(educationRank("Ph.D. in ML"), educationRank("博士"));
  assert.equal(educationRank("Associate degree"), educationRank("大专"));
});
```
`crawler/test_education_en.py` 对 `extract_education` 同样断言 `"Bachelor's"→本科` 等。

- [ ] **Step 2: 跑失败 → 实现**

两侧正则补变体（先读现有正则再加，别整体替换）：
- 本科：`bachelor'?s?|b\.?\s?s\.?|b\.?\s?a\.?|b\.?sc|undergrad`
- 硕士：`master'?s?|m\.?\s?s\.?|m\.?eng|m\.?sc`
- 博士：`ph\.?\s?d|doctor of philosophy|doctora`
- 大专：`associate('?s)?\s+degree|大专`

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/education-rank.js crawler/normalizer.py tests/education-rank.test.js crawler/test_education_en.py
git commit -m "feat(tags): 教育学历识别补英文变体 Bachelor's/M.S./Ph.D./Associate (JS+Py)"
```

---

## Task 2.2: 经验资历词→年限

**Files:**
- Modify: `lib/china-keyword-expansion.js`（`_minRequiredExperienceYears`，约 450-460）
- Modify: `crawler/normalizer.py`（经验解析对应处）
- Test: `tests/experience-seniority.test.js`、`crawler/test_experience_en.py`

- [ ] **Step 1: 写失败测试**

```js
test("seniority to years fallback", () => {
  // 数字优先; 无数字才用资历词
  assert.equal(minYears("Senior Software Engineer"), 5);
  assert.equal(minYears("Staff Engineer"), 8);
  assert.equal(minYears("Principal Engineer"), 12);
  assert.equal(minYears("Entry Level Analyst"), 0);
  assert.equal(minYears("Software Engineer, 3+ years"), 3); // 数字优先, 不被资历词覆盖
});
```

- [ ] **Step 2: 跑失败 → 实现**

在 `_minRequiredExperienceYears` **数字解析失败后**加资历词兜底表：`entry|junior→0`、`mid|intermediate→3`、`senior→5`、`staff|lead→8`、`principal|distinguished→12`。数字命中时**不**用资历词（数字优先）。Python 侧同步。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/china-keyword-expansion.js crawler/normalizer.py tests/experience-seniority.test.js crawler/test_experience_en.py
git commit -m "feat(tags): 经验补资历词→年限兜底 Senior=5/Staff=8/Principal=12 (数字优先, JS+Py)"
```

---

## Task 2.3: 招聘类型英文信号（校招/社招/实习）

**Files:**
- Modify: `lib/china-keyword-expansion.js`（`recruitmentCategory`，约 500-539）
- Modify: `crawler/normalizer.py`（`extract_job_type`，约 154-182）
- Test: `tests/recruitment-category-en.test.js`、`crawler/test_job_type_en.py`

- [ ] **Step 1: 写失败测试**

```js
test("recruitment category english", () => {
  assert.equal(recruitmentCategory({ title: "Software Engineer Intern" }), "实习");
  assert.equal(recruitmentCategory({ title: "Summer 2026 Internship" }), "实习");
  assert.equal(recruitmentCategory({ title: "New Grad Software Engineer" }), "校招");
  assert.equal(recruitmentCategory({ title: "University Graduate - Engineering" }), "校招");
  assert.equal(recruitmentCategory({ title: "Entry Level Data Analyst" }), "校招");
  assert.equal(recruitmentCategory({ title: "Senior Software Engineer" }), "社招");
  assert.equal(recruitmentCategory({ title: "Staff Engineer" }), "社招");
});
```
> 沿用现有函数签名（读实际入参形态：是 job 对象还是字段串），断言按真实签名调整。

- [ ] **Step 2: 跑失败 → 实现**

补英文信号（遵守「精度优先只认强信号，兜底社招」分层）：
- 实习：`\bintern(ship)?s?\b`（已有，确认覆盖）
- 校招：`new\s?grad|university\s+graduate|graduate\s+program|entry[-\s]?level|campus`（`entry level` 且无年限要求时归校招）
- 社招：`senior|staff|principal|lead|distinguished` 或年限≥2 或默认
Python `extract_job_type` 同步。**信任 adapter 真类型不被正文覆盖**（沿用招聘类型分层判定记忆）。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/china-keyword-expansion.js crawler/normalizer.py tests/recruitment-category-en.test.js crawler/test_job_type_en.py
git commit -m "feat(tags): 招聘类型补英文 New Grad/Entry→校招 Senior/Staff→社招 Intern→实习 (JS+Py)"
```

---

## Task 2.4: 职能分类边缘英文岗位名

**Files:**
- Modify: `lib/china-keyword-expansion.js`（`classifyJobFunction` / `JOB_FUNCTION_RULES`，约 559-620）
- Test: `tests/job-function-en.test.js`

- [ ] **Step 1: 写失败测试**

```js
test("job function english edge titles", () => {
  assert.equal(classifyJobFunction("Staff Software Engineer"), "研发");
  assert.equal(classifyJobFunction("Technical Program Manager"), "产品"); // 或既有 TPM 归类
  assert.equal(classifyJobFunction("Site Reliability Engineer"), "研发");
});
```
> 先读现有 `JOB_FUNCTION_RULES` 确定各桶命名（研发/研發 用哪个字），断言对齐现有取值。

- [ ] **Step 2: 跑失败 → 实现**

补锚点：`staff engineer|sre|site reliability|program manager|tpm`。**宁可优雅降级到「其他」也不误分**（spec）。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/china-keyword-expansion.js tests/job-function-en.test.js
git commit -m "feat(tags): 职能分类补 Staff/SRE/TPM 等英文边缘岗位名"
```

---

## Task 2.5: Sponsorship 识别（JS + Python 纯函数 + 入库 + 卡片 + 筛选）

**Files:**
- Create: `lib/sponsorship.js`、`crawler/sponsorship.py`
- Modify: `crawler/normalizer.py`（normalize 时写 `sponsorship_signal`）、`crawler/jobs_db.py`（写列）
- Modify: `components/JobCard.tsx`（渲染标签）、`components/JobFilters.tsx`（可选过滤）
- Test: `tests/sponsorship.test.js`、`crawler/test_sponsorship.py`

- [ ] **Step 1: 写失败测试（JS）**

```js
const { sponsorshipSignal } = require("../lib/sponsorship.js");
test("sponsorship none", () => {
  assert.equal(sponsorshipSignal("We are unable to provide visa sponsorship"), "none");
  assert.equal(sponsorshipSignal("Must be authorized to work in the US without sponsorship"), "none");
  assert.equal(sponsorshipSignal("US citizens only; security clearance required"), "none");
});
test("sponsorship available", () => {
  assert.equal(sponsorshipSignal("Visa sponsorship available"), "available");
  assert.equal(sponsorshipSignal("We will sponsor H-1B for qualified candidates"), "available");
});
test("sponsorship unknown", () => {
  assert.equal(sponsorshipSignal("Great team, fast growth"), "unknown");
  assert.equal(sponsorshipSignal(""), "unknown");
});
```

- [ ] **Step 2: 跑失败 → 实现纯函数（JS + Python 同规则）**

```js
// lib/sponsorship.js
const NONE = [
  /\bdo(es)? not sponsor/i, /\bno (visa )?sponsorship/i, /\bunable to (provide|offer) (visa )?sponsorship/i,
  /without (visa )?sponsorship/i, /must be authorized to work in the u\.?s/i,
  /u\.?s\.? citizens? only/i, /security clearance/i, /not (able|eligible) to sponsor/i,
];
const AVAIL = [
  /\b(visa )?sponsorship (is )?available/i, /\bwill sponsor/i, /\bwe sponsor/i,
  /h-?1b sponsorship/i, /sponsorship (is )?(provided|offered)/i, /relocation and visa/i,
];
function sponsorshipSignal(text) {
  const t = text || "";
  if (NONE.some((r) => r.test(t))) return "none";
  if (AVAIL.some((r) => r.test(t))) return "available";
  return "unknown";
}
module.exports = { sponsorshipSignal };
```
`crawler/sponsorship.py` 同规则（same regex 列表）。normalize 时对 `title + summary` 跑，写 `sponsorship_signal`；jobs_db upsert 写该列（属派生字段，可随重抓更新，不进 `_PRESERVE_IF_EMPTY`）。

- [ ] **Step 3: 卡片 + 筛选**

`JobCard.tsx`：`sponsorship_signal==='none'` 渲染「⚠️ 需自备身份/不提供 Sponsorship」，`'available'` 渲染「✅ 提供 Sponsorship」，`unknown` 不渲染。`JobFilters.tsx` 加可选「只看提供 Sponsorship」复选（默认不勾、不硬过滤）。

- [ ] **Step 4: 跑测试 → PASS → Commit**

```bash
git add lib/sponsorship.js crawler/sponsorship.py crawler/normalizer.py crawler/jobs_db.py components/JobCard.tsx components/JobFilters.tsx tests/sponsorship.test.js crawler/test_sponsorship.py
git commit -m "feat(overseas): 签证 sponsorship 识别 (JD关键词, 零LLM) + 卡片标签 + 可选筛选"
```

---

## Task 2.6: 海外城市别名

**Files:**
- Modify: `lib/china-keyword-expansion.js`（`CITY_ALIASES`，约 228-270；`normalizeChinaCity`）
- Test: `tests/city-aliases-overseas.test.js`

- [ ] **Step 1: 写失败测试**

```js
test("overseas city aliases bidirectional", () => {
  assert.equal(normalizeCity("Singapore"), normalizeCity("新加坡"));
  assert.equal(normalizeCity("New York"), normalizeCity("纽约"));
  assert.equal(normalizeCity("San Francisco"), normalizeCity("旧金山"));
  assert.equal(normalizeCity("Seattle"), normalizeCity("西雅图"));
});
```
> 用实际导出的归一函数名（`normalizeChinaCity` 或别名）；断言双向归一到同一 canonical。

- [ ] **Step 2: 跑失败 → 实现**

`CITY_ALIASES` 加海外条目（纽约/New York、旧金山/San Francisco/SF、西雅图/Seattle、山景城/Mountain View、桑尼维尔/Sunnyvale、圣何塞/San Jose、奥斯汀/Austin、波士顿/Boston、新加坡/Singapore、伦敦/London 等）。**注意**：函数名叫 `normalizeChinaCity` 但现在含海外城市，可保留旧名（避免大改调用点）或加注释说明已泛化。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/china-keyword-expansion.js tests/city-aliases-overseas.test.js
git commit -m "feat(match): CITY_ALIASES 补海外城市双向别名 (纽约/旧金山/西雅图/新加坡…)"
```

---

## Task 2.7: 中英岗位名/技能对照词典（静态，离线生成）

**Files:**
- Create: `lib/role-lexicon-en.js`
- Modify: `lib/china-keyword-expansion.js`（关键词展开时并入英文等价词）
- Test: `tests/role-lexicon.test.js`

- [ ] **Step 1: 生成词典（离线一次性，可用 LLM 辅助，产出后固化）**

产出 `lib/role-lexicon-en.js`：中文岗位名/技能 → 英文等价词数组。**运行时零 LLM**。至少覆盖：
```js
module.exports = {
  roles: {
    "产品经理": ["product manager", "pm", "product owner"],
    "算法": ["algorithm", "machine learning", "ml engineer", "ai engineer"],
    "后端": ["backend", "back-end", "server-side"],
    "前端": ["frontend", "front-end", "web developer"],
    "数据": ["data", "data scientist", "data engineer", "data analyst"],
    "运营": ["operations", "ops"],
    "设计": ["designer", "ux", "ui"],
    "测试": ["qa", "test engineer", "sdet"],
    "运维": ["devops", "sre", "site reliability"],
    // …扩到覆盖常见职能
  },
  skills: {
    "机器学习": ["machine learning", "ml"],
    "深度学习": ["deep learning"],
    // …
  },
};
```

- [ ] **Step 2: 写测试**

```js
const lex = require("../lib/role-lexicon-en.js");
test("lexicon expands cn role to en", () => {
  assert.ok(lex.roles["算法"].includes("machine learning"));
});
```

- [ ] **Step 3: 接入关键词展开**

在 `jobMatchesChinaKeyword` / 关键词展开路径，把用户中文 role/skill 经词典展开出英文词参与匹配（**仅海外范围或全都要范围启用**，domestic 不变）。

- [ ] **Step 4: 跑测试 → PASS → Commit**

```bash
git add lib/role-lexicon-en.js lib/china-keyword-expansion.js tests/role-lexicon.test.js
git commit -m "feat(match): 中英岗位名/技能静态对照词典 + 海外范围关键词展开 (运行时零LLM)"
```

---

## Task 2.8: scoring 地点别名匹配 + 海外范围并入 en_* 档案

**Files:**
- Modify: `lib/scoring.ts`（地点匹配约 101-109；关键词/技能匹配）
- Test: `tests/scoring-overseas.test.js`

- [ ] **Step 1: 写失败测试**

```js
test("scoring: overseas city alias location match", () => {
  const profile = { target_locations: ["新加坡"] };
  const job = { location: "Singapore", title: "Data Engineer", summary: "..." };
  assert.ok(scoreJob(job, profile).score > 0); // 新加坡↔Singapore 命中
});
test("scoring: en profile fields used in overseas scope", () => {
  const profile = { en_target_roles: ["machine learning"], job_scope: "overseas" };
  const job = { title: "Machine Learning Engineer", job_scope: "overseas", summary: "..." };
  assert.ok(scoreJob(job, profile).score > 0);
});
```
> 按 `lib/scoring.ts` 实际签名/返回结构调整断言（读它现有 test 与返回形态）。

- [ ] **Step 2: 跑失败 → 实现**

- 地点匹配：`location.includes(loc)` 前先把 job.location 与 target_locations 都过 `normalizeCity`/别名归一再比。
- 关键词/技能：海外范围（或 all）下，把 `en_target_roles/en_skills/en_target_keywords` + 词典展开词并入匹配集。domestic 范围不变。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/scoring.ts tests/scoring-overseas.test.js
git commit -m "feat(match): scoring 地点走别名归一 + 海外范围并入 en_* 档案 (domestic 不变)"
```

---

# Phase 3 — 求职范围开关 + 地区筛选 UI + 可选英文简历 + 雷达 scope-aware

## Task 3.1: 求职范围偏好读写 + 全局开关组件

**Files:**
- Modify: `app/api/preferences/route.ts`（或现有偏好读写处，读实际路径）
- Modify: `components/Navbar.tsx`
- Test: `tests/preferences-scope.test.js`（纯函数校验 job_scope 取值合法）

- [ ] **Step 1: 后端读写 job_scope/target_regions**

偏好读写 API 支持 `job_scope`（`domestic|overseas|all`，非法值回退 domestic）+ `target_regions`。写 `user_preferences`。

- [ ] **Step 2: Navbar 开关组件**

加「求职范围」下拉/分段控件（国内/海外/全都要），值持久化到偏好；切换后触发看板/列表刷新（沿用现有偏好变更刷新机制）。默认 domestic。移动端沿用现有汉堡菜单适配（见 mobile-adaptation 记忆）。

- [ ] **Step 3: 校验测试 + Commit**

```bash
git add app/api/preferences/ components/Navbar.tsx tests/preferences-scope.test.js
git commit -m "feat(overseas): 求职范围偏好读写 + Navbar 全局开关 (默认国内)"
```

---

## Task 3.2: 岗位库列表/搜索 scope-aware + 地区筛选 UI

**Files:**
- Modify: `lib/jobs-store/search.ts`、`lib/jobs-store/read.ts`（按 job_scope/target_regions 过滤）
- Modify: `components/JobFilters.tsx`（地区/国家筛选）
- Modify: `app/jobs/jobs-client.tsx`（传参）
- Test: `tests/jobs-store-scope.test.js`（纯函数/SQL 构造层）

- [ ] **Step 1: search/read 按 scope 过滤**

list/count/recall 读 `user_preferences.job_scope`：`domestic`→`job_scope='domestic'`；`overseas`→`'overseas'` 且命中 target_regions（country_code ∈ regions）；`all`→不加 scope 过滤。**默认 domestic 与今天一致**。
> ⚠️ **首页计数不受此影响**——首页仍用 `count_valid_active_jobs()` 全量合并总数（spec §8.3）。此 Task 只改**列表/召回**，不改首页计数。

- [ ] **Step 2: 地区筛选 UI**

`JobFilters.tsx` 加「地区」筛选（美国/新加坡/远程/全部海外），仅在 job_scope≠domestic 时显示；国内范围隐藏。区别于现有「资方属地」（公司国籍）。

- [ ] **Step 3: 测试 + Commit**

```bash
git add lib/jobs-store/ components/JobFilters.tsx app/jobs/jobs-client.tsx tests/jobs-store-scope.test.js
git commit -m "feat(overseas): 岗位库列表/召回 scope-aware + 地区筛选UI (首页计数仍合并总数)"
```

---

## Task 3.3: 首页计数保持合并总数（验证性 Task）

**Files:**
- 只读核对 + 必要时改回

- [ ] **Step 1: 确认首页计数用全量函数**

Read 首页计数组件（`JobLibraryStat` 或 today 指标），确认它调 `count_valid_active_jobs()` 无 scope 参数、不读 job_scope。若 Task 3.2 误把 scope 传进首页计数，改回全量。

- [ ] **Step 2: 加断言测试**

若首页计数有对应服务端函数，加测试断言其不因 job_scope 变化。

- [ ] **Step 3: Commit（若有改动）**

```bash
git add -A && git commit -m "test(overseas): 锁定首页计数=合并总数, 不随求职范围开关变"
```

---

## Task 3.4: 可选英文简历上传 → en_* 档案（复用现有解析）

**Files:**
- Modify: `app/api/resume/route.ts`（接受 `variant=en` 参数，产出写 en_* 字段）
- Modify: `lib/resume-extract.js`（复用同解析器，英文输入）
- Modify: 简历/偏好页组件（加「上传英文简历（可选）」入口）
- Test: `tests/resume-en-mapping.test.js`

- [ ] **Step 1: 后端支持 en variant**

resume 路由加可选 `variant`（`cn`默认 / `en`）。`en` 时：走**同一个** one-shot 解析器（现有 `lib/resume-extract.js`，OCR 已 chi_sim+eng），把结果映射写入 `candidate_profiles.en_target_roles/en_skills/en_target_keywords` + `has_en_resume=true`。**不新增第二个 LLM 模型调用；就是现有那一次解析，只是落到 en_ 列。**

- [ ] **Step 2: 前端入口**

简历/偏好页加「上传英文简历（可选，用于海外岗精准匹配）」入口，成功后提示已启用英文匹配。

- [ ] **Step 3: 映射纯函数测试**

对「解析结果 JSON → en_* 字段」的映射写纯函数测试（不打 LLM，喂假解析结果）。

- [ ] **Step 4: Commit**

```bash
git add app/api/resume/ lib/resume-extract.js tests/resume-en-mapping.test.js <前端简历组件>
git commit -m "feat(overseas): 可选英文简历上传→en_*档案 (复用现有单次解析, 零新增LLM)"
```

---

## Task 3.5: 雷达/今日机会 scope-aware

**Files:**
- Modify: `lib/opportunities/eligibility.ts`（`locationState`，约 58-67）
- Modify: `lib/opportunities/service.ts`（召回 + 海外用 en_* 档案）
- Modify: `app/api/opportunities/route.ts`
- Test: `tests/opportunities-scope.test.js`

- [ ] **Step 1: 写失败测试**

```js
test("locationState: overseas scope lets overseas job pass", () => {
  const prefs = { job_scope: "overseas", target_regions: ["US"] };
  const job = { location: "Seattle, WA", job_scope: "overseas", country_code: "US" };
  assert.equal(locationState(job, prefs), "match");
});
test("locationState: domestic scope unchanged (regression)", () => {
  const prefs = { job_scope: "domestic", target_locations: ["北京"] };
  const job = { location: "Beijing", job_scope: "domestic" };
  assert.equal(locationState(job, prefs), "match");
  const overseasJob = { location: "New York", job_scope: "overseas" };
  assert.equal(locationState(overseasJob, prefs), "mismatch"); // 国内范围不放海外
});
```

- [ ] **Step 2: 跑失败 → 实现**

- 召回（service.ts）按 `job_scope` 收窄候选（复用 Task 3.2 read 层）。
- `locationState`：海外范围用 country_code ∈ target_regions 判 match；domestic 范围维持 `normalizeChinaCity` 口径**字节级不变**（回归）。
- 海外范围打分并入 en_* 档案（复用 Task 2.8）。
- **首轮入库不污染动量**：确认动量/新机会信号仍读 `job_events.FIRST_SEEN`（append-only），海外岗首轮批量入库不刷爆（spec §9）。若动量逻辑读 `jobs.first_seen_at`，海外首轮需打标或延迟计入。

- [ ] **Step 3: 跑测试 → PASS → Commit**

```bash
git add lib/opportunities/ app/api/opportunities/ tests/opportunities-scope.test.js
git commit -m "feat(overseas): 今日机会/雷达 scope-aware (海外用en_*档案, domestic字节不变, 防动量污染)"
```

---

## Task 3.6: Phase 3 收口回归 + 文档同步

- [ ] **Step 1: 回归四件套** → 全绿

- [ ] **Step 2: 同步项目文档**

更新 `CLAUDE.md`（数据库表加 country_code/job_scope、四层搜索段若涉及、当前 source 状态加海外说明）、`README`/目录结构若有描述、spec §15 实施记录。遵守「留痕+同步文档」——扫一遍谁在描述这块，过时表述一并更新。

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "docs(overseas): 同步 CLAUDE.md/spec 实施记录 (country_code/job_scope/求职范围开关)"
```

---

# Phase 4 — 定向补 Fortune 500/1000 大厂（后置，live-gated，非本期核心）

> 不铺量。只定向补缺失的目标大厂，必须 live 探活确认稳定产出真实岗位才入库（禁猜 slug）。

## Task 4.1: 缺口盘点 + 定向探活

**Files:**
- 复用 `crawler/probe.py`（扩源探活器）

- [ ] **Step 1: 盘点**

对照 Fortune 500/1000，列出「用户目标相关 + 现有源池缺失」的大厂（科技/消费/金融为主）。产出候选清单（公司 + 猜测 ATS 类型）。

- [ ] **Step 2: live 探活**

Run: `cd crawler && set -a && source ../.env.local && set +a && python3 probe.py --all --emit <下一个迁移号>`
只把「真返回美/新/远程岗位」的写进 seed 迁移。**禁止猜 slug 入库**。

- [ ] **Step 3: 入库 + 配 regions + 登记矩阵 + Commit**

新源 seed 迁移带 `regions={US,SG,Remote}`（或按实际），并确认进治理矩阵。

- [ ] **Step 4: 记录**

spec §15 记录新增了哪些大厂、各产出多少真实岗。

---

# 收尾

## 全量验收（对照 spec §11，Claude 验收）

- [ ] 1. 默认国内用户看板/计数/匹配零变化（domestic 快照对照全绿）
- [ ] 2. 切「海外」：今日机会 + 岗位库出现美/新/远程大公司岗，带 jd_url、200 点开即达、JD 正文≥60 字
- [ ] 3. 中文简历用户在海外范围能召回相关英文岗（算法→ML Engineer）
- [ ] 4. 传英文简历后海外匹配精度明显提升
- [ ] 5. 抽检真实英文 JD：招聘类型/教育/经验/职能标签正确
- [ ] 6. 不给 sponsorship 的美国岗被正确标记
- [ ] 7. 海外死岗被探活挤掉，不虚高计数；海外源在 sweep/audit 矩阵内真跑
- [ ] 8. 全链路无新增 per-job LLM（代码审查确认）
- [ ] 9. 首页计数 = 合并总数，不随开关变
- [ ] 10. 回归四件套 + canonical 双侧测试全绿

## Self-Review 记录（写计划时已核）

- **Spec 覆盖**：spec §4 各层 → Phase 0-3 各 Task 一一对应；§6 标签 → Task 2.1-2.4；§7 sponsorship → Task 2.5；§5 中英桥 → Task 2.6-2.8；§8 治理 → Task 1.4；§9 边界（动量污染/Workday 隔离/裸 Remote/英文简历质量）→ Task 0.6/2.x/3.5 覆盖；首页合并总数 → Task 3.3。
- **类型一致**：`derive_country_code`/`derive_job_scope`/`location_in_scope`（Py）↔ `deriveCountryCode`/`deriveJobScope`（JS）同口径；`sponsorshipSignal` 返回 `available|none|unknown` 全程一致；`job_scope` 取值 `domestic|overseas`（岗）与 `domestic|overseas|all`（用户偏好）区分清楚。
- **无占位**：所有规则/词表/正则已给具体内容；对未读函数的改动明确要求「先读现有实现再改」+ 给出完整测试契约作为验收锚。
