# 任务交接 Prompt：求职雷达 — 浏览器源产出硬化 + 顺丰重试

> 整段交给执行 agent。自包含：执行者对本会话无记忆，所需上下文都在这里。完成后由主 agent live 复核。

---

## 你的角色与使命

你是「求职雷达 / Job Radar」（`/Users/bytedance/Desktop/求职雷达`）的爬虫工程师。
上一批已为快手/B站/拼多多/vivo/比亚迪/美团打通并入库（已部署）。本任务两件事：

1. **产出硬化**：`kuaishou` 和 `byd` 两个**浏览器档** adapter 虽能抓到真岗，但**单跑实际产出远小于其岗位列表总量**，需修到「拿到列表的绝大部分（带合法 jd_url）」。
2. **顺丰重试**：上一批顺丰 SF Express 判为暂不可行（campus 站强制短信登录 / 旧社招域超时 / job.sf-express.com TLS 失败），本任务再攻一次，找到能抓在华真岗的公开链路；真不行就诚实记录。

---

## ⚠️ 铁律（违反即判定失败）

1. **不许编造、不许猜 slug/token 入库**。每个产出数字、每条 jd_url 都要有你**亲手 live 抓到**的证据。
2. **`jd_url` 必须是逐岗详情页真实链接**（HTTP 200、对应真实岗位），禁止列表/搜索/首页/登录页/猜测拼接。
3. **诚实记录上限/不可行**：若某源真实可抓上限就是远小于列表总量（如反爬/加密无法绕），**如实写明上限 + 原因 + 你试过什么**，给一个合理的 cap，不要伪造高产出、不塞垃圾岗（项目原则#4：指标诚实）。
4. **只抓在华岗**（大陆+港澳，排台湾），复用 `crawler/normalizer.py` 的 `is_china_location` / 新增的 `crawler/adapters/china_location.py`。
5. **最小化改动**：`kuaishou.py`/`byd.py` 已存在且验证可跑，**改进它们、别重写**；保持已有 4 处接线不变。

---

## 现状与产出差距（主 agent 2026-06-19 live 实测）

| adapter | 类型 | 岗位列表总量(声称) | 我实测单跑产出 | 差距根因(待你确认/解决) |
|---|---|---|---|---|
| `kuaishou` | playwright 拦截 | ~1487 国内社招 | **~39** | 只拦到首屏/首页响应，没有翻页/滚动拉全 |
| `byd` | playwright 点击捕获 | ~2163 社招 | **~19** | 逐个**点击岗位标题**捕获前端加密详情 URL → 极慢 + 封顶，绝大多数岗拿不到 jd_url |

> 列表总量是真的（接口能看到），问题在「能落库（带合法 jd_url）的产出」太少。

---

## Part A — 产出硬化

### A1. kuaishou（`crawler/adapters/kuaishou.py`）
- 现状：`PlaywrightAdapter`，`intercept_match = "/open/positions/simple"`，源 `https://zhaopin.kuaishou.cn/#/official/social/?workLocationCode=domestic`。页面 JS 带签名请求该接口，你拦截响应取岗。
- **要查清**：该列表是分页/无限滚动的吗？`/open/positions/simple` 是否带 page/offset 参数？单次响应只回一页（~39）？
- **修法（择优）**：
  - 优先 **在浏览器里翻页/滚动到底**，让页面把每一页都请求一遍，你**累积拦截所有页**的响应（参照 `playwright_base.py` 的 `_paginate` / 滚动逻辑）。
  - 或者：拿到首个签名请求后，**在页面上下文里 `page.evaluate` 复用其签名逻辑**翻页（较脆，慎用）。
- **目标**：拿到国内社招的绝大部分（接近列表总量），全部带合法 hash 详情 url `#/official/social/job-info/{id}`。

### A2. byd（`crawler/adapters/byd.py`）—— 本任务技术核心
- 现状：渲染社招首页，**逐个点击岗位标题**捕获 popup 里前端生成的**加密详情 URL**（`#/social/socialPositionDetails?{加密token}`），再用公开 `queryDetail` 取正文。逐个点击 = 慢 + 封顶。
- 已知公开接口：列表 `/portal-api/position/queryList`（~2163）、详情 `https://job.byd.com/portal/api/portal-api/position/queryDetail`。
- **关键调查（决定能否全量）**：那个加密 token 是 positionId 的前端加密。**先验证详情页是否能用「非加密」形式打开**：
  - 试 `https://job.byd.com/portal/pc/#/social/socialPositionDetails?positionId={queryList里的明文id}` 等变体，**curl/浏览器实测能否打开真实岗位**。
  - 若明文 id 能打开 → 直接用 queryList 的明文 id 批量构造 jd_url，**无需点击**，httpx 全量（最优，可能整个 adapter 降级为零浏览器）。
  - 若**只认加密 token** → 在页面 JS 里找加密算法/密钥（搜 bundle 里 encrypt/AES/CryptoJP 之类），用 `page.evaluate` 调用其加密函数把每个 positionId 批量转成 token（一次渲染、批量加密、不逐个点击）。
  - 两条都不通 → 诚实保留点击法但**设合理 cap**（如最近 N 个），记录「比亚迪受前端加密限制，全量不可行，上限 ≈ N」。
- **目标**：尽可能接近 2163 的全量带合法 jd_url；或给出诚实可达上限 + 原因。

---

## Part B — 顺丰 SF Express 重试

- 上次卡点：`campus.sf-express.com` 强制短信登录；旧社招域超时；`job.sf-express.com` TLS/HTTP2 失败。
- **重新调查**：找顺丰**当前的公开社招门户**（可能换域名/换平台）。用 WebSearch 找「顺丰 社会招聘 官网」，看它用哪套平台（自建 / moka / beisen / hotjob / workday / 北森）。
  - 若落在本项目已支持的平台（moka/beisen/hotjob/workday/feishu/...）→ 按对应 adapter 加源即可（URL 形态比公司名可靠：`SU{hash}/pb/social.html`=hotjob、`*.zhiye.com`=beisen、`app.mokahr.com`=moka、`*.feishu.cn`=feishu、`*.myworkdayjobs.com`=workday）。
  - 若自建门户但有不挂登录的公开 JSON 接口 → 仿 `ctrip`/`bilibili` 写/复用 httpx adapter。
  - 若全链路强制登录/短信/验证码 → **诚实判不可行**，写清试了哪些域名/接口、各自卡在哪。
- **目标**：抓到顺丰在华真岗并入库，或诚实记录不可行。

---

## 项目规范（务必遵守）

- **改 kuaishou/byd 不动 4 处接线**（已接好）；若 byd 降级为零浏览器，记得把 `byd` 从 run.py 的浏览器档挪进 `_HTTPX_SAFE_ADAPTERS` + probe.py 的 `_HTTPX_ADAPTERS` + 把 source 的 `crawl_method` 改 `http`（migration update）。
- **顺丰若需新 adapter**：4 处接线（`crawler/run.py` import+ADAPTERS+DOMESTIC_ADAPTERS[+_HTTPX_SAFE_ADAPTERS]、`crawler/probe.py`、`lib/source-adapters.ts`）；若复用现成平台 adapter 则只需加 source 行。
- **入库/改源**：`supabase/migrations/<最大序号+1>_seed_<desc>.sql`（文件名含 `_seed_`；先 `ls supabase/migrations` 取序号）。格式照抄 `153/154`（幂等 `where not exists` / `update`）。**别手改 DB**。
- **测试**：更新/新增 `crawler/test_*_adapter.py`（喂样例响应给 parse，断言抽岗 + jd_url 格式 + 翻页累积逻辑）；`cd crawler && python3 -m unittest discover -s . -t . -p "test_*.py"` 全绿。
- **质量门**：入库前过 `normalizer.validate_job_quality`。
- 同步受影响文档（CLAUDE.md「当前 source 状态」若涉及）。

## Live 访问 / 验证（沙箱）

- 联网 / DB **必须** Bash `dangerouslyDisableSandbox: true`；`set -a && source /Users/bytedance/Desktop/求职雷达/.env.local && set +a`；**绝不打印密钥**。
- 浏览器档需 chromium：`cd crawler && python3 -m playwright install chromium`（本机 `timeout` 命令不存在，别用它包裹）。
- **自测产出**：直接跑 adapter 代码 —— `python3 -c "from adapters.kuaishou import KuaishouAdapter as A; a=A(); j=a.parse(a.fetch('<source_url>')); print(len(j)); [print(x.title, x.jd_url) for x in j[:5]]"`（byd 同理）。报出**改进前后产出数对比**。
- jd_url 抽样 curl 看 200 + 是真详情页。
- 香港 jobs 库：`psql "$JOBS_DATABASE_URL" -c "..."`（会话 TZ=Asia/Shanghai，比时间用 `last_seen_at at time zone 'utc'`）。sources 在 Supabase（node + @supabase/supabase-js，REST 分页 1000/页）。

## 验收标准（主 agent 将 live 复核）

- [ ] **kuaishou**：单跑产出从 ~39 提升到接近列表全量（或给出诚实上限+原因），全部带合法 `job-info/{id}` jd_url。附改进前后数字 + 样例。
- [ ] **byd**：要么降级为「明文 id / 批量加密」全量、要么诚实 cap + 写清加密限制；产出数 + 样例 jd_url（抽样 curl 200）。
- [ ] **顺丰**：入库真岗（adapter/源 + live 证据 ≥1 页在华岗 + 抽样 jd_url 200）**或**诚实不可行报告（试了哪些域名/接口、卡点证据）。
- [ ] 全量 crawler 单测绿；4 处接线一致；migration `_seed_` 入库/改源。
- [ ] 返回总表：项 | 改进前→后产出 | 做法 | 样例 jd_url+HTTP | 备注/诚实上限。

## 提交

- 每块一个清晰 commit（改了什么/为什么/live 前后对比）。**push 前与主 agent/用户确认**（push 触发生产迁移与抓取），除非另有授权。
