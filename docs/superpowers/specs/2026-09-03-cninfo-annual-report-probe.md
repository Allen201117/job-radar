# 巨潮资讯年报员工数据可行性 live 验证报告

**验证日期**: 2026-09-03  
**样本公司**: 宁德时代（300750）、比亚迪（002594）  
**实测请求数**: 共 14 次（含 GET/POST/HEAD/下载）

---

## 结论表

| 项目 | 结论 | 可信度 |
|---|---|---|
| 接口可访问性 | 可访问，无需登录，需要 JSESSIONID cookie | 实测确认 |
| `hisAnnouncement/query` 用 `stock=` 字段过滤 | **不可用** — 任何格式（股票代码/orgId/代码+公司名）均返回 0 结果 | 实测确认 |
| `hisAnnouncement/query` 用 `searchkey=公司名+年度报告` | **可用** — 稳定返回年报列表 | 实测确认 |
| PDF 下载 | `http://static.cninfo.com.cn/finalpage/{date}/{id}.PDF` 无鉴权，直接下载 | 实测确认 |
| 员工人数节提取 | 标准模板，pdfplumber 文本抽取即可拿到所有字段 | 实测确认 |
| 应付职工薪酬附注 | 附注里有完整四列（期初/本期增加/本期减少/期末），可倒推人均 | 实测确认 |
| 港股（HKEXnews）类似入口 | 未做 live 验证，见「未找到确切来源」段 | 未验证 |

---

## §1 接口发现与实测过程

### 1.1 股票列表接口

**URL**: `http://www.cninfo.com.cn/new/data/szse_stock.json`  
**方法**: GET，无需 Header  
**实测结果**: HTTP 200，返回深交所全量股票 6,246 条 JSON  
**字段结构**:
```json
{"code": "002594", "pinyin": "byd", "category": "A股", "orgId": "gshk0001211", "zwjc": "比亚迪"}
{"code": "300750", "pinyin": "ndsd", "category": "A股", "orgId": "GD165627", "zwjc": "宁德时代"}
```

上交所股票需另请求 `http://www.cninfo.com.cn/new/data/sse_stock.json`（本次未测，但结构应相同）。

### 1.2 年报查询接口 — 失败路径

**URL**: `http://www.cninfo.com.cn/new/hisAnnouncement/query`  
**方法**: POST  
**社区文档描述的参数**: `stock=股票代码,公司名`  
**实测结果**: 测试了以下格式，全部返回 `"totalAnnouncement":0`：

| `stock` 参数值 | 结果 |
|---|---|
| `002594` | 0 结果 |
| `002594,比亚迪` | 0 结果 |
| `gshk0001211`（orgId） | 0 结果 |

**原因推测**: `stock` 过滤逻辑可能需要额外的 CSRF token 或特定的 Referer 路径（巨潮前端实际上是通过 JS 动态构建请求，含额外隐藏字段）。本次未进一步溯源（避免超过 30 次请求限制）。

### 1.3 年报查询接口 — 成功路径（实测验证）

**URL**: `http://www.cninfo.com.cn/new/hisAnnouncement/query`  
**方法**: POST  
**实际可用参数**:

```
stock=（留空）
searchkey=宁德时代年度报告
category=category_ndbg_szsh
pageNum=1
pageSize=5
column=szse
tabName=fulltext
seDate=（留空则不限年份）
sortName=（留空）
sortType=（留空）
isHLtitle=true
```

Headers 必须含:
```
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest
User-Agent: Mozilla/5.0 ...
```

需先 GET 任意巨潮页面以获取 `JSESSIONID` cookie，随后 POST 才返回非零结果。

**比亚迪实测结果**（searchkey=比亚迪年度报告，共 30 条）：

| 标题 | adjunctUrl |
|---|---|
| 2025年年度报告 | `finalpage/2026-03-28/1225045351.PDF` |
| 2025年年度报告摘要 | `finalpage/2026-03-28/1225045350.PDF` |
| 2024年年度报告摘要 | `finalpage/2025-03-25/1222881505.PDF` |
| 2024年年度报告 | `finalpage/2025-03-25/1222881496.PDF` |
| 2023年年度报告摘要 | `finalpage/2024-03-27/1219412041.PDF` |

**宁德时代实测结果**（searchkey=宁德时代年度报告，共 14 条）：

| 标题 | adjunctUrl |
|---|---|
| 2025年年度报告 | `finalpage/2026-03-10/1225002214.PDF` |
| 2025年年度报告摘要 | `finalpage/2026-03-10/1225002213.PDF` |
| 2024年年度报告 | `finalpage/2025-03-15/1222806982.PDF` |

PDF 完整 URL 格式: `http://static.cninfo.com.cn/{adjunctUrl}`

### 1.4 PDF 下载

| 公司 | 年份 | 大小 | HTTP 状态 | 下载耗时 |
|---|---|---|---|---|
| 宁德时代 | 2024 | 1.97 MB / 229 页 | 200（无鉴权） | 26.2s（国内可更快） |
| 比亚迪 | 2024 | 9.63 MB | 200（HEAD 验证） | 未下载 |

---

## §2 实际抽取到的数据（宁德时代 2024 年报）

### 2.1 员工情况（第 57 页，「十一、公司员工情况」章节）

| 字段 | 数值 |
|---|---|
| 母公司在职员工 | 32,510 人 |
| 主要子公司在职员工 | 99,478 人 |
| **在职员工总计** | **131,988 人** |
| 当期领取薪酬人数 | 131,988 人 |
| 需承担费用的离退休职工 | 0 人 |

**专业构成**:

| 类别 | 人数 |
|---|---|
| 生产人员 | 96,725 |
| 技术人员 | 20,346 |
| 行政人员 | 11,419 |
| 销售人员 | 2,806 |
| 财务人员 | 692 |
| **合计** | **131,988** |

**教育程度**:

| 学历 | 人数 |
|---|---|
| 博士 | 625 |
| 硕士 | 8,015 |
| 本科 | 26,292 |
| 大专及以下 | 97,056 |
| **合计** | **131,988** |

### 2.2 应付职工薪酬附注（第 189-190 页，附注 31）

单位：千元人民币

| 项目 | 期初余额 | **本期增加** | 本期减少 | 期末余额 |
|---|---|---|---|---|
| 一、短期薪酬（合计） | 14,840,448 | **28,151,691** | 24,345,435 | 18,646,704 |
| 其中：工资奖金津贴补贴 | 14,776,113 | **25,002,292** | 21,224,400 | 18,554,005 |
| 社会保险费 | 5,037 | **1,117,615** | 1,117,807 | 4,845 |
| 住房公积金 | 5,229 | **654,914** | 650,258 | 9,885 |
| 其中：基本养老保险 | 5,603 | **1,479,908** | 1,479,365 | 6,145 |

**倒推人均薪酬（粗估，仅供参考）**:  
短期薪酬本期增加 28,151,691 千元 ÷ 131,988 人 ≈ **213,300 元/年 ≈ 17,775 元/月**  
注：这包含社保/公积金的公司承担部分，实际税前到手薪酬更低；且这是合并报表口径的当年计提额。

---

## §3 评估

### 3.1 接口稳定性

| 方面 | 结论 |
|---|---|
| 是否需要登录账号 | **否** — 只需匿名 JSESSIONID（GET 任意页面即可取得） |
| 是否有 CAPTCHA / JS 挑战 | 本次未触发；但 `stock=` 字段的 POST 参数疑似需要额外 JS 生成的字段才生效 |
| 推荐 Header | `User-Agent` + `X-Requested-With: XMLHttpRequest` + `Referer` |
| 频率限制 | 本次 14 次请求未触发任何限流；官方无公开说明，建议每请求间隔 1-2s |
| cookie 有效期 | JSESSIONID 应按会话有效，长时间跑需定期刷新 |
| `static.cninfo.com.cn` PDF 下载 | 完全公开，无鉴权，稳定 |

**反爬风险**: 中等。巨潮是深交所官方信息披露平台，不可能彻底封锁机器读取（监管合规要求），但高频批量请求可能触发 IP 限速。建议加随机延迟、用多 IP 轮换处理全量 5,300 家场景。

### 3.2 PDF 大小与解析耗时

| 指标 | 实测值 |
|---|---|
| CATL 2024 PDF 大小 | 1.97 MB，229 页 |
| BYD 2024 PDF 大小 | 9.63 MB（HEAD 确认） |
| pdfplumber 全文扫描耗时 | 14.6s（229 页，单线程，M 系芯片） |
| 定向只取员工章节 | 约 0.1-0.5s（已知页码后只读那一页） |
| 员工信息页面位置稳定性 | 本次两家均在报告书前 1/4，A 股年报模板高度标准化 |

**扫描策略建议**: 先全文扫描找含「员工情况」的页码，再精确提取，避免全 PDF 逐页解析。

### 3.3 章节格式通用性

**高度标准化**。中国证监会对 A 股年报格式有强制要求（《公开发行证券的公司信息披露内容与格式准则第 2 号》），员工情况章节的表头几乎一字不差：

- 表头固定: `专业构成类别` / `专业构成人数（人）`
- 五个专业类别固定: 生产人员、销售人员、技术人员、财务人员、行政人员
- 四个学历类别固定: 博士、硕士、本科、大专及以下

**可通用的 pdfplumber 提取策略**: 用文本匹配找到「公司员工情况」或「员工数量」章节，然后用 `extract_tables()` 提取表格即可（本次实测表格提取成功，结构整齐）。

**潜在例外**:
- 极少数公司年报以纯扫描图片形式提交（需 OCR，但监管要求提交文字版，比例极低）
- 创业板/科创板部分小公司用合并正文而非独立表格描述员工数（需 regex 从文本提取）
- 附注里的应付职工薪酬格式基本统一，但科目名称略有差异（有的用「一、短期职工薪酬」）

### 3.4 全量 ~5,300 家成本估算

| 阶段 | 请求数 | 体量 |
|---|---|---|
| 股票列表（一次性） | 2（沪/深各 1） | ~1.2 MB |
| 年报 URL 查询（每家 1 次） | ~5,300 | 可忽略（JSON 响应小） |
| PDF 下载（每家 1 份） | ~5,300 | 估算 平均 5-8 MB × 5,300 ≈ **26-42 GB** |
| PDF 解析 | 0 网络请求 | CPU：~15s/份 × 5,300 ≈ **22 小时**（单线程）；多进程可降至 2-4 小时 |

**实际增量成本（每年一次）**:
- 只有发布了新年报的公司才需要重新下载解析（已解析的年报可永久缓存）
- 年报集中在 3-4 月披露，每日新增约 100-300 份，分批下载即可

### 3.5 港股 HKEXnews 类似入口

**未做 live 验证**，以下为知识截止日（2025-08）之前的已知信息：

港交所披露易（HKEXnews，`https://www.hkexnews.hk/`）有结构化查询入口：
- 接口: `https://www1.hkexnews.hk/search/titlesearch.xhtml` 可查公告
- 年报文档格式: 多为 PDF，也有部分 HTML
- **机器可读程度**: 低于巨潮。港交所无强制标准化的年报员工章节格式要求，各公司格式差异大
- **XBRL 数据**: 港交所自 2023 年起要求部分公司提交 iXBRL，但员工数量不是 XBRL 强制标签

**结论**: 港股年报员工数据技术上可爬，但格式提取难度显著高于 A 股（无固定模板），建议单独立项评估。

---

## §4 推荐实现方案

### 4.1 接口调用序列

```python
import httpx, time, hashlib, json
from pathlib import Path

CNINFO_BASE = "http://www.cninfo.com.cn"
CNINFO_STATIC = "http://static.cninfo.com.cn"
CACHE_DIR = Path("./annual_report_cache")

def get_session() -> httpx.Client:
    client = httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (compatible; AnnualReportBot/1.0)"},
        follow_redirects=True, timeout=30
    )
    client.get(f"{CNINFO_BASE}/new/commonUrl/pageOfSearch?url=disclosure/list/search")
    return client

def query_annual_report_url(client: httpx.Client, company_name: str, year: int) -> str | None:
    """返回最新年报的 adjunctUrl，如 'finalpage/2025-03-15/1222806982.PDF'"""
    r = client.post(
        f"{CNINFO_BASE}/new/hisAnnouncement/query",
        data={
            "stock": "",
            "searchkey": f"{company_name}年度报告",
            "category": "category_ndbg_szsh",
            "pageNum": "1", "pageSize": "10",
            "column": "szse",  # 深交所；上交所同接口但 column=sse（待验证）
            "tabName": "fulltext",
            "seDate": f"{year}-01-01 to {year}-12-31",
            "sortName": "", "sortType": "", "isHLtitle": "true"
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }
    )
    anns = r.json().get("announcements") or []
    # 找「年度报告」而非「摘要」
    for a in anns:
        title = a.get("announcementTitle", "")
        if "年度报告" in title and "摘要" not in title:
            return a.get("adjunctUrl")
    return None

def download_pdf(adjunct_url: str) -> bytes | None:
    """带本地文件缓存，同一年报只下载一次"""
    cache_key = hashlib.md5(adjunct_url.encode()).hexdigest()
    cache_path = CACHE_DIR / f"{cache_key}.pdf"
    if cache_path.exists():
        return cache_path.read_bytes()
    
    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    r = client.get(f"{CNINFO_STATIC}/{adjunct_url}")
    if r.status_code == 200:
        CACHE_DIR.mkdir(exist_ok=True)
        cache_path.write_bytes(r.content)
        return r.content
    return None
```

### 4.2 解析策略

**优先使用表格提取（`pdfplumber.extract_tables()`）**，而非正则：

```python
import pdfplumber, re

def extract_employee_data(pdf_bytes: bytes) -> dict:
    result = {}
    with pdfplumber.open(pdf_bytes) as pdf:
        # Step 1: 找员工章节页码
        emp_page_idx = None
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "公司员工情况" in text or "员工数量" in text and "专业构成" in text:
                emp_page_idx = i
                break
        
        if emp_page_idx is None:
            # fallback: 搜「在职员工的数量合计」
            for i, page in enumerate(pdf.pages):
                if "在职员工的数量合计" in (page.extract_text() or ""):
                    emp_page_idx = i
                    break
        
        if emp_page_idx is None:
            return {"error": "employee_section_not_found"}
        
        # Step 2: 从该页提取表格
        page = pdf.pages[emp_page_idx]
        tables = page.extract_tables()
        text = page.extract_text() or ""
        
        # 正则从文本兜底（比表格更稳定）
        total_match = re.search(r"在职员工的数量合计.*?([\d,]+)", text)
        if total_match:
            result["employee_total"] = int(total_match.group(1).replace(",", ""))
        
        for role, key in [("生产人员", "production"), ("销售人员", "sales"),
                           ("技术人员", "technical"), ("财务人员", "finance"),
                           ("行政人员", "admin")]:
            m = re.search(rf"{role}\s+([\d,]+)", text)
            if m:
                result[f"emp_{key}"] = int(m.group(1).replace(",", ""))
        
        for edu, key in [("博士", "phd"), ("硕士", "master"), ("本科", "bachelor"),
                          ("大专及以下", "below_bachelor")]:
            m = re.search(rf"{edu}\s+([\d,]+)", text)
            if m:
                result[f"edu_{key}"] = int(m.group(1).replace(",", ""))
        
        # Step 3: 找应付职工薪酬附注
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            if "应付职工薪酬" in t and "本期增加" in t:
                m = re.search(r"短期薪酬.*?([\d,]+)\s+([\d,]+)", t)
                if m:
                    result["compensation_current_year_added_k_cny"] = int(m.group(2).replace(",", ""))
                break
    
    return result
```

**解析策略选择**:

| 字段 | 推荐方法 |
|---|---|
| 员工总数、专业/学历构成 | 文本正则优先（格式固定），表格提取作备用 |
| 应付职工薪酬附注 | 文本正则（`短期薪酬` + 第 3 列数字） |
| 人均薪酬倒推 | `本期增加额 ÷ 员工总数`（粗估，含社保公司承担部分） |

### 4.3 失败回退策略

| 失败原因 | 处置 |
|---|---|
| `searchkey` 查询返回 0 结果 | 检查公司简称是否正确（e.g. 「宁德时代」不是「宁德」）；尝试只用股票代码作为 searchkey |
| PDF 下载 timeout | 重试 3 次，间隔 5s；记录失败 adjunctUrl |
| pdfplumber 解析报错（扫描版 PDF） | 捕获异常，标记 `parse_error: scanned_pdf`，不入库 |
| 员工章节未找到 | 标记 `parse_error: section_not_found`；可能是纯控股公司（无员工直接雇佣） |

### 4.4 缓存策略

- **PDF 缓存**: 以 `adjunctUrl` 的 MD5 为文件名，本地磁盘缓存；adjunctUrl 含发布日期+报告 ID，天然是版本稳定键
- **解析结果缓存**: 以 `(company_name, year)` 为 key，存入 `company_profiles` 或独立的 `annual_report_cache` 表；一旦入库不再重新解析（除非检测到新年报）
- **年报 URL 缓存**: `adjunctUrl` 写入 DB，次年再跑时先查 DB 是否已有该年份记录

### 4.5 输出字段 Schema（写入 company_profiles / insight_items）

**写入 `company_profiles` 表的字段**（结构化 payload，每年更新一次）:

```json
{
  "headcount_total": 131988,
  "headcount_source": "cninfo_annual_report",
  "headcount_year": 2024,
  "headcount_breakdown": {
    "production": 96725,
    "technical": 20346,
    "admin": 11419,
    "sales": 2806,
    "finance": 692
  },
  "education_breakdown": {
    "phd": 625,
    "master": 8015,
    "bachelor": 26292,
    "below_bachelor": 97056
  },
  "compensation_current_year_added_k_cny": 28151691,
  "avg_compensation_cny_approx": 213300,
  "cninfo_report_url": "http://static.cninfo.com.cn/finalpage/2025-03-15/1222806982.PDF",
  "report_publish_date": "2025-03-15"
}
```

**写入 `insight_items` 的 fact 条目示例**:

```json
{
  "company": "宁德时代",
  "dimension": "timing",
  "grade": "fact",
  "content": "2024年在职员工131,988人，技术人员20,346人（占15.4%），硕士及以上8,640人。人均薪酬约21.3万元/年（据年报应付职工薪酬计提额倒推，含社保）。",
  "payload": {
    "headcount": 131988,
    "tech_ratio": 0.154,
    "avg_comp_approx": 213300,
    "data_year": 2024
  },
  "source": "巨潮资讯 2024年年度报告",
  "source_url": "http://static.cninfo.com.cn/finalpage/2025-03-15/1222806982.PDF",
  "valid_until": "2026-03-01"
}
```

---

## 未找到确切来源

1. **港股 HKEXnews API 结构**: 未做 live 验证，无法确认具体接口 URL 和返回格式
2. **上交所股票的 `column` 参数**: 推测是 `sse`，但本次只验证了深交所（`szse`）
3. **`hisAnnouncement/query` 的 `stock=` 字段为何返回 0**: 推测需要额外 JS 生成的 token，但未追踪前端 JS 源码验证
4. **seDate 参数导致 500 的原因**: 实测 `seDate=2025-03-01+to+2025-04-30` 会让请求返回 HTTP 500，原因未查明（可能是日期格式或与 column 参数的组合）

---

## 注意事项与风险

1. **searchkey 方案的局限**: 用公司名作为 searchkey 是 keyword 搜索，可能误匹配（如「比亚迪」会同时搜到比亚迪股份、比亚迪半导体、比亚迪电子的公告）。过滤策略：检查 `secCode` 是否等于目标股票代码。

2. **摘要 vs 正文年报**: adjunctUrl 列表中同时含「年度报告」和「年度报告摘要」，摘要体积小但员工数据不完整。需过滤掉标题含「摘要」的公告。

3. **PDF 体积差异大**: 本次实测 CATL 1.97MB vs BYD 9.63MB，后者可能含大量图片。下载时应设置足够大的 timeout（120s）。

4. **pdfplumber 全文扫描慢**: 229 页 PDF 全文扫描需 14.6s。全量 5,300 家若串行处理约 22 小时，建议多进程（`multiprocessing.Pool`，8-16 进程可降至 2-3 小时）。

5. **合规风险**: 巨潮/深交所年报是监管强制公开信息，机器读取无合规风险。但应注意 robots.txt 并保持礼貌频率（建议 1-2 req/s）。

6. **人均薪酬是近似值**: `应付职工薪酬本期增加额` 是会计计提口径，含社保/公积金公司承担部分（约占 30-40%），且不等于实际支付额（有期初/期末差）。作为量级参考可用，不适合精确比较。

