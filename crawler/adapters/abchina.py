"""中国农业银行招聘门户（career.abchina.com）适配器（Playwright 读 React state）。

⚠️ **为什么不能用 httpx**：这个站的**响应体是加密的**。`new/getInfo` 明文返回一把 1024 位
RSA 公钥做密钥交换，之后 `org/*` / `orgPosition/*` / `pron/*` 的响应体是一长串 hex
（`object` 字段），页面用 `SSM_ExtSM4Dec_ECB_Pad_Array`（SM4-ECB）解开。
纯 JSON 请求体一律返「参数错误」，不带会话返「session超时」。
所以这里走浏览器——**不是因为它是 SPA，是因为明文只存在于浏览器内存里**。

⚠️ **它曾被误判成「公告制、没有逐岗详情页」**：岗位卡的 onClick 是
`window.open(location.origin + pathname + '#/PositionDetails/:' + jobPublishId)`，
在自动化浏览器里点一下**像没反应**，于是被当成没有详情页。
URL 里那个冒号是**字面量**（前端拼串时把路由占位符一起拼进去了），不是要替换的东西。

抓法（不拦接口、不解密，只读页面自己渲染完的 React state）：
  1. `#/{recruitType}` 列表页 → 每张「热招事项」卡的 state.batchCardInfo = {orgId, orgName, recruitType, batchName}
  2. `#/RecruitmentOrgDetails/{recruitType}/{orgId}` → 每张岗位卡 `.cardWrapper111` 的
     state.posCardInfo = {posName, deadline, numbers, workplace, jobPublishId, orgName, jobTypeName}
  3. jd_url 用模板拼（与站点 onClick 逐字一致）
  4. 逐岗 `#/PositionDetails/:{jobPublishId}` → state.posDetails 的
     responsibilities / qualifications / requirements 三段 = 正文（快档 CRAWL_DETAIL_CAP=0 跳过）

⚠️ **列表卡里一个字正文都没有**（posCardInfo 只有岗位名/地点/人数/截止）。不补正文就是
100% 薄卡：进不了 count_valid_active_jobs，这家在必投健康覆盖里恒为 0
（2026-09-05 实测线上 2,418 个在招岗 **全部** summary 为 NULL）。正文只在逐岗详情页。

⚠️ **必须先加载一次首页把会话建起来**（首页会自己打 `new/getInfo` 换密钥 + 拿 SESSION cookie）。
冷启动直接 goto `#/99` 只会渲染出 222 字的空壳、永远等不到卡片——实测就是这样一次都不出数据。
先 `goto(入口页, networkidle)` 再走 hash 路由，46 个机构 3 秒内就出来了。

⚠️ **这个 SPA 渲染慢**：即便会话已建好，机构页首帧到出卡片也要几秒。用 `wait_for_function`
等到真出现卡片，不要用固定 sleep（我第一次等 6 秒看到空壳，据此错判「直接 hash 导航打不开」）。
"""
import json
import logging
import time
from typing import List, Optional

from .base import BaseAdapter, RawJob, resolve_detail_cap, resolve_list_cap

logger = logging.getLogger(__name__)

_ENTRY = "https://career.abchina.com/build/index.html"

# 浏览器 UA：与 playwright_base 同口径。这个站对 UA 不算敏感，但无头浏览器带爬虫 UA
# 是自找麻烦，且真实浏览器行为才是我们在这里想复现的东西。
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 招聘类型：站点顶栏「校园招聘」= 99 / 「社会招聘」= 100（hash 路由里就是这个数字）。
# 「专项招聘」当前无公开岗位板块，不猜它的编号。
_RECRUIT_TYPES = ((99, "校招"), (100, "社招"))

# 从已渲染的 React 组件里取 state 的公共前缀（React 16 是 __reactInternalInstance$，17+ 是 __reactFiber$）。
# 两个页面各自的固定文案：只要页面真渲染完了，这段一定在。用它把「这家确实没在招」
# 和「页面根本没渲染出来」区分开 —— 两者都表现为「0 个岗」，但一个正常、一个是漏抓。
# ⚠️ 两页的文案不一样，别混用：列表页没有「在招岗位」四个字，拿它去判会把每一轮都误判成漏抓。
_LIST_RENDERED_MARKER = "招聘机构"   # `#/{recruitType}` 列表页（社招当期没岗时也有这块）
_ORG_RENDERED_MARKER = "在招岗位"    # `#/RecruitmentOrgDetails/...` 机构页

_COLLECT_JS = """
(stateKey) => {
  const seen = new Map();
  for (const el of document.querySelectorAll('*')) {
    const fk = Object.keys(el).find(k => k.startsWith('__reactInternalInstance$') || k.startsWith('__reactFiber$'));
    if (!fk) continue;
    let fiber = el[fk];
    for (let i = 0; i < 3 && fiber; i++) {
      const st = fiber.stateNode && fiber.stateNode.state;
      const info = st && st[stateKey];
      if (info && (info.orgId || info.jobPublishId)) {
        seen.set(String(info.jobPublishId || info.orgId), info);
        break;
      }
      fiber = fiber.return;
    }
  }
  return [...seen.values()].map(o => JSON.parse(JSON.stringify(o)));
}
"""


# 详情页把**解密后**的岗位详情挂在 React state 的 posDetails 上，三段正文
# responsibilities / qualifications / requirements 就是页面上的「主要职责 / 基本条件 / 具体要求」。
# 读 state 而不是抓 innerText：innerText 会把顶部导航、「申请岗位收藏」按钮、页脚一起裹进来，
# 那些模板文案对每个岗都一样，混进 summary 只会污染检索。
_DETAIL_JS = """
() => {
  for (const el of document.querySelectorAll('*')) {
    const fk = Object.keys(el).find(k => k.startsWith('__reactInternalInstance$') || k.startsWith('__reactFiber$'));
    if (!fk) continue;
    let fiber = el[fk];
    for (let i = 0; i < 4 && fiber; i++) {
      const st = fiber.stateNode && fiber.stateNode.state;
      const d = st && st.posDetails;
      if (d && (d.responsibilities || d.qualifications || d.requirements)) {
        return JSON.parse(JSON.stringify(d));
      }
      fiber = fiber.return;
    }
  }
  return null;
}
"""



def _clean(value) -> str:
    return str(value or "").strip()


class AbchinaAdapter(BaseAdapter):
    name = "abchina"

    DETAIL_URL = _ENTRY + "#/PositionDetails/:{job_publish_id}"
    ORG_URL = _ENTRY + "#/RecruitmentOrgDetails/{recruit_type}/{org_id}"
    LIST_URL = _ENTRY + "#/{recruit_type}"
    # 渲染慢：机构页首帧到出卡片实测 6~10s。等「卡片出现」而不是等固定秒数。
    RENDER_TIMEOUT_MS = 25000
    POLL_INTERVAL_MS = 700
    GOTO_TIMEOUT_MS = 45000
    _MAX_JOBS = 4000
    # 详情页比机构页快一个数量级（本机实测中位 0.69s），不需要 25s 的耐心。
    DETAIL_TIMEOUT_MS = 9000
    # 逐岗正文条数上限：2026-09-05 live 全源 2,603 个岗 → 设 3000 覆盖全源。
    # 快档 daily 用 CRAWL_DETAIL_CAP=0 跳过（resolve_detail_cap），只抓列表骨架。
    _DETAIL_CAP = 3000
    # 连续这么多个岗都拿不到正文 → 认为站点这一轮不让抓了（它会掐连接），停掉正文这一段。
    # 列表已经拿到手，没必要为了正文把剩下两千多个岗每个都耗满两次 goto 超时。
    _DETAIL_ABORT_AFTER_FAILURES = 25
    # 正文这一段最多花多久。**这个数字是量出来的，不是拍的**（2026-09-05 查 enrich-crawl 台账）：
    #   · 农行落在 shard 1，最近两轮 61 / 57 分钟，离 180min 超时上限有约 120 分钟余量；
    #   · 但同期 shard 2 是 172 / 148 分钟 —— 2026-09-01 那轮 181 分钟**被 GitHub 取消**。
    #     分片是按源数贪心装箱的，成员会随源增减漂移，所以别把「今天有余量」当永久事实。
    # 取 15 分钟：占上限 8%，即便耗时整体上浮也不会是压垮某一片的那根稻草。
    # 覆盖速度：CI 到这个站按 1.5~2.5s/岗算 ≈ 360~600 岗/晚 → 2,603 个岗约 5~7 晚补齐。
    # 这是刻意的取舍：**限速优先于覆盖速度**——一周覆盖全量可以接受，挤掉别的浏览器任务不行。
    _DETAIL_BUDGET_S = 900
    # 每晚往后挪这么多作为起点。预算用完就停，若恒从第 0 个开始，尾部的岗**永远**补不到正文。
    # summary 在 upsert 里是「空值不覆盖」（jobs_db._PRESERVE_IF_EMPTY），所以轮转几晚就能
    # 覆盖全源，且已经补好的不会被后面的空值抹掉。
    _DETAIL_ROTATE_STRIDE = 600

    # 正文三段（页面上的小标题 ↔ posDetails 的字段名）。
    # ⚠️ 刻意不收 posDetails.phone：那是 HR 的联系邮箱/电话，属于个人联系方式，不入库
    #    （同 gree adapter 忽略 PubName 的理由）。
    _BODY_SECTIONS = (("主要职责", "responsibilities"),
                      ("基本条件", "qualifications"),
                      ("具体要求", "requirements"))

    def should_skip(self, source_url: str) -> Optional[str]:
        return None  # SPA 入口页，HEAD 预检没有意义

    @classmethod
    def _collect(cls, page, state_key: str, marker: str = None):
        """轮询到页面把带 state_key 的组件渲染出来，再把这些 state 取回来。

        ⚠️ 不能用 `wait_for_function` 一等了之：hash 路由是**同文档导航**，上一个机构的卡片
        还留在 DOM 里，条件会立刻为真、于是把上一家的岗位当成这一家的（第一版就是这么
        只抓到 2 个岗、还自称抓全了）。调用方必须先 reload 让文档真的换掉，这里只负责等渲染。

        ⚠️ 等待要给够：农银人寿 34 个岗实测 >8s 才渲染出来，只等 8s 会得到「0 个岗」这种
        看着正常、其实是漏抓的结果。等满 RENDER_TIMEOUT_MS 仍为空，才认「这家当期没在招」。

        返回 `(找到的 state 列表, 页面是否确实渲染完了)`。第二个值是**诚实度开关**：
        CI 比本机慢，2026-09-05 首轮线上就比本机少抓了 162 个岗（2,418 vs 2,580），
        而当时 fetch_complete 还是 True —— 正是「没抓全却自称抓全」。有了它，
        渲染没等到的机构会把 fetch_complete 打成 False，不再假装抓全。
        """
        deadline = time.monotonic() + cls.RENDER_TIMEOUT_MS / 1000.0
        while True:
            found = page.evaluate(_COLLECT_JS, state_key) or []
            if found:
                return found, True
            if time.monotonic() >= deadline:
                # 等到头还是 0 个 —— 是「这家真没在招」还是「页面压根没渲染出来」？
                # 靠页面固定文案区分：marker 在 = 渲染完了、就是没岗（正常）；
                # marker 不在 = 我们没等到 = **漏抓**，调用方据此把 fetch_complete 打成 False。
                try:
                    rendered = marker in page.inner_text("body") if marker else True
                except Exception:
                    rendered = False
                return [], rendered
            page.wait_for_timeout(cls.POLL_INTERVAL_MS)

    def _scan_org(self, page, recruit_type, org):
        """打开一个机构页并取回岗位卡的 state。返回 (岗位列表, 页面是否确实渲染完了)。"""
        org_id = _clean(org.get("orgId"))
        try:
            page.goto(self.ORG_URL.format(recruit_type=recruit_type, org_id=org_id),
                      wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
            # 只改 hash 是同文档导航，上一家的卡片会留在 DOM 里 → 必须真的重载。
            page.reload(wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
            return self._collect(page, "posCardInfo", _ORG_RENDERED_MARKER)
        except Exception as exc:
            # ⚠️ 单个机构页抖一下（实测撞到过 net::ERR_EMPTY_RESPONSE）不该炸掉整轮 ——
            # 前面几十家已经抓到的岗会跟着一起丢，run.py 还会把整个源记成 failed。
            print(f"[abchina] 机构 {org.get('orgName') or org_id} 打开失败：{type(exc).__name__}")
            return [], False

    def _detail_of(self, page, job_id: str, want_name: str) -> Optional[dict]:
        """打开逐岗详情页，把解密后的 posDetails 读回来；拿不到就返回 None（留薄卡，不编）。

        ⚠️ 归属校验：详情里的 posName 必须与列表卡一致才收。reload 已经换了文档、正常不会
        串味，但「宁可漏一条正文，也不能把 A 岗的正文挂到 B 岗上」——这是产品红线。
        """
        for attempt in (1, 2):
            try:
                page.goto(self.DETAIL_URL.format(job_publish_id=job_id),
                          wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                # 同 _scan_org：只改 hash 是同文档导航，上一个岗的正文会留在 DOM 里。
                page.reload(wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                deadline = time.monotonic() + self.DETAIL_TIMEOUT_MS / 1000.0
                detail = None
                while True:
                    detail = page.evaluate(_DETAIL_JS)
                    if detail or time.monotonic() >= deadline:
                        break
                    page.wait_for_timeout(self.POLL_INTERVAL_MS)
            except Exception as exc:                      # 单个岗的失败不该拖垮整源
                logger.info("abchina: detail %s failed (attempt %d): %s", job_id, attempt, exc)
                continue
            if detail:
                got = _clean(detail.get("posName"))
                if want_name and got and got != want_name:
                    logger.warning("abchina: detail/list posName mismatch for %s (%r vs %r), skipped",
                                   job_id, got, want_name)
                    return None
                return detail
        return None

    def _fill_bodies(self, page, rows: list, cap: int) -> None:
        """逐岗补正文，就地写进 row["_detail"]。受 cap（条数）与 _DETAIL_BUDGET_S（墙钟）双重约束。

        起点按天轮转（_DETAIL_ROTATE_STRIDE）：预算用完就停的话，恒从第 0 个开始会让尾部的岗
        永远是薄卡。

        ⚠️ 不许为了让台账翻绿去补个位数 —— 那是刷指标。这里要么按预算真补一批，要么不补。
        """
        total = len(rows)
        if not cap or not total:
            return
        start = (time.gmtime().tm_yday * self._DETAIL_ROTATE_STRIDE) % total
        deadline = time.monotonic() + self._DETAIL_BUDGET_S
        filled = misses = 0
        for offset in range(min(cap, total)):
            if time.monotonic() >= deadline:
                logger.info("abchina: detail budget spent, %d/%d bodies this run "
                            "(rest picked up on later runs)", filled, total)
                break
            row = rows[(start + offset) % total]
            detail = self._detail_of(page, _clean(row.get("jobPublishId")),
                                     _clean(row.get("posName")))
            if detail:
                row["_detail"] = detail
                filled += 1
                misses = 0
                continue
            misses += 1
            if misses >= self._DETAIL_ABORT_AFTER_FAILURES:
                logger.warning("abchina: %d consecutive detail misses, stopping body pass "
                               "(list data kept, %d bodies filled)", misses, filled)
                break

    @classmethod
    def _summary_of(cls, row: dict) -> Optional[str]:
        detail = (row or {}).get("_detail") or {}
        parts = []
        for label, key in cls._BODY_SECTIONS:
            text = _clean(detail.get(key))
            if text:
                parts.append("%s\n%s" % (label, text))
        return "\n\n".join(parts) or None

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        self.reported_total = None
        self.fetch_complete = False
        cap = resolve_list_cap(self._MAX_JOBS)
        rows: List[dict] = []
        seen_jobs = set()
        truncated = False
        all_rendered = True
        missed_orgs: List[str] = []
        pending: List[tuple] = []   # 第一轮没渲染出来的机构，留给下面的重试轮

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="zh-CN", viewport={"width": 1440, "height": 900},
                                    user_agent=_UA)
            try:
                # 见模块 docstring：不先过一遍首页，后面所有 hash 路由都只会渲染出空壳。
                page.goto(_ENTRY, wait_until="networkidle", timeout=self.GOTO_TIMEOUT_MS)

                for recruit_type, job_type in _RECRUIT_TYPES:
                    page.goto(self.LIST_URL.format(recruit_type=recruit_type),
                              wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                    orgs, orgs_rendered = self._collect(page, "batchCardInfo", _LIST_RENDERED_MARKER)
                    if not orgs_rendered:
                        all_rendered = False
                    for org in orgs:
                        org_id = _clean(org.get("orgId"))
                        if not org_id:
                            continue
                        positions, rendered = self._scan_org(page, recruit_type, org)
                        if not rendered:
                            # 这家没等到渲染 —— 它有多少岗我们不知道，别当成 0，留给重试轮。
                            pending.append((recruit_type, job_type, org))
                        for pos in positions:
                            job_id = _clean(pos.get("jobPublishId"))
                            if not job_id or job_id in seen_jobs:
                                continue
                            if len(rows) >= cap:
                                truncated = True
                                break
                            seen_jobs.add(job_id)
                            pos["_job_type"] = job_type
                            pos["_batch_name"] = _clean(org.get("batchName")) or None
                            rows.append(pos)
                        if truncated:
                            break
                    if truncated:
                        break

                # ⚠️ 重试轮：这个站慢且不稳，同一轮里 9 个机构页等 25s 都没渲染出来是实测发生过的
                # （线上首轮因此比本机少抓 162 个岗）。等所有机构走完再回头补一次 —— 那会儿
                # 瞬时拥塞多半过去了，而且不会在原地反复空等。只补一次，不做无限重试。
                for recruit_type, job_type, org in list(pending):
                    if truncated:
                        break
                    positions, rendered = self._scan_org(page, recruit_type, org)
                    if not rendered:
                        all_rendered = False
                        missed_orgs.append(_clean(org.get("orgName")) or _clean(org.get("orgId")))
                        continue
                    for pos in positions:
                        job_id = _clean(pos.get("jobPublishId"))
                        if not job_id or job_id in seen_jobs:
                            continue
                        if len(rows) >= cap:
                            truncated = True
                            break
                        seen_jobs.add(job_id)
                        pos["_job_type"] = job_type
                        pos["_batch_name"] = _clean(org.get("batchName")) or None
                        rows.append(pos)

                # ── 逐岗正文 ──────────────────────────────────────────────────
                # 放在列表（含重试轮）之后：正文是「锦上添花」，绝不能因为它挤掉列表的完整性。
                # 快档 CRAWL_DETAIL_CAP=0 时这一步整段跳过。
                self._fill_bodies(page, rows, resolve_detail_cap(self._DETAIL_CAP))
            finally:
                browser.close()

        if not rows:
            raise RuntimeError("abchina: no positions found on any org page")
        if missed_orgs:
            print(f"[abchina] {len(missed_orgs)} 个机构页没等到渲染（本轮不算抓全）："
                  f"{'、'.join(missed_orgs[:8])}{' …' if len(missed_orgs) > 8 else ''}")
        self.reported_total = len(rows)
        # 站点不自报总数（接口是密文），只能诚实记「看见的全部」。
        # 撞上限、或有机构页没等到渲染 → 都不算抓全（后者是线上实测过的漏抓来源）。
        self.fetch_complete = (not truncated) and all_rendered
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = _clean(row.get("jobPublishId"))
            title = _clean(row.get("posName"))
            if not (job_id and title):
                continue
            jd_url = self.DETAIL_URL.format(job_publish_id=job_id)
            jobs.append(RawJob(
                company="", title=title,
                location=_clean(row.get("workplace")) or None,
                job_type=_clean(row.get("_job_type")) or None,
                # 正文来自逐岗详情页的 posDetails（快档 CRAWL_DETAIL_CAP=0 时没跑详情 → None）。
                summary=self._summary_of(row),
                jd_url=jd_url, apply_url=jd_url,
                deadline=_clean(row.get("deadline"))[:10] or None,
            ))
        return jobs
