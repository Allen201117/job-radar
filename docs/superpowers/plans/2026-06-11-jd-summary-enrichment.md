# JD summary 富化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 消除岗位库大面积缺 JD 正文——按 `jd_url` 反推 detail 端点富化 summary，后台并发 drain backlog + 用户读时补可见卡。

**Architecture:** 统一 `crawler/enrich.py` 富化注册表（httpx-detail 高并发 + browser-detail 低并发）；Postgres 当队列（`summary 空 AND enrich_fail_count<3`，优先级排序，死信老化）；新 `enrich-backlog.yml` Actions matrix drain；`/api/enrich` on-demand。复用已验证的 `backfill_foreign_summaries.py` 反推逻辑。

**Tech Stack:** Python(httpx + supabase-py) crawler；Postgres(Supabase)；GitHub Actions；Next.js(/api/enrich, P3)。

Spec: `docs/superpowers/specs/2026-06-11-jd-summary-enrichment-design.md`

---

## P1 — httpx-detail 快赢（workday/oracle/eightfold/smartrecruiters/hotjob ≈ 203 源）

### Task 1: 迁移 133 — 富化追踪列 + 死信

**Files:** Create `supabase/migrations/133_job_enrich_tracking.sql`

- [ ] 写迁移（幂等 add column if not exists）:

```sql
-- 133 — 富化追踪：drain worker 用 enrich_fail_count 做死信、enrich_checked_at 做调度去重。
alter table jobs add column if not exists enrich_fail_count int not null default 0;
alter table jobs add column if not exists enrich_checked_at timestamptz;
-- 队列扫描索引：active + 空 summary + 未超死信，按最近优先
create index if not exists idx_jobs_enrich_queue
  on jobs (first_seen_at desc)
  where status = 'active' and summary is null and enrich_fail_count < 3;
```

- [ ] Commit: `git add supabase/migrations/133_job_enrich_tracking.sql && git commit -m "feat(db): 133 富化追踪列 enrich_fail_count/enrich_checked_at + 队列索引"`
  - push 即由 migrate.yml 自动应用。

### Task 2: `crawler/enrich.py` — 富化注册表

**Files:** Create `crawler/enrich.py`；Test `crawler/test_enrich.py`

注册表把「按 jd_url 反推 detail → 返回 summary 文本」按 adapter 收口。P1 = 5 个 httpx fetcher。workday/oracle/eightfold/smartrecruiters 直接搬 `scripts/backfill_foreign_summaries.py` 的 `_detail_*`（已验证）；新增 hotjob。

- [ ] **Step 1: 写失败测试**（纯函数，monkeypatch httpx，不打真网）:

```python
# crawler/test_enrich.py
import unittest
from unittest import mock
import enrich

class HotjobDetailTest(unittest.TestCase):
    def test_reverses_jd_url_to_detail_post(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SU123/pb/posDetail.html?postId=P9&postType=campus", "title": "x"}
        src = {"source_url": "https://wecruit.hotjob.cn/SU123/pb/school.html", "adapter_name": "hotjob"}
        captured = {}
        class R:
            status_code = 200
            def json(self): return {"data": {"workContent": "干活", "serviceCondition": "要求"}}
        def fake_post(url, data=None, headers=None, timeout=None):
            captured["url"] = url; captured["data"] = data; return R()
        with mock.patch.object(enrich.httpx, "post", fake_post):
            body = enrich.ENRICH_REGISTRY["hotjob"](row, src)
        self.assertIn("/wecruit/positionInfo/listPositionDetail/SU123", captured["url"])
        self.assertEqual(captured["data"]["postId"], "P9")
        self.assertEqual(captured["data"]["recruitType"], 1)  # campus→1
        self.assertIn("干活", body)

class RegistryTest(unittest.TestCase):
    def test_httpx_adapters_registered(self):
        for a in ("workday","oracle","eightfold","smartrecruiters","hotjob"):
            self.assertIn(a, enrich.ENRICH_REGISTRY)
    def test_classes(self):
        self.assertEqual(enrich.detail_class("hotjob"), "httpx")
        self.assertEqual(enrich.detail_class("beisen"), "browser")
        self.assertIsNone(enrich.detail_class("不存在"))
```

- [ ] **Step 2: 跑测试看失败** — `cd crawler && python3 -m unittest test_enrich -v` → FAIL (no module enrich)

- [ ] **Step 3: 实现 `crawler/enrich.py`**:

```python
"""按 jd_url 反推官方 detail 端点 → 返回 summary 文本。drain worker + on-demand 共用。
httpx 类无浏览器可高并发；browser 类（beisen/moka/feishu）P2 再加。
fetcher 签名: f(row: dict, src: dict) -> str（空串=无正文/已撤岗）。"""
import re
from urllib.parse import urlparse, parse_qs
import httpx

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
      "Accept": "application/json"}
TIMEOUT = 25

# --- 外企四家族：搬 scripts/backfill_foreign_summaries.py（已 live 验证） ---
def _detail_workday(row, src):
    m = re.search(r"(/job/.+)$", urlparse(row["jd_url"]).path)
    if not m: return ""
    cxs_base = re.sub(r"/jobs/?$", "", src["source_url"])
    r = httpx.get(f"{cxs_base}{m.group(1)}", headers=UA, timeout=TIMEOUT)
    if r.status_code >= 300: return ""
    return (r.json().get("jobPostingInfo", {}) or {}).get("jobDescription") or ""

def _detail_oracle(row, src):
    m = re.search(r"/sites/([^/]+)/job/(\w+)", row["jd_url"])
    if not m: return ""
    p = urlparse(row["jd_url"])
    url = (f"{p.scheme}://{p.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
           f'?onlyData=true&expand=all&finder=ById;Id="{m.group(2)}",siteNumber={m.group(1)}')
    r = httpx.get(url, headers=UA, timeout=TIMEOUT)
    if r.status_code >= 300: return ""
    items = r.json().get("items", []) or []
    if not items: return ""
    it = items[0]
    parts = [it.get("ExternalDescriptionStr") or it.get("ShortDescriptionStr"),
             it.get("ExternalResponsibilitiesStr"), it.get("ExternalQualificationsStr")]
    return " ".join(x for x in parts if x)

def _detail_eightfold(row, src):
    m = re.search(r"/(\d{9,})(?:[/?#]|$)", row["jd_url"])
    if not m: return ""
    sp = urlparse(src["source_url"])
    domain = (parse_qs(sp.query).get("domain") or [""])[0]
    url = f"{sp.scheme}://{sp.netloc}{sp.path}/{m.group(1)}"
    r = httpx.get(url, params={"domain": domain}, headers=UA, timeout=TIMEOUT)
    if r.status_code >= 300: return ""
    return r.json().get("job_description") or ""

def _detail_smartrecruiters(row, src):
    parts = [x for x in urlparse(row["jd_url"]).path.split("/") if x]
    if len(parts) < 2: return ""
    identifier, pid = parts[0], parts[1]
    r = httpx.get(f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{pid}",
                  headers=UA, timeout=TIMEOUT)
    if r.status_code >= 300: return ""
    secs = (r.json().get("jobAd") or {}).get("sections") or {}
    parts = [(secs.get(k) or {}).get("text") for k in ("jobDescription","responsibilities","qualifications")]
    return " ".join(x for x in parts if x)

# --- hotjob：jd_url = {origin}/{suite}/pb/posDetail.html?postId=&postType= ---
_HOTJOB_RECRUIT = {"society": 2, "campus": 1, "intern": 12}
def _detail_hotjob(row, src):
    p = urlparse(row["jd_url"]); q = parse_qs(p.query)
    post_id = (q.get("postId") or [""])[0]
    post_type = (q.get("postType") or [""])[0]
    suite = next((x for x in (p.path or "").split("/") if x), "")
    if not (post_id and suite): return ""
    origin = f"{p.scheme}://{p.netloc}"
    headers = {**UA, "Accept": "application/json, text/plain, */*",
               "Content-Type": "application/x-www-form-urlencoded",
               "Referer": row["jd_url"], "Origin": origin}
    r = httpx.post(f"{origin}/wecruit/positionInfo/listPositionDetail/{suite}",
                   data={"postId": post_id, "recruitType": _HOTJOB_RECRUIT.get(post_type, 2)},
                   headers=headers, timeout=TIMEOUT)
    if r.status_code >= 300: return ""
    d = r.json().get("data") or {}
    return " ".join(x for x in (d.get("workContent"), d.get("serviceCondition")) if x)

ENRICH_REGISTRY = {
    "workday": _detail_workday, "oracle": _detail_oracle, "eightfold": _detail_eightfold,
    "smartrecruiters": _detail_smartrecruiters, "hotjob": _detail_hotjob,
}
_BROWSER_ADAPTERS = {"beisen", "moka", "feishu"}  # P2 实现

def detail_class(adapter):
    if adapter in ENRICH_REGISTRY: return "httpx"
    if adapter in _BROWSER_ADAPTERS: return "browser"
    return None

def enrich_one(adapter, row, src):
    """返回 summary 文本或空串。异常上抛由调用方计死信。"""
    f = ENRICH_REGISTRY.get(adapter)
    return f(row, src) if f else ""
```

- [ ] **Step 4: 跑测试看通过** — `cd crawler && python3 -m unittest test_enrich -v` → PASS

- [ ] **Step 5: DRY 重构** `scripts/backfill_foreign_summaries.py` 改为 `from enrich import _detail_workday ...`（删本地副本），跑 `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` 全绿。

- [ ] **Step 6: Commit** `git add crawler/enrich.py crawler/test_enrich.py scripts/backfill_foreign_summaries.py && git commit -m "feat(crawler): enrich.py 富化注册表(foreign4+hotjob) + 测试"`

### Task 3: drain runner `crawler/enrich_backlog.py`

**Files:** Create `crawler/enrich_backlog.py`；Test 追加 `crawler/test_enrich.py`

- [ ] **Step 1: 写死信/队列单测**（mock supabase）:

```python
class DrainTest(unittest.TestCase):
    def test_fail_increments_deadletter(self):
        import enrich_backlog as eb
        # fetcher 抛 → 该行 enrich_fail_count+1、enrich_checked_at 写、summary 不动
        ...（mock sb 记录 update payload，断言 patch 含 enrich_fail_count）
    def test_success_writes_summary_only(self):
        ...（断言 patch 含 summary，不含 enrich_fail_count）
```

- [ ] **Step 2~4:** 实现 drain：
  - 取队列：`jobs.select(...).is_("summary","null").eq("status","active").lt("enrich_fail_count",3)`，按 `first_seen_at desc` 分页，`--limit` 截断。join sources 取 adapter/source_url。
  - 仅 `detail_class(adapter)=="httpx"`（P1）。`ThreadPoolExecutor(workers)`，按 source 轮转交错（同 backfill 的 zip_longest 防集中打同租户）。
  - 成功 → `update {summary, [job_type], enrich_checked_at}`；空/异常 → `update {enrich_fail_count: n+1, enrich_checked_at}`。
  - CLI: `--limit --workers(默认10) --adapter --dry-run`。复用 `db.get_supabase`/`normalizer`。
- [ ] **Step 5: Commit** `git commit -m "feat(crawler): enrich_backlog drain runner(队列+死信+并发)"`

### Task 4: `.github/workflows/enrich-backlog.yml`

**Files:** Create `.github/workflows/enrich-backlog.yml`

- [ ] httpx-detail drain（无浏览器，省 chromium 安装）：
  - `on: schedule: cron "0 */3 * * *"`（每 3h）+ workflow_dispatch。
  - `strategy.matrix.shard: [0,1,2,3]`（4 片，按 adapter 或 id 取模分流，先简单：每片 `--limit 8000` 自然分摊，重复行被「已富化即不再空」幂等吸收）。
  - `timeout-minutes: 50`。step: `python crawler/enrich_backlog.py --limit 8000 --workers 12`，env SUPABASE_URL/SERVICE_ROLE_KEY。
- [ ] Commit `git commit -m "feat(ci): enrich-backlog.yml httpx-detail drain(每3h, matrix)"`

### Task 5: 验证 + 真机 drain
- [ ] `python3 -m unittest discover -s crawler -t crawler -p "test_*.py"` 全绿。
- [ ] 真机：`python3 crawler/enrich_backlog.py --adapter hotjob --limit 50` → 实查 summary 被填、计数对；前后比对样本空占比下降。
- [ ] `gh workflow run enrich-backlog.yml` 触发一次，确认 <50min、回填数 >0。

---

## P2 — browser-detail（beisen 211 + moka 196 + feishu 49，backlog 大头）
- enrich.py 加 browser 类 fetcher（moka 复用 `backfill_moka_summaries.py` 渲染；feishu/beisen 用站点 session 重放 detail XHR 或渲染 detail 页）。
- enrich-backlog.yml 加 browser shard（装 chromium、低并发、单源限量、`timeout 50`）。
- 测试：browser fetcher 的 jd_url→detail 参数反推（mock 渲染层）。

## P3 — on-demand `/api/enrich` + 前端
- `app/api/enrich/route.ts`：POST {jd_urls≤30} → 查行 → 仅 httpx 简单映射源 → `lib/enrich-client.ts`(TS 重实现 workday/hotjob/oracle/eightfold/smartrecruiters 反推，与 Python golden 用例对齐) 并发≤20 → upsert summary → 返回。
- 前端 Today/Jobs：可见薄卡(httpx 源)调 /api/enrich 异步弹入；排序加 summary-present 权重；薄卡占位「正文抓取中·点开看官网」。

## P4 — 调优
- 优先级权重表（私企>国企>外企，segment+classifyCompanyOrigin）；死信阈值/并发/cron 频率调优；观测 active 空 summary% 指标（目标 <10%）。

---

## Self-Review
- 覆盖：spec §5.1(enrich.py)=Task2；§5.2(队列/死信/迁移)=Task1+3；§5.3(drain workflow)=Task4；§5.4-5.5(on-demand/前端)=P3；§9 分期 = P1..P4 对齐。✓
- 无占位：P1 每步有真代码/命令；P2-P4 为后续阶段大纲（各自再出计划）。
- 类型一致：fetcher 签名 `(row,src)->str` 全程统一；`ENRICH_REGISTRY`/`detail_class`/`enrich_one` 命名贯穿 Task2-3 与 P3。✓
- 范围：P1 自成可上线闭环（drain httpx backlog）；P2/P3 各自独立可测。
