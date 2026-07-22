# 校招洞察 P3（爬虫提速版）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给校招专区补「今年精确网申日期 + 提前批/正式批时间差」，主源换成「官方校招页 httpx 并发直取」（不吃搜索额度、分钟级），并把公司洞察抽屉从岗位卡里外露到公司卡级。

**Architecture:** 复用 P2 现成「抽取→判官→官方源门→幂等写 RCO」骨架，只把数据源从慢搜索换成 httpx 直取官方校招页；精确日期写 `recruitment_cycle_observations`（迁移 182 的 `date_start/date_end/time_expr_type` 已预留，**不新建表、不新迁移**）。前端抽屉外露复用现成 `CompanyInsightDrawer` + `lib/insight-client`。

**Tech Stack:** Python crawler（httpx + selectolax + concurrent.futures 并发）；Next.js/React 前端；Supabase（sources/company_profiles/RCO）；SiliconFlow LLM（`insight_engine.chat_json`/`judge_claim`）；node --test + python unittest。

## Global Constraints

- **红线·宁缺不编**：精确日期 `time_expr_type='精确日期'`/`'日期范围'` 只写「官方招聘域名 grounding + 判官 entailment」的；拿不到官方证据一律不写（不 draft 冒充、不编日期）。
- **官方源门复用**：`crawler/official_gate.py` 的 `official_hosts_from_sources` / `is_official_grounding` / `decide_cycle_status` / `registrable_host` 原样复用，不改其语义。
- **批次 HC 硬差异砍**：数据里无批次标签（全库 `title ~ '正式批'` 命中 0），P3 不做 HC 差异；批次差异只做「时间」差异。
- **快路① 不写 RCO**：自有岗位 deadline 派生**填不了 RCO 必填的 `batch`（NOT NULL + 枚举）** → 猜批次=编。快路① 只做「公司级·据在招岗位约 X 截止」的**读时提示**，不进 RCO、不猜批次、无迁移。
- **grad_class 绑定**：所有 RCO 写入绑 `current_cohort(now)` 的届别 + `valid_until`；`verified` 事实不可覆盖（同 (season,batch,event) key 已有 verified 则跳过）。
- **CI 不吃搜索额度**：快路② 全程 httpx 抓公开官方页，不调 `search_router`；SiliconFlow 只用于抽取 + 判官。
- **测试约束**：纯函数走 `node --test tests/*.test.js`（TS lib 用相对路径 import，禁 `@/` 运行时别名）与 `python3 -m unittest`（crawler，不打真实网络）；I/O/UI 走 build + 浏览器/CI 验证。
- **提交前回归**：`node --test tests/*.test.js && python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && npm run build && git diff --check`。

---

## File Structure

**新建：**
- `crawler/campus_official_extract.py` — 精确日期 LLM writer 提示 + 纯函数解析器（产 `date_start/date_end` + 回填 month）。
- `crawler/campus_official_pages.py` — 官方校招页 URL 解析 + httpx 抓取 + 日期信号预筛 + HTML→text（纯函数 + I/O）。
- `crawler/campus_official_backlog.py` — 快路② drain 编排（并发抓 → 抽 → 判官 → 官方门 → 写 RCO）。
- `crawler/test_campus_official_extract.py` / `crawler/test_campus_official_pages.py` — crawler 单测。
- `.github/workflows/campus-official-pages.yml` — 每日 cron（并发 httpx，不吃搜索额度）。
- `tests/recruitment-cycle-p3.test.js` — 前端纯函数单测（精确日期展示 + 时间差 + deadline 清洗）。

**修改：**
- `lib/recruitment-cycle.ts` — 加 `campusPreciseDates` / `campusBatchTimingGap` / `cleanCampusDeadlineMs` 三个纯函数。
- `app/campus/page.tsx` — 装配精确日期/时间差/清洗后 deadline 传给客户端。
- `app/campus/campus-client.tsx` — ① 公司卡级「公司洞察」按钮开抽屉；② 渲染「今年精确」行 + 「据在招岗位」提示。
- `lib/recruitment-cycle-store.ts`（按需）— 确认 select 带回 `date_start,date_end,time_expr_type`。

---

## Phase P3a — 公司洞察抽屉外露（前端，独立小改，先落）

### Task 1: 校招公司卡加「公司洞察」按钮 + 抽屉

**Files:**
- Modify: `app/campus/campus-client.tsx`（import 段 + 组件 state + 卡面按钮区）
- 参考（勿改）：`components/JobCard.tsx:120-190,746-750`（现成 insightBadge + 微批拉取 + 抽屉挂载写法）、`lib/insight-client.ts:116-153`

**Interfaces:**
- Consumes: `CompanyInsightDrawer`（props `{ company: string; open: boolean; onClose: () => void }`，自取数）；`lib/insight-client` 的 `requestInsightAvailability(company: string): void` / `getCachedAvailability(company: string): InsightAvailability | null` / `subscribeAvailability(fn: () => void): () => void`；`InsightAvailability`（含 `real: number` 实录数 + 派生标记）。
- Produces: 无（纯 UI 装配）。

- [ ] **Step 1: 加 import**

在 `campus-client.tsx` 顶部 import 段补：
```tsx
import CompanyInsightDrawer from "@/components/CompanyInsightDrawer";
import {
  requestInsightAvailability,
  getCachedAvailability,
  subscribeAvailability,
  type InsightAvailability,
} from "@/lib/insight-client";
```

- [ ] **Step 2: 组件内加抽屉 state + 可用性订阅**

在 `CampusClient` 函数体内（`const [mode, ...]` 附近）加：
```tsx
// 公司洞察抽屉（P3a 外露）：公司卡级只拉一次可用性（比每个 JobCard 各拉更省），暂无实录/派生的公司不给点。
const [insightCompany, setInsightCompany] = useState<string | null>(null);
const [, forceAvailTick] = useState(0);
useEffect(() => {
  cards.forEach((c) => requestInsightAvailability(c.company));
  const unsub = subscribeAvailability(() => forceAvailTick((n) => n + 1));
  return unsub;
}, [cards]);
```

- [ ] **Step 3: 卡面加按钮（放「展开岗位」旁）**

在公司卡的按钮区（`campus-client.tsx` 现「展开岗位」`<button>` 之后、同一 flex 容器内）插入：
```tsx
{(() => {
  const avail = getCachedAvailability(card.company);
  // 有实录(real>0)或岗位聚合派生才显按钮；纯空（无任何洞察）不给点，避免空抽屉。
  if (!avail || (!avail.real && !avail.derived)) return null;
  return (
    <button
      type="button"
      onClick={() => setInsightCompany(card.company)}
      className="mt-1 inline-flex items-center justify-center gap-1.5 self-start rounded-full border border-black/[0.08] bg-white/70 px-3.5 py-1.5 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#d9d0c2] dark:hover:bg-white/[0.08]"
    >
      {avail.real > 0 ? `公司洞察 ${avail.real}` : "公司洞察 · 岗位聚合"}
    </button>
  );
})()}
```
> 注：`InsightAvailability` 的 `derived` 字段名以 `lib/insight-client.ts:116-125` 的 interface 为准；若字段名不同，按实际字段调整判空条件（读该文件确认，勿凭记忆）。

- [ ] **Step 4: 组件末尾挂抽屉**

在 `CampusClient` return 的最外层 `<div>` 末尾（`<SaveToast .../>` 之后）加：
```tsx
{insightCompany && (
  <CompanyInsightDrawer
    company={insightCompany}
    open={!!insightCompany}
    onClose={() => setInsightCompany(null)}
  />
)}
```

- [ ] **Step 5: build 验证**

Run: `npm run build`
Expected: 编译通过、无 TS 报错（`CampusCardData` 已有 `company`）。

- [ ] **Step 6: 浏览器验证（preview）**

用 preview 起 dev（`.claude/launch.json` 的 dev 配置），登录测试账号 → `/campus` → 有洞察的公司卡出现「公司洞察 N」按钮，点开弹出抽屉、显该公司分区，关闭正常。截图留证。

- [ ] **Step 7: Commit**

```bash
git add app/campus/campus-client.tsx
git commit -m "feat(campus): 公司洞察抽屉外露到公司卡级（P3a）"
```

---

## Phase P3b — 快路② 官方校招页精确日期抽取器（crawler，主力）

### Task 2: 精确日期抽取器（LLM 提示 + 纯函数解析）

**Files:**
- Create: `crawler/campus_official_extract.py`
- Test: `crawler/test_campus_official_extract.py`
- 参考（勿改）：`crawler/campus_cycle_extract.py`（月份版写法）

**Interfaces:**
- Produces:
  - `build_official_messages(company: str, page_text: str) -> list[dict]` — chat_json 用 messages（单一官方页文本作唯一来源）。
  - `parse_precise_claims(llm_out, now: datetime) -> list[dict]` — 纯函数，返回合法 claim：`{season, batch, event, date_start: 'YYYY-MM-DD', date_end: 'YYYY-MM-DD'|None, month_start: int, month_end: int|None, value_text: str, quote: str}`；非法条丢弃、不 raise。日期须在 `[now-60d, now+550d]` 内（滤 `3000-01-01` 等垃圾 + 往年过期日期）。

- [ ] **Step 1: 写失败测试**

`crawler/test_campus_official_extract.py`:
```python
import unittest
from datetime import datetime, timezone
from campus_official_extract import parse_precise_claims

NOW = datetime(2026, 7, 22, tzinfo=timezone.utc)


class ParsePreciseClaims(unittest.TestCase):
    def _one(self, **kw):
        base = {"season": "秋招", "batch": "正式批", "event": "截止",
                "date_start": "2026-09-10", "date_end": None,
                "value_text": "网申9月10日截止", "quote": "网申截止时间：2026年9月10日"}
        base.update(kw)
        return {"claims": [base]}

    def test_valid_precise_date_derives_month(self):
        out = parse_precise_claims(self._one(), NOW)
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c["date_start"], "2026-09-10")
        self.assertEqual(c["month_start"], 9)      # 从日期回填 month
        self.assertIsNone(c["month_end"])

    def test_date_range_fills_both_months(self):
        out = parse_precise_claims(
            self._one(date_start="2026-08-15", date_end="2026-09-10",
                      value_text="网申8月15日–9月10日"), NOW)
        self.assertEqual(out[0]["month_start"], 8)
        self.assertEqual(out[0]["month_end"], 9)

    def test_reject_garbage_far_future(self):
        self.assertEqual(parse_precise_claims(self._one(date_start="3000-01-01"), NOW), [])

    def test_reject_past_cycle_date(self):
        self.assertEqual(parse_precise_claims(self._one(date_start="2025-09-10"), NOW), [])

    def test_reject_bad_enum(self):
        self.assertEqual(parse_precise_claims(self._one(batch="社招"), NOW), [])

    def test_reject_missing_quote(self):
        self.assertEqual(parse_precise_claims(self._one(quote=""), NOW), [])

    def test_reject_bad_date_format(self):
        self.assertEqual(parse_precise_claims(self._one(date_start="2026/9/10"), NOW), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd crawler && python3 -m unittest test_campus_official_extract -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'campus_official_extract'`）

- [ ] **Step 3: 写实现**

`crawler/campus_official_extract.py`:
```python
"""校招今年精确日期抽取（快路② P3b）—— LLM writer 提示 + 纯函数解析。

数据源是单一「公司官方校招页」文本（唯一来源），故不需 source_idx。writer 只抽页面里
**明确写出精确日期**的批次网申/截止时间；parse_precise_claims 纯函数做枚举/日期格式/
日期区间合理性硬校验（滤 3000-01-01 垃圾 + 往年过期日期），并从日期回填 month（兼容
现成 campusTimelineSummary 的月份口径）。宁缺不编：拿不准/无精确日期的条一律丢。
"""
import re
from datetime import timedelta

_SEASONS = {"秋招", "春招"}
_BATCHES = {"提前批", "正式批", "补录", "实习转正"}
_EVENTS = {"开放", "截止", "黄金期", "结束"}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

WRITER_SYS = (
    "你是校招网申日期抽取助手，只依据【给定的公司官方校招页原文】抽取该公司**今年当季校招**"
    "各批次的**精确网申/截止日期**。硬约束：①每条结论必须能在原文找到明确日期支撑，给出不超过"
    "60字的引用片段 quote；②字段：season(秋招/春招)、batch(提前批/正式批/补录/实习转正)、"
    "event(开放/截止/黄金期/结束)、date_start(YYYY-MM-DD)、date_end(YYYY-MM-DD，无区间则为 null)、"
    "value_text(展示串，如「网申9月10日截止」)；③原文没写明确到日的日期 / 是往年的 / 拿不准 → 不要"
    "输出该条，宁缺毋滥；④禁编造原文没有的日期。只输出 JSON：{\"claims\":[{...}]}。"
)


def build_official_messages(company, page_text):
    """拼 chat_json 用 messages。page_text: 官方校招页正文（已 HTML→text 截断）。"""
    user = (
        f"公司：{company}\n\n"
        f"下面是该公司官方校招页原文，请抽取今年当季校招各批次的精确网申/截止日期：\n\n"
        f"{str(page_text or '')[:6000]}"
    )
    return [
        {"role": "system", "content": WRITER_SYS},
        {"role": "user", "content": user},
    ]


def _valid_iso_in_window(s, now):
    if not isinstance(s, str) or not _ISO.match(s):
        return None
    try:
        from datetime import datetime
        d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=now.tzinfo)
    except ValueError:
        return None
    if d < now - timedelta(days=60) or d > now + timedelta(days=550):
        return None  # 滤 3000-01-01 垃圾 + 往年过期日期
    return d


def parse_precise_claims(llm_out, now):
    """校验 LLM 输出，返回合法精确日期 claim（纯函数，不打网络）。非法条丢弃、不 raise。"""
    claims = llm_out.get("claims") if isinstance(llm_out, dict) else (
        llm_out if isinstance(llm_out, list) else None)
    out = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        if c.get("season") not in _SEASONS or c.get("batch") not in _BATCHES or c.get("event") not in _EVENTS:
            continue
        ds = _valid_iso_in_window(c.get("date_start"), now)
        if ds is None:
            continue
        de_raw = c.get("date_end")
        if de_raw in (None, "", ds.strftime("%Y-%m-%d")):
            de = None
        else:
            de_d = _valid_iso_in_window(de_raw, now)
            if de_d is None:
                continue
            de = de_raw
        value_text = str(c.get("value_text") or "").strip()
        quote = str(c.get("quote") or "").strip()
        if not value_text or not quote:
            continue  # 宁缺不编：展示串 + 引用片段必须齐全
        out.append({
            "season": c["season"], "batch": c["batch"], "event": c["event"],
            "date_start": ds.strftime("%Y-%m-%d"),
            "date_end": de,
            "month_start": ds.month,
            "month_end": (int(de[5:7]) if de else None),
            "value_text": value_text,
            "quote": quote[:200],
        })
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd crawler && python3 -m unittest test_campus_official_extract -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add crawler/campus_official_extract.py crawler/test_campus_official_extract.py
git commit -m "feat(campus): 官方校招页精确日期抽取器（快路② P3b）"
```

### Task 3: 官方校招页 URL 解析 + 抓取 + 日期信号预筛

**Files:**
- Create: `crawler/campus_official_pages.py`
- Test: `crawler/test_campus_official_pages.py`
- 参考（勿改）：`crawler/official_gate.py`（`is_official_grounding`）

**Interfaces:**
- Consumes: `official_gate.is_official_grounding(url, official_hosts)`。
- Produces:
  - `official_campus_urls(source_rows: list[dict], official_hosts: set, cap=5) -> list[str]` — 候选官方校招页 URL（去重、封顶；原始 source_url 优先，再补 host + 常见 campus 路径）。
  - `has_date_signal(html: str, min_len=4000) -> bool` — 廉价预筛：长度 ≥min_len（滤 SPA 空壳）且含日期信号正则。
  - `html_to_text(html: str, cap=6000) -> str` — selectolax 提正文、压空白、截断。
  - `fetch_first_with_signal(urls: list[str], timeout=12) -> tuple[str|None, str]` — I/O：顺序抓，返回 `(命中信号的 url 或 None, 该页 text)`；全不命中返回 `(None, "")`。**不在单测里打真实网络。**

- [ ] **Step 1: 写失败测试（纯函数）**

`crawler/test_campus_official_pages.py`:
```python
import unittest
from campus_official_pages import official_campus_urls, has_date_signal, html_to_text


class OfficialCampusUrls(unittest.TestCase):
    def test_prefers_source_url_then_host_variants(self):
        rows = [{"source_url": "https://jobs.bytedance.com/campus/position"}]
        hosts = {"jobs.bytedance.com"}
        urls = official_campus_urls(rows, hosts, cap=5)
        self.assertEqual(urls[0], "https://jobs.bytedance.com/campus/position")
        self.assertIn("https://jobs.bytedance.com/campus", urls)
        self.assertLessEqual(len(urls), 5)

    def test_dedup_and_cap(self):
        rows = [{"source_url": "https://jobs.bytedance.com/campus"}]
        urls = official_campus_urls(rows, {"jobs.bytedance.com"}, cap=3)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertLessEqual(len(urls), 3)

    def test_no_hosts_empty(self):
        self.assertEqual(official_campus_urls([], set()), [])


class HasDateSignal(unittest.TestCase):
    def test_spa_shell_rejected_by_length(self):
        self.assertFalse(has_date_signal("<html>网申 9月10日</html>", min_len=4000))

    def test_ssr_page_with_date_accepted(self):
        html = "x" * 5000 + "网申截止时间 2026年9月10日"
        self.assertTrue(has_date_signal(html, min_len=4000))

    def test_long_page_without_date_rejected(self):
        self.assertFalse(has_date_signal("y" * 5000, min_len=4000))


class HtmlToText(unittest.TestCase):
    def test_strips_tags_and_blank_lines(self):
        t = html_to_text("<div>网申时间</div>\n\n<p>9月10日</p>", cap=6000)
        self.assertIn("网申时间", t)
        self.assertIn("9月10日", t)
        self.assertNotIn("<div>", t)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd crawler && python3 -m unittest test_campus_official_pages -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

`crawler/campus_official_pages.py`:
```python
"""官方校招页抓取工艺（快路② P3b）—— URL 解析 + httpx 抓取 + 日期信号预筛 + HTML→text。

诚实留白：SPA 空壳（腾讯 1.7KB / 百度 2.8KB 等）靠长度门直接淘汰、不喂 LLM；SSR 有日期
信号的（字节 campus 页 819KB）才进抽取。全程抓公开官方页，不吃搜索额度。
"""
import re

import httpx
from selectolax.parser import HTMLParser

from official_gate import is_official_grounding

_COMMON_CAMPUS_PATHS = ("/campus", "/campus.html", "")
_DATE_SIGNAL = re.compile(
    r"网申|投递(时间|截止)|报名(时间|截止)|截止(时间|日期)|\d{1,2}月\d{1,2}[日号]|20(2[6-9]|3\d)[年./\-]\d{1,2}")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")


def official_campus_urls(source_rows, official_hosts, cap=5):
    """候选官方校招页 URL（去重、封顶）。原始 source_url（落在官方 host 上的）优先，
    再补 host + 常见 campus 路径变体。"""
    urls, seen = [], set()

    def add(u):
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    for r in source_rows or []:
        su = (r or {}).get("source_url") or ""
        if su and is_official_grounding(su, official_hosts):
            add(su)
    for h in sorted(official_hosts or []):
        for p in _COMMON_CAMPUS_PATHS:
            add(f"https://{h}{p}")
    return urls[:max(0, int(cap or 0))]


def has_date_signal(html, min_len=4000):
    """廉价预筛：长度门滤 SPA 空壳 + 日期信号正则。二者皆满足才算有信号。"""
    if not html or len(html) < min_len:
        return False
    return bool(_DATE_SIGNAL.search(html))


def html_to_text(html, cap=6000):
    if not html:
        return ""
    try:
        text = HTMLParser(html).text(separator="\n")
    except Exception:
        text = html
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)[:cap]


def fetch_first_with_signal(urls, timeout=12):
    """顺序抓候选 URL，返回第一个有日期信号的 (url, text)；全不命中返回 (None, "")。
    永不抛（单公司抓取异常不能拖垮整批）。**单测不打真实网络。**"""
    headers = {"User-Agent": _UA}
    for u in urls or []:
        try:
            resp = httpx.get(u, headers=headers, timeout=timeout, follow_redirects=True)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        html = resp.text or ""
        if has_date_signal(html):
            return u, html_to_text(html)
    return None, ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd crawler && python3 -m unittest test_campus_official_pages -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add crawler/campus_official_pages.py crawler/test_campus_official_pages.py
git commit -m "feat(campus): 官方校招页 URL 解析+抓取+日期信号预筛（快路② P3b）"
```

### Task 4: 快路② drain 编排（抓→抽→判官→官方门→写 RCO）

**Files:**
- Create: `crawler/campus_official_backlog.py`
- 参考（勿改）：`crawler/campus_cycle_backlog.py`（骨架 + `current_cohort` / `_existing_status_by_key` / `fetch_covered_company_names` / `select_cycle_targets`）

**Interfaces:**
- Consumes: `db.get_supabase` / `db.fetch_all_rows`；`insight_backlog.fetch_one_company`；`insight_engine.chat_json/judge_claim/llm_config/llm_run_unhealthy/llm_run_health/reset_llm_health`；`official_gate.official_hosts_from_sources/is_official_grounding/is_entailment/decide_cycle_status`；`campus_official_extract.build_official_messages/parse_precise_claims`；`campus_official_pages.official_campus_urls/fetch_first_with_signal`；`campus_cycle_backlog.current_cohort/_existing_status_by_key`；`must_apply.by_industry`；`ops_runs.record_ops_run/status_from_counts`。
- Produces: `drain_official_one(sb, company, now) -> dict`（单公司统计，永不抛）；`main()`（CLI：`--company` 单家 / `--limit N` 批量 / `--workers K` 并发）。

- [ ] **Step 1: 写实现（编排为主，纯函数已在 Task 2/3 测过；本任务靠 live 冒烟验证）**

`crawler/campus_official_backlog.py`:
```python
#!/usr/bin/env python3
"""校招今年精确日期 快路② —— 每日 cron：官方校招页 httpx 并发直取 → 精确日期抽取 →
判官 → 官方源门 auto-verify → 幂等写 recruitment_cycle_observations。

红线（宁缺不编）：只 auto-verify「官方招聘域名 grounding（抓的就是公司自有官方页）+ 判官
entailment」的精确日期；SPA 空壳/无日期信号的诚实跳过。不吃搜索额度（全程 httpx 抓公开页）。

用法（CI/本机，需 .env.local 的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY + SILICONFLOW_API_KEY）：
  python3 campus_official_backlog.py --company 字节跳动
  python3 campus_official_backlog.py --limit 40 --workers 6
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import db
import must_apply
import ops_runs
from campus_cycle_backlog import current_cohort, _existing_status_by_key, fetch_covered_company_names
from campus_official_extract import build_official_messages, parse_precise_claims
from campus_official_pages import official_campus_urls, fetch_first_with_signal
from insight_backlog import fetch_one_company
from insight_engine import (chat_json, judge_claim, llm_config, llm_run_health,
                            llm_run_unhealthy, reset_llm_health)
from official_gate import (decide_cycle_status, is_entailment, is_official_grounding,
                           official_hosts_from_sources)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def drain_official_one(sb, company, now):
    """单公司快路② drain。永不抛。返回统计 dict。"""
    stats = {"company": company, "claims_seen": 0, "verified": 0, "draft": 0, "skipped": None}

    profile = fetch_one_company(sb, company)
    if not profile:
        return {"company": company, "skipped": "no_company"}
    if not llm_config()["configured"]:
        return {"company": company, "skipped": "llm_not_configured"}

    try:
        source_rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("company,source_url").eq("company", company))
    except Exception as e:
        print(f"  [campus-official-err] {company} 查源失败: {type(e).__name__}: {str(e)[:120]}")
        return {"company": company, "skipped": "sources_error"}
    official_hosts = official_hosts_from_sources(
        [r.get("source_url") for r in source_rows if r.get("source_url")])
    if not official_hosts:
        return {"company": company, "skipped": "no_official_host"}

    urls = official_campus_urls(source_rows, official_hosts)
    page_url, page_text = fetch_first_with_signal(urls)
    if not page_url:
        return {"company": company, "skipped": "no_campus_page_signal"}
    if not is_official_grounding(page_url, official_hosts):
        return {"company": company, "skipped": "page_not_official"}

    try:
        claims = parse_precise_claims(chat_json(build_official_messages(company, page_text)), now)
    except Exception as e:
        print(f"  [campus-official-err] {company} 抽取失败: {type(e).__name__}: {str(e)[:120]}")
        return {"company": company, "skipped": "writer_error"}
    stats["claims_seen"] = len(claims)
    if not claims:
        return stats

    grad_class, valid_until = current_cohort(now)
    existing = _existing_status_by_key(sb, profile["id"], grad_class)

    for c in claims:
        ev_key = (c["season"], c["batch"], c["event"])
        if existing.get(ev_key) == "verified":
            continue  # verified 事实不可覆盖（不变量）
        claim_sentence = f"{company}{c['season']}{c['batch']}{c['value_text']}"
        try:
            judge = judge_claim(claim_sentence, page_text)
        except Exception as e:
            print(f"  [campus-official-err] {company} 判官失败: {type(e).__name__}: {str(e)[:120]}")
            continue
        if not is_entailment(judge.get("verdict"), judge.get("confidence")):
            continue
        # 官方页 grounding=True → decide 返回 ('verified','official_notice','high')
        status, source_kind, confidence = decide_cycle_status(
            is_official_grounding(page_url, official_hosts), 1)
        time_expr_type = "日期范围" if c["date_end"] else "精确日期"
        row = {
            "company_id": profile["id"], "grad_class": grad_class,
            "season": c["season"], "batch": c["batch"], "event": c["event"],
            "time_expr_type": time_expr_type, "value_text": c["value_text"],
            "month_start": c["month_start"], "month_end": c["month_end"],
            "date_start": c["date_start"], "date_end": c["date_end"],
            "confidence": confidence, "evidence_url": page_url,
            "evidence_excerpt": (c["quote"] or "")[:200], "evidence_fetched_at": _now_iso(),
            "source_kind": source_kind, "verify_status": status,
            "valid_until": valid_until, "created_by": "cron",
        }
        try:
            sb.table("recruitment_cycle_observations").insert(row).execute()
        except Exception as e:
            print(f"  [campus-official-err] {company} 写入失败: {type(e).__name__}: {str(e)[:120]}")
            continue
        if status == "verified":
            existing[ev_key] = "verified"
        stats["verified" if status == "verified" else "draft"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser(description="校招今年精确日期 快路②（官方页并发直取，宁缺不编）")
    ap.add_argument("--company", default="")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        print("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY，先 source .env.local")
        sys.exit(1)

    sb = db.get_supabase()
    now = datetime.now(timezone.utc)
    started_at = _now_iso()
    reset_llm_health()

    if args.company:
        results = [drain_official_one(sb, args.company, now)]
    else:
        by_industry = must_apply.by_industry()
        covered = fetch_covered_company_names(sb)  # 已有 verified 时间线的公司本轮不重复（含精确日期）
        seen, targets = set(), []
        for _ind, companies in (by_industry or {}).items():
            for entry in (companies or []):
                name = (entry.get("name") or "").strip() if isinstance(entry, dict) else ""
                if name and name not in seen and name not in covered:
                    seen.add(name)
                    targets.append(name)
        targets = targets[:max(0, args.limit)]
        print(f"[campus_official_backlog] 目标 {len(targets)} 家（已覆盖 {len(covered)} 家跳过），workers={args.workers}")
        results = []
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = {ex.submit(drain_official_one, sb, name, now): name for name in targets}
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append({"company": futs[fut], "skipped": f"crash:{type(e).__name__}"})

    processed = len(results)
    verified = sum(r.get("verified", 0) for r in results)
    draft = sum(r.get("draft", 0) for r in results)
    for r in results:
        print(f"  {r.get('company')}: {r.get('skipped') or 'ok'} "
              f"verified={r.get('verified', 0)} draft={r.get('draft', 0)}")

    ops_runs.record_ops_run(
        sb, "campus_official_backlog",
        {"companies_processed": processed, "verified": verified, "draft": draft},
        status=ops_runs.status_from_counts(processed, 0),
        started_at=started_at, finished_at=_now_iso())

    if llm_run_unhealthy():
        h = llm_run_health()
        print(f"✗ LLM 整体失败（ok={h['ok']} fail={h['fail']} account_error={h['account_error']}）")
        sys.exit(1)


if __name__ == "__main__":
    main()
```
> ⚠️ 复用 `_existing_status_by_key`/`fetch_covered_company_names`/`current_cohort` 时先 `Read crawler/campus_cycle_backlog.py` 确认签名未变（本 plan 基于 2026-07-22 版）；`fetch_one_company` 返回含 `id` 的 profile，先确认 `crawler/insight_backlog.py` 该函数签名。

- [ ] **Step 2: 回归 + 冒烟（本机，需 .env.local）**

Run（回归，确认没打断现有 crawler 单测）:
`python3 -m unittest discover -s crawler -t crawler -p "test_*.py"`
Expected: 全绿（含 Task 2/3 新测）。

Run（live 冒烟，字节 SSR 页）:
```bash
cd crawler && set -a && source ../.env.local && set +a && python3 campus_official_backlog.py --company 字节跳动
```
Expected: 打印 `字节跳动: ok claims_seen=… verified=…`（若 SiliconFlow 有额度且页面当季有精确日期则 verified≥0；无则 claims_seen=0 属正常，非报错）。**冒烟只验 wiring 不报错 + 官方门判定正确**，真实产出以首次 prod cron 为准。

- [ ] **Step 3: Commit**

```bash
git add crawler/campus_official_backlog.py
git commit -m "feat(campus): 快路② 官方页并发直取 drain 编排（P3b 主力）"
```

### Task 5: 每日 cron workflow

**Files:**
- Create: `.github/workflows/campus-official-pages.yml`
- 参考（勿改）：`.github/workflows/campus-cycle-enrich.yml`

**Interfaces:** 无（CI 配置）。

- [ ] **Step 1: 先读模板**

Run: `Read .github/workflows/campus-cycle-enrich.yml`（照抄 checkout / python setup / pip install / env 注入结构；本 workflow **不需要**搜索源 key，只需 Supabase + SiliconFlow）。

- [ ] **Step 2: 写 workflow**

`.github/workflows/campus-official-pages.yml`（按模板结构填；关键差异：cron 错峰到 `0 20 * * *`，run 换成官方页 drain，env 去掉搜索 key）：
```yaml
name: campus-official-pages
on:
  schedule:
    - cron: "0 20 * * *"   # 每日 UTC 20:00，与 campus-cycle-enrich(22:15) 错峰
  workflow_dispatch:
    inputs:
      company:
        description: "只跑单家公司（调试）"
        required: false
        default: ""
      limit:
        description: "本轮最多处理多少家"
        required: false
        default: "40"
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: pip install -r crawler/requirements.txt
      - name: Run campus official-pages drain
        working-directory: crawler
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
        run: |
          if [ -n "${{ github.event.inputs.company }}" ]; then
            python3 campus_official_backlog.py --company "${{ github.event.inputs.company }}"
          else
            python3 campus_official_backlog.py --limit "${{ github.event.inputs.limit || 40 }}" --workers 6
          fi
```
> ⚠️ 以 `campus-cycle-enrich.yml` 实际字段为准（secrets 名、python 版本、requirements 路径、workflow_dispatch 写法）；与模板不一致处以模板为准，别照抄本 plan 里可能过时的细节。

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/campus-official-pages.yml
git commit -m "ci(campus): 每日官方校招页并发直取 cron（快路② P3b）"
```

---

## Phase P3c + 快路① — 展示（前端纯函数 + 装配）

### Task 6: 精确日期展示纯函数 + 快路① deadline 清洗

**Files:**
- Modify: `lib/recruitment-cycle.ts`（新增三个纯函数，不改现有 `campusTimelineSummary`）
- Test: `tests/recruitment-cycle-p3.test.js`
- 参考（勿改）：`lib/recruitment-cycle.ts:55-102`（现成月份版）

**Interfaces:**
- Produces（同一文件三个纯函数）：
  - `campusPreciseDates(observations: RecruitmentObservation[], now?: Date): { label: string; batch: string }[]` — 取 verified + 未过期 + 当前届 + `time_expr_type ∈ {'精确日期','日期范围'}` 的行，产展示 bit（如 `正式批网申9月10日截止`，标注「据官方公告」由展示层加）。空则 `[]`。
  - `campusBatchTimingGap(observations: RecruitmentObservation[], now?: Date): string | null` — 有「提前批开放」与「正式批开放」两批 month_start 时，产「提前批比正式批约早 N 周」；否则 `null`。
  - `cleanCampusDeadlineMs(deadlineText: string | null, now?: Date): number | null` — 清洗 text deadline：仅接受 `YYYY-MM-DD` 且在 `[now, now+550d]`（滤 `长期有效`/`3000-01-01`/远未来/过去），返回毫秒或 `null`。

- [ ] **Step 1: 写失败测试**

`tests/recruitment-cycle-p3.test.js`:
```javascript
const test = require("node:test");
const assert = require("node:assert");
const {
  campusPreciseDates,
  campusBatchTimingGap,
  cleanCampusDeadlineMs,
} = require("../lib/recruitment-cycle.ts");

const NOW = new Date("2026-07-22T00:00:00Z");

test("campusPreciseDates 取 verified 未过期精确日期行", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "截止",
      time_expr_type: "精确日期", value_text: "网申9月10日截止", month_start: 9, month_end: null,
      verify_status: "verified", valid_until: "2027-06-30" },
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放",
      time_expr_type: "月", value_text: "约7月", month_start: 7, month_end: null,
      verify_status: "verified", valid_until: "2027-06-30" }, // 非精确日期，排除
  ];
  const bits = campusPreciseDates(obs, NOW);
  assert.equal(bits.length, 1);
  assert.match(bits[0].label, /网申9月10日截止/);
});

test("campusPreciseDates 排除 draft / 过期", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "截止",
      time_expr_type: "精确日期", value_text: "9月10日", month_start: 9,
      verify_status: "draft", valid_until: "2027-06-30" },
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "截止",
      time_expr_type: "精确日期", value_text: "9月10日", month_start: 9,
      verify_status: "verified", valid_until: "2025-06-30" },
  ];
  assert.equal(campusPreciseDates(obs, NOW).length, 0);
});

test("campusBatchTimingGap 提前批比正式批早", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放",
      month_start: 7, verify_status: "verified", valid_until: "2027-06-30" },
    { grad_class: "2027届", season: "秋招", batch: "正式批", event: "开放",
      month_start: 9, verify_status: "verified", valid_until: "2027-06-30" },
  ];
  assert.match(campusBatchTimingGap(obs, NOW), /提前批.*早/);
});

test("campusBatchTimingGap 缺一批返回 null", () => {
  const obs = [
    { grad_class: "2027届", season: "秋招", batch: "提前批", event: "开放",
      month_start: 7, verify_status: "verified", valid_until: "2027-06-30" },
  ];
  assert.equal(campusBatchTimingGap(obs, NOW), null);
});

test("cleanCampusDeadlineMs 接受近未来、滤垃圾/过去", () => {
  assert.ok(cleanCampusDeadlineMs("2026-08-01", NOW) > 0);
  assert.equal(cleanCampusDeadlineMs("长期有效", NOW), null);
  assert.equal(cleanCampusDeadlineMs("3000-01-01", NOW), null);
  assert.equal(cleanCampusDeadlineMs("2025-01-01", NOW), null);
  assert.equal(cleanCampusDeadlineMs("", NOW), null);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test tests/recruitment-cycle-p3.test.js`
Expected: FAIL（函数未导出）

- [ ] **Step 3: 写实现（追加到 `lib/recruitment-cycle.ts` 末尾）**

```typescript
const BATCH_ORDER_P3: Record<string, number> = { 提前批: 0, 正式批: 1, 补录: 2, 实习转正: 3 };

function _usableRows(observations: RecruitmentObservation[], now: Date) {
  const today = ymd(now);
  const m = now.getMonth() + 1;
  const preferred: CycleSeason = m >= 5 && m <= 12 ? "秋招" : "春招";
  const rows = (observations || []).filter(
    (o) =>
      o &&
      (!o.verify_status || o.verify_status === "verified") &&
      (!o.valid_until || o.valid_until >= today),
  );
  const inPref = rows.filter((o) => o.season === preferred);
  return inPref.length > 0 ? inPref : rows;
}

// 今年精确日期展示 bit（据官方公告的确切网申/截止日期）。
export function campusPreciseDates(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
): { label: string; batch: string }[] {
  const rows = _usableRows(observations, now).filter(
    (o) => o.time_expr_type === "精确日期" || o.time_expr_type === "日期范围",
  );
  const byBatch = new Map<string, RecruitmentObservation>();
  for (const o of rows) {
    const cur = byBatch.get(o.batch);
    if (!cur) byBatch.set(o.batch, o);
  }
  return Array.from(byBatch.values())
    .sort((a, b) => (BATCH_ORDER_P3[a.batch] ?? 9) - (BATCH_ORDER_P3[b.batch] ?? 9))
    .map((o) => ({ label: `${o.batch}${o.value_text}`, batch: o.batch }));
}

// 提前批 vs 正式批 时间差（cycle 级，仅时间不碰 HC/难度）。
export function campusBatchTimingGap(
  observations: RecruitmentObservation[],
  now: Date = new Date(),
): string | null {
  const rows = _usableRows(observations, now).filter((o) => o.event === "开放" && o.month_start != null);
  const early = rows.find((o) => o.batch === "提前批");
  const main = rows.find((o) => o.batch === "正式批");
  if (!early || !main || early.month_start == null || main.month_start == null) return null;
  const weeks = Math.round((main.month_start - early.month_start) * 4.3);
  if (weeks <= 0) return null;
  return `提前批比正式批约早 ${weeks} 周`;
}

// 快路①：清洗 text deadline，仅接受近未来真实日期（滤「长期有效」/占位/远未来/过去）。
export function cleanCampusDeadlineMs(
  deadlineText: string | null,
  now: Date = new Date(),
): number | null {
  if (!deadlineText || !/^\d{4}-\d{2}-\d{2}$/.test(deadlineText.trim())) return null;
  const t = Date.parse(deadlineText.trim() + "T00:00:00Z");
  if (Number.isNaN(t)) return null;
  const nowMs = now.getTime();
  const maxMs = nowMs + 550 * 24 * 3600 * 1000;
  if (t < nowMs || t > maxMs) return null;
  return t;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test tests/recruitment-cycle-p3.test.js`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/recruitment-cycle.ts tests/recruitment-cycle-p3.test.js
git commit -m "feat(campus): 精确日期展示+批次时间差+deadline清洗纯函数（P3c/快路①）"
```

### Task 7: 装配到页面 + 卡面渲染

**Files:**
- Modify: `app/campus/page.tsx`（计算 precise/gap/cleaned deadline，塞进 card）
- Modify: `app/campus/campus-client.tsx`（`CampusCardData` 加字段 + 渲染「今年精确」行 + 「据在招岗位」提示）
- 按需确认: `lib/recruitment-cycle-store.ts` 的 select 是否带回 `date_start,date_end,time_expr_type`（`campusPreciseDates` 只用 `time_expr_type/value_text/batch/verify_status/valid_until/season/event/month_start`，不直接用 date_*；但保险起见确认 store 未过滤掉精确日期行）。

**Interfaces:**
- Consumes: Task 6 的 `campusPreciseDates` / `campusBatchTimingGap` / `cleanCampusDeadlineMs`。
- Produces: `CampusCardData` 扩展 `preciseDates: { label: string; batch: string }[]`、`batchTimingGap: string | null`、`cleanDeadlineMs: number | null`。

- [ ] **Step 1: page.tsx 计算并下发**

在 `app/campus/page.tsx` import 段补：
```tsx
import { campusTimelineSummary, campusPreciseDates, campusBatchTimingGap, cleanCampusDeadlineMs } from "@/lib/recruitment-cycle";
```
把 `cards = zone.map(...)` 里的 return 改为（在现有基础上加三个字段；用清洗函数替换裸 `Date.parse`）：
```tsx
    const obs = cyclesByPattern.get(z.pattern) || [];
    const timeline = obs.length > 0 ? campusTimelineSummary(obs) : null;
    const preciseDates = obs.length > 0 ? campusPreciseDates(obs) : [];
    const batchTimingGap = obs.length > 0 ? campusBatchTimingGap(obs) : null;
    const cleanDl = z.campusJobs
      .map((j) => cleanCampusDeadlineMs(j.deadline))
      .filter((t): t is number => t != null);
    const cleanDeadlineMs = cleanDl.length ? Math.min(...cleanDl) : null;
    return { ...z, window, nearestDeadlineMs, timeline, preciseDates, batchTimingGap, cleanDeadlineMs };
```

- [ ] **Step 2: campus-client.tsx 扩类型**

`CampusCardData` 类型加：
```tsx
export type CampusCardData = CampusCompanyRow & {
  window: WindowState;
  nearestDeadlineMs: number | null;
  timeline: CampusTimeline | null;
  preciseDates: { label: string; batch: string }[];
  batchTimingGap: string | null;
  cleanDeadlineMs: number | null;
};
```

- [ ] **Step 3: 卡面渲染「今年精确」行（据往年行之后）**

在 `card.timeline &&` 那段之后插入：
```tsx
{card.preciseDates.length > 0 && (
  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] leading-5 text-[#4f6f2a] dark:text-[#a3d06a]">
    <span className="inline-flex items-center gap-1 rounded-md border border-[#bcdcae] bg-[#e6f2d6] px-1.5 py-0.5 font-medium text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]">
      今年·据官方公告
    </span>
    {card.preciseDates.map((p) => (
      <span key={p.batch}>· {p.label}</span>
    ))}
    {card.batchTimingGap && <span className="text-[#8a6312] dark:text-[#e0b15a]">· {card.batchTimingGap}</span>}
  </div>
)}
{card.preciseDates.length === 0 && card.cleanDeadlineMs && (
  <p className="text-[12px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
    据在招岗位约 {new Date(card.cleanDeadlineMs).toLocaleDateString("zh-CN", { month: "long", day: "numeric" })} 前截止
  </p>
)}
```
> 措辞三档区分（据官方公告 > 据在招岗位 > 据往年）已由不同行/配色体现：官方公告用绿系强档、据在招岗位用灰系弱档、据往年沿用蓝系。

- [ ] **Step 4: build 验证**

Run: `npm run build`
Expected: 编译通过、无 TS 报错。

- [ ] **Step 5: 浏览器验证**

preview `/campus`：有精确日期的公司显绿系「今年·据官方公告 · 正式批网申9月10日截止」；无精确日期但有干净 deadline 的显灰系「据在招岗位约 X 前截止」；两者都无则只剩「据往年」。截图留证。

- [ ] **Step 6: 回归四件套 + Commit**

Run: `node --test tests/*.test.js && python3 -m unittest discover -s crawler -t crawler -p "test_*.py" && npm run build && git diff --check`
Expected: 全绿。
```bash
git add app/campus/page.tsx app/campus/campus-client.tsx
git commit -m "feat(campus): 卡面渲染今年精确日期+批次时间差+据在招岗位提示（P3c/快路①）"
```

---

## Self-Review

**1. Spec coverage（对 §0.5 定稿逐条）：**
- P3a 抽屉外露 → Task 1 ✅
- P3b 快路② 官方页抽取器（URL 解析→抓取→预筛→抽取→判官→官方门→写 RCO）→ Task 2/3/4 ✅
- P3b 快路② cron → Task 5 ✅
- P3b 快路① deadline 兜底（清洗、公司级、不写 RCO 不猜批次）→ Task 6 `cleanCampusDeadlineMs` + Task 7 「据在招岗位」提示 ✅
- P3c 批次「时间」差异 → Task 6 `campusBatchTimingGap` + Task 7 渲染 ✅
- 今年精确日期展示（三档措辞区分）→ Task 6 `campusPreciseDates` + Task 7 ✅
- 无新迁移（source_kind='official_notice' 在迁移 182 check 内；快路① 不写 RCO）✅
- 不吃搜索额度（快路② 全 httpx）✅

**2. Placeholder scan：** 无 TBD/TODO；每个 code step 都有完整代码；测试步给出真实断言。UI 装配步（Task 1/7）为 build + 浏览器验证（项目无 RTL 单测惯例，已注明）。

**3. Type consistency：**
- `parse_precise_claims(llm_out, now)` 返回 dict 含 `date_start/date_end/month_start/month_end/season/batch/event/value_text/quote` → Task 4 `drain_official_one` 逐字段消费 ✅
- `official_campus_urls`/`fetch_first_with_signal`/`has_date_signal`/`html_to_text` 签名 Task 3 定义、Task 4 消费一致 ✅
- `campusPreciseDates` 返回 `{label,batch}[]` → Task 7 `card.preciseDates.map((p)=>p.label/p.batch)` 一致 ✅
- `decide_cycle_status(has_official, n)` 复用原签名（Task 4 传 `(is_official_grounding(...), 1)`）✅

**⚠️ 执行注意（复用现成代码前必读确认签名）：** `campus_cycle_backlog.current_cohort/_existing_status_by_key/fetch_covered_company_names`、`insight_backlog.fetch_one_company`、`lib/insight-client` 的 `InsightAvailability` 字段名、`.github/workflows/campus-cycle-enrich.yml` 的 secrets/结构——均以仓库实际为准（本 plan 基于 2026-07-22 版本），执行每个 Task 前先 Read 对应文件核签名，勿凭本 plan 可能过时的细节硬写。
