# SME 供给验证与规模信号地基 v1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先量后改——用真实数据分清"对用户不公平"是**小厂库存不足**还是**小厂曝光不足**,同时把"公司规模/性质/阶段"的规范化信号地基建起来(不复用旧字段语义、不逐岗物化)。

**Architecture:** 新增 `company_size_signals` 表(规范化三轴 + 证据 + 状态,与旧 `headcount_band`/`funding_stage` 语义隔离);一个纯映射模块从**已有硬证据**(Wikidata headcount / sources.segment / funding_stage)保守 seed 该表(宁可 unknown 不错标);一个**只读**审计脚本跨库(HK jobs + Supabase signals)量化"低产出层里有多少能确认是真小厂 / 真大厂 / 未知",产出 Plan 2 的分叉决策。

**Tech Stack:** Python 3.11(crawler,unittest,psycopg2)、Supabase Postgres(migration)、香港自建 PG(只读查询)。无前端、无 LLM、无网络(测试全用纯函数 + mock)。

**Spec:** `docs/superpowers/specs/2026-09-15-company-tiering-sme-expansion-design.md`

## Global Constraints

以下逐条来自 spec,每个 task 隐含遵守:
- **jd_url 准确性高于一切**;本计划全程**只读**,不写 jobs、不改 status、不入库任何岗位。
- **宁可 unknown 不错标**:任何维度无硬证据一律 unknown;跨档区间(如"1000-5000"跨 2000 分界)保留原区间、band=unknown,不硬归。
- **岗位数一律不作规模信号**:审计里的"在招岗数分桶"只用于**分层抽样**,绝不据此判定公司规模。
- **不复用旧字段语义**:新增 `company_size_signals` 表,不改写 `company_profiles.headcount_band`/`funding_stage`(旧富化管线仍按旧口径写它们)。
- **segment 只作待核线索**:`sources.segment=foreign` 是历史按 ATS 类型批量填的、非股权核验 → 映射为 `ownership_class` 时状态必须是 `pending`,不得升级为 `confirmed`。
- **不逐岗物化**:本计划不给 jobs 加任何列。
- **跨库读**:jobs 在香港库(`JOBS_DATABASE_URL`),signals 在 Supabase(`SUPABASE_DB_URL`);审计脚本分别连、在 Python 里 join,不做跨库 SQL join。
- 迁移前缀递增不重复(当前最新 251,本计划用 252);新表非 seed,文件名不带 `_seed_`。
- **执行前先设 `export MAIN_REPO=<你的主仓绝对路径>`**(`.env.local` 所在的仓库根;本仓公开,文档一律不写绝对路径)。下文命令用 `"$MAIN_REPO"` 引用它。

---

### Task 1: `company_size_signals` 表 schema(迁移 252)

**Files:**
- Create: `supabase/migrations/252_company_size_signals.sql`

**Interfaces:**
- Produces: 表 `company_size_signals`,列:`id uuid pk`、`company text not null unique`、`size_band text`(check in `<100/100-499/500-1999/2000+/unknown`)、`ownership_class text`(check in `民营/外资/央企/地方国企/unknown`)、`dev_stage text`(check in `初创/成长/成熟/unknown`)、`raw_size_evidence text`(原始人数/区间,跨档时保留)、`evidence_url text`、`evidence_date date`、`entity_scope text`(check in `group/legal_entity/operating_entity/unknown`,默认 unknown)、`size_status text`(check in `confirmed/pending/conflict/unknown`,默认 unknown)、`source_signal text`(check in `wikidata/segment/funding_stage/manual/llm`)、`created_at timestamptz default now()`、`updated_at timestamptz default now()`。RLS:service_role 全权、authenticated 只读且限 admin(镜像 `must_apply_gap_attempts`)。

- [ ] **Step 1: 写迁移文件**

```sql
-- 252 — 公司规模/性质/阶段 规范化信号表（与旧 headcount_band/funding_stage 语义隔离）。
-- 宁可 unknown 不错标：无硬证据一律 unknown；跨档区间保留原文、band=unknown。

create table company_size_signals (
  id uuid primary key default gen_random_uuid(),
  company text not null unique,
  size_band text check (size_band in ('<100','100-499','500-1999','2000+','unknown')),
  ownership_class text check (ownership_class in ('民营','外资','央企','地方国企','unknown')),
  dev_stage text check (dev_stage in ('初创','成长','成熟','unknown')),
  raw_size_evidence text,
  evidence_url text,
  evidence_date date,
  entity_scope text not null default 'unknown'
    check (entity_scope in ('group','legal_entity','operating_entity','unknown')),
  size_status text not null default 'unknown'
    check (size_status in ('confirmed','pending','conflict','unknown')),
  source_signal text check (source_signal in ('wikidata','segment','funding_stage','manual','llm')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_size_signals_band on company_size_signals (size_band, size_status);

alter table company_size_signals enable row level security;
revoke all on table company_size_signals from public, anon, authenticated;
grant all on table company_size_signals to service_role;
grant select on table company_size_signals to authenticated;

create policy "Admins can read company_size_signals"
  on company_size_signals for select
  to authenticated
  using (exists (select 1 from profiles where id = auth.uid() and role = 'admin'));
```

- [ ] **Step 2: 本地真库 dry-run(临时表 + ROLLBACK,用 `including all`)**

Run:
```bash
cd "$MAIN_REPO" && set -a && source .env.local && set +a && \
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 <<'SQL'
begin;
\i .claude/worktrees/laughing-galileo-012163/supabase/migrations/252_company_size_signals.sql
insert into company_size_signals (company, size_band, size_status, source_signal)
  values ('__dryrun__', 'unknown', 'unknown', 'manual');
select count(*) from company_size_signals;
rollback;
SQL
```
Expected: 无 ERROR,`count` 返回 1,末尾 ROLLBACK(不留数据)。

- [ ] **Step 3: 前缀校验**

Run: `bash scripts/check-migrations.sh` (若脚本存在)
Expected: PASS(252 未被占用、纯数字前缀)。

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/252_company_size_signals.sql
git commit -m "feat(tiering): company_size_signals 规范化三轴信号表(迁移 252)"
```

---

### Task 2: 硬证据保守映射 + seed 脚本

**Files:**
- Create: `crawler/size_signals.py`
- Create: `crawler/test_size_signals.py`

**Interfaces:**
- Consumes: 无(纯函数 + Supabase 读写)。
- Produces:
  - `map_headcount_band(raw: str | None) -> tuple[str, str | None]` 返回 `(size_band, raw_evidence_if_straddle)`;识别的确档→对应 band、`None`;跨档(含 '-' 且两端落不同 band,如 '1000-5000')→ `('unknown', raw)`;空/未知→ `('unknown', None)`。
  - `map_segment_ownership(segment: str | None) -> tuple[str, str]` 返回 `(ownership_class, size_status)`:`soe→('央企'?...)` **不可细分,返回 `('unknown','pending')` 且调用方记 note**;`foreign→('外资','pending')`;`private→('民营','pending')`;其余→`('unknown','unknown')`。
  - `map_funding_stage(fs: str | None) -> str` 返回 `dev_stage`:`已上市→'成熟'`;`未上市/未披露→'unknown'`(不推初创);空→`'unknown'`。
  - `seed_from_hard_evidence(sb_conn) -> dict` 读 `company_profiles`,对每行 upsert `company_size_signals`(company 冲突则更新),返回计数 `{seeded, band_confirmed, ownership_pending, unknown}`。

- [ ] **Step 1: 写失败测试**

```python
# crawler/test_size_signals.py
import unittest
from size_signals import map_headcount_band, map_segment_ownership, map_funding_stage

class TestSizeSignalMapping(unittest.TestCase):
    def test_clear_bands_map_directly(self):
        self.assertEqual(map_headcount_band('1-100'), ('<100', None))
        self.assertEqual(map_headcount_band('10万+'), ('2000+', None))
        self.assertEqual(map_headcount_band('500-1000'), ('500-1999', None))

    def test_straddle_range_is_unknown_but_keeps_raw(self):
        # 1000-5000 跨 2000 分界 → 不硬归,band=unknown,原文保留
        self.assertEqual(map_headcount_band('1000-5000'), ('unknown', '1000-5000'))

    def test_empty_is_unknown(self):
        self.assertEqual(map_headcount_band(None), ('unknown', None))
        self.assertEqual(map_headcount_band(''), ('unknown', None))

    def test_segment_foreign_is_pending_not_confirmed(self):
        # segment=foreign 是按 ATS 类型批量填的,只能 pending
        self.assertEqual(map_segment_ownership('foreign'), ('外资', 'pending'))
        self.assertEqual(map_segment_ownership('private'), ('民营', 'pending'))

    def test_segment_soe_cannot_split_央企_vs_地方(self):
        # soe 无法细分央企/地方国企 → unknown + pending,不硬猜
        self.assertEqual(map_segment_ownership('soe'), ('unknown', 'pending'))

    def test_funding_stage_never_infers_startup(self):
        self.assertEqual(map_funding_stage('已上市'), '成熟')
        self.assertEqual(map_funding_stage('未上市/未披露'), 'unknown')
        self.assertEqual(map_funding_stage(None), 'unknown')

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd crawler && python3 -m unittest test_size_signals -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'size_signals'`)

- [ ] **Step 3: 实现映射函数(先只实现纯函数,seed 下一步)**

```python
# crawler/size_signals.py
"""公司规模/性质/阶段 硬证据保守映射。宁可 unknown 不错标。
只读 company_profiles 的既有硬证据,写 company_size_signals;不碰 jobs、不改旧字段。"""
from typing import Optional, Tuple

# 明确档 → 规范 band（只收能无歧义落到单一 band 的写法）
_CLEAR_BAND = {
    '1-100': '<100', '100-500': '100-499', '500-1000': '500-1999',
    '1000-5000': None,  # 跨 2000 分界,占位,由 straddle 逻辑处理
    '5000-1万': '2000+', '1万-5万': '2000+', '5万-10万': '2000+', '10万+': '2000+',
}

def map_headcount_band(raw: Optional[str]) -> Tuple[str, Optional[str]]:
    if not raw:
        return ('unknown', None)
    raw = raw.strip()
    # 已知明确档
    if raw in _CLEAR_BAND and _CLEAR_BAND[raw] is not None:
        return (_CLEAR_BAND[raw], None)
    # 跨 2000 分界的区间 → 不硬归,保留原文
    if raw == '1000-5000':
        return ('unknown', raw)
    return ('unknown', raw if '-' in raw or raw.isdigit() else None)

def map_segment_ownership(segment: Optional[str]) -> Tuple[str, str]:
    if segment == 'foreign':
        return ('外资', 'pending')
    if segment == 'private':
        return ('民营', 'pending')
    if segment == 'soe':
        return ('unknown', 'pending')  # 无法细分央企/地方国企,不硬猜
    return ('unknown', 'unknown')

def map_funding_stage(fs: Optional[str]) -> str:
    if fs == '已上市':
        return '成熟'
    return 'unknown'  # 未上市/未披露 不推初创
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd crawler && python3 -m unittest test_size_signals -v`
Expected: PASS(全部 6 个)

- [ ] **Step 5: 加 seed 运行器(读 company_profiles → upsert signals)**

```python
# 追加到 crawler/size_signals.py
import os, psycopg2

def seed_from_hard_evidence(conn) -> dict:
    """读 company_profiles 全量(分页游标,避免 1000 行截断),按硬证据 upsert signals。"""
    stats = {'seeded': 0, 'band_confirmed': 0, 'ownership_pending': 0, 'unknown': 0}
    with conn.cursor(name='cp_cursor') as cur:  # 服务端游标,不受 1000 行截断影响
        cur.itersize = 500
        cur.execute("select company, headcount_band, funding_stage from company_profiles")
        rows = cur.fetchall()
    with conn.cursor() as w:
        for company, hb, fs in rows:
            band, raw = map_headcount_band(hb)
            stage = map_funding_stage(fs)
            band_status = 'confirmed' if band != 'unknown' else 'unknown'
            if band != 'unknown':
                stats['band_confirmed'] += 1
            else:
                stats['unknown'] += 1
            w.execute("""
                insert into company_size_signals
                  (company, size_band, dev_stage, raw_size_evidence, size_status, source_signal)
                values (%s,%s,%s,%s,%s,'wikidata')
                on conflict (company) do update set
                  size_band=excluded.size_band, dev_stage=excluded.dev_stage,
                  raw_size_evidence=excluded.raw_size_evidence, size_status=excluded.size_status,
                  updated_at=now()
            """, (company, band, stage, raw, band_status))
            stats['seeded'] += 1
    conn.commit()
    return stats

if __name__ == '__main__':
    conn = psycopg2.connect(os.environ['SUPABASE_DB_URL'])
    print(seed_from_hard_evidence(conn))
```

> 注:ownership 的 seed 需 join `sources.segment`(company_profiles 无 segment)。为保持 Task 2 只依赖 company_profiles,ownership seed 放 Task 3 审计里一并做(审计本就要读 sources)。此处只 seed size_band + dev_stage。

- [ ] **Step 6: Commit**

```bash
git add crawler/size_signals.py crawler/test_size_signals.py
git commit -m "feat(tiering): 硬证据保守映射(headcount/segment/funding → 三轴,宁可 unknown)"
```

---

### Task 3: 库存 vs 曝光 只读审计脚本

**Files:**
- Create: `crawler/audit_sme_supply.py`
- Create: `crawler/test_audit_sme_supply.py`

**Interfaces:**
- Consumes: `size_signals.map_segment_ownership`(给 sources.segment 定 ownership)。
- Produces:
  - `bucket_by_output(gtot: int) -> str` 返回 `'A_1000+'/'B_200-999'/'C_50-199'/'D_10-49'/'E_1-9'`。
  - `classify_low_output(company: str, gtot: int, band: str | None) -> str` 对**低产出层(gtot<50)**的公司判"能否确认规模":`band in ('<100','100-499')→'confirmed_small'`;`band in ('500-1999','2000+')→'confirmed_notsmall'`;否则 `'unknown_size'`。
  - `run_audit(hk_conn, sb_conn, cities: list[str]) -> dict` 跨库:HK 取每城市社招池 company→gtot,Supabase 取 company→size_band,Python join,输出每城市 `{confirmed_small, confirmed_notsmall, unknown_size}` 的公司数。**只读,无 --apply。**

- [ ] **Step 1: 写失败测试**

```python
# crawler/test_audit_sme_supply.py
import unittest
from audit_sme_supply import bucket_by_output, classify_low_output

class TestAuditPure(unittest.TestCase):
    def test_bucket_boundaries(self):
        self.assertEqual(bucket_by_output(1000), 'A_1000+')
        self.assertEqual(bucket_by_output(999), 'B_200-999')
        self.assertEqual(bucket_by_output(49), 'D_10-49')
        self.assertEqual(bucket_by_output(9), 'E_1-9')

    def test_low_output_confirmed_small_only_from_hard_band(self):
        # 低产出 + 硬证据小档 → 真小厂
        self.assertEqual(classify_low_output('X', 12, '<100'), 'confirmed_small')
        # 低产出 + 硬证据大档 → 不是小厂(可能招聘冻结的大厂)
        self.assertEqual(classify_low_output('Y', 12, '2000+'), 'confirmed_notsmall')
        # 低产出 + 无规模证据 → 未知(不敢判,这正是命门缺口)
        self.assertEqual(classify_low_output('Z', 12, None), 'unknown_size')
        self.assertEqual(classify_low_output('Z', 12, 'unknown'), 'unknown_size')

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd crawler && python3 -m unittest test_audit_sme_supply -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现审计(纯函数 + 跨库读运行器)**

```python
# crawler/audit_sme_supply.py
"""库存 vs 曝光 只读审计。回答:低产出层里有多少能【确认】是真小厂 / 真大厂 / 未知?
【只读,没有也不会有 --apply】。岗位数只用于分层抽样,绝不据此判规模。"""
import os
from typing import Optional

def bucket_by_output(gtot: int) -> str:
    if gtot >= 1000: return 'A_1000+'
    if gtot >= 200:  return 'B_200-999'
    if gtot >= 50:   return 'C_50-199'
    if gtot >= 10:   return 'D_10-49'
    return 'E_1-9'

def classify_low_output(company: str, gtot: int, band: Optional[str]) -> str:
    if band in ('<100', '100-499'):
        return 'confirmed_small'
    if band in ('500-1999', '2000+'):
        return 'confirmed_notsmall'
    return 'unknown_size'

def run_audit(hk_conn, sb_conn, cities):
    # Supabase: company -> size_band
    with sb_conn.cursor(name='sig') as c:
        c.itersize = 500
        c.execute("select company, size_band from company_size_signals")
        band_map = {co: b for co, b in c.fetchall()}
    report = {}
    for city in cities:
        with hk_conn.cursor() as h:
            h.execute("""
                select company, count(*) from jobs
                where status='active' and char_length(coalesce(summary,''))>=60
                  and location ilike %s and recruitment_category='社招'
                group by company
            """, (f'%{city}%',))
            pool = h.fetchall()
        low = [(co, g) for co, g in pool if g < 50]
        tally = {'confirmed_small': 0, 'confirmed_notsmall': 0, 'unknown_size': 0}
        for co, g in low:
            tally[classify_low_output(co, g, band_map.get(co))] += 1
        report[city] = {'pool_companies': len(pool), 'low_output_companies': len(low), **tally}
    return report

if __name__ == '__main__':
    import psycopg2
    hk = psycopg2.connect(os.environ['JOBS_DATABASE_URL'])
    sb = psycopg2.connect(os.environ['SUPABASE_DB_URL'])
    rep = run_audit(hk, sb, ['北京', '上海', '深圳', '杭州', '广州', '成都'])
    for city, r in rep.items():
        print(city, r)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd crawler && python3 -m unittest test_audit_sme_supply -v`
Expected: PASS(全部)

- [ ] **Step 5: Commit**

```bash
git add crawler/audit_sme_supply.py crawler/test_audit_sme_supply.py
git commit -m "feat(tiering): 库存vs曝光 只读审计脚本(低产出层能否确认真小厂)"
```

---

### Task 4: 跑一遍真数据 + 记录 Plan 2 分叉决策

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-company-tiering-sme-expansion-design.md`(追加"附录 A:v1 验证结果")

**Interfaces:**
- Consumes: Task 1-3 的表 + 脚本。

- [ ] **Step 1: seed 硬证据信号(真库,一次性)**

Run:
```bash
cd "$MAIN_REPO" && set -a && source .env.local && set +a && \
cd crawler && python3 size_signals.py
```
Expected: 打印 `{'seeded': ~1366, 'band_confirmed': ~120, ...}`(band_confirmed 约等于 company_profiles 里 headcount_band 非空数)。

- [ ] **Step 2: 跑库存vs曝光审计(真库)**

Run:
```bash
cd "$MAIN_REPO" && set -a && source .env.local && set +a && \
cd crawler && python3 audit_sme_supply.py
```
Expected: 每城市打印 `{pool_companies, low_output_companies, confirmed_small, confirmed_notsmall, unknown_size}`。

- [ ] **Step 3: 判读并写附录 + 决策**

把真实数字写进 spec 附录 A,并按下面规则给出 Plan 2 分叉(**必须双向报数,不许只报净值**):
- 若 `unknown_size` 在低产出层占绝对多数(预期会,因硬证据只覆盖大厂)→ 结论:"硬证据不足以回答库存vs曝光 → Plan 2 必须先建 LLM 证据抽取器(spec §4),在**有界样本**上跑 + 分层盲测,才能量化真小厂库存。" 这是 eyes-open 地进入 Plan 2,而不是盲目扩源。
- 若 `confirmed_small` 已有可观数量 → 结论倾向"曝光问题" → Plan 2 优先做标签筛选 + 结果分散(spec §5.2),用已确认小厂验证曝光改善。
- 若两者都很少且低产出层很小 → 结论倾向"库存问题" → Plan 2 优先建 SME 候选台账 + 定向扩源(spec §5.1)。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-15-company-tiering-sme-expansion-design.md
git commit -m "docs(tiering): v1 库存vs曝光 验证结果 + Plan 2 分叉决策(附录 A)"
```

---

## 自检(写完计划后对着 spec 复查)

- **Spec 覆盖**:本计划实现 spec §7 步骤 1(库存vs曝光,Task 3+4)+ §3 三轴地基的**硬证据部分**(Task 1+2)+ §0 旧字段不可复用(新表隔离)。**故意不实现**:§4 LLM 抽取器、§5 扩源/结果分散、§3.1 筛选公司名集过滤、前台标签——全部留给 Plan 2,由 Task 4 的数字决定方向。这是 spec §9 明确要求的"先拿数再投基建"。
- **占位符扫描**:无 TBD;所有 step 带真实 SQL/代码/命令。
- **类型一致**:`map_headcount_band` 返回 `(band, raw)` 二元组在 Task 2 定义、Task 2 seed 里消费一致;`classify_low_output` 的 band 取值域与 `company_size_signals.size_band` 的 check 一致;审计 join 键统一用 `company` 文本(spec §3.2 已标注此为 v1 已知妥协,集团/子公司同名风险记在 unknown 里、不误升 confirmed)。
- **已知边界(诚实)**:审计用 `company` 文本 join,存在同名/子公司错配风险(spec §3.2)——但本计划只用它**分桶计数**、不改任何 status,错配只影响统计精度、不产生不可逆后果;真正的实体对齐留给 Plan 2。
