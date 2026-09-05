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

⚠️ **这个站会间歇性地把页面渲染成完全空白**（body innerText 长度为 0），机构页和详情页都会。
撞上时「0 个岗」不是「这家没在招」，是我们没看见 —— reload 一次基本就好。所以取岗位卡要区分
「整页空白」（重试）和「渲染了但没有卡片」（真的没在招，别白等）。同理，它也会间歇性掐连接
（net::ERR_EMPTY_RESPONSE），单家机构打不开只记 fetch_complete=False，不许拖垮整源。

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
    # 详情页比机构页快一个数量级（实测中位 0.69s），不需要 25s 的耐心。
    DETAIL_TIMEOUT_MS = 9000
    # 逐岗正文上限：2026-09-05 live 全源 2,418 个岗 → 设 3000 覆盖全源。
    # 快档 daily 用 CRAWL_DETAIL_CAP=0 跳过（resolve_detail_cap），只抓列表骨架。
    _DETAIL_CAP = 3000
    # 连续这么多个岗都拿不到正文 → 认为站点这一轮不让抓了（它会掐连接），停掉正文这一段。
    # 列表已经拿到手，没必要为了正文把剩下两千多个岗每个都耗满两次 goto 超时。
    _DETAIL_ABORT_AFTER_FAILURES = 25
    # 正文这一段最多花多久。本机实测中位 0.69s/岗、2,418 个岗约 28 分钟，但 CI runner 在美国、
    # 每一跳都更慢 —— 没有闸就可能把整片 enrich shard 拖过 180min 超时，**连同这一片里另外
    # 一百多个源一起挂掉**。宁可这一晚少补一些正文，也不能拖垮一整片。
    _DETAIL_BUDGET_S = 1800
    # 每晚往后挪这么多作为起点。预算用完就停，若恒从第 0 个开始，尾部的岗**永远**补不到正文。
    # summary 在 upsert 里是「空值不覆盖」（jobs_db._PRESERVE_IF_EMPTY），所以轮转几晚就能
    # 覆盖全源，且已经补好的不会被后面的空值抹掉。
    _DETAIL_ROTATE_STRIDE = 600
    # 「整页没渲染出来」的判据：body 一个字都没有。实测空白页 innerText 长度恰为 0，
    # 而正常渲染的页面光顶部导航就有几十字 —— 所以这个阈值不会把「渲染了但没岗」误判成空白。
    _RENDERED_MIN_CHARS = 30

    # 正文三段（页面上的小标题 ↔ posDetails 的字段名）。
    # ⚠️ 刻意不收 posDetails.phone：那是 HR 的联系邮箱/电话，属于个人联系方式，不入库
    #    （同 gree adapter 忽略 PubName 的理由）。
    _BODY_SECTIONS = (("主要职责", "responsibilities"),
                      ("基本条件", "qualifications"),
                      ("具体要求", "requirements"))

    def should_skip(self, source_url: str) -> Optional[str]:
        return None  # SPA 入口页，HEAD 预检没有意义

    @classmethod
    def _collect(cls, page, state_key: str) -> list:
        """轮询到页面把带 state_key 的组件渲染出来，再把这些 state 取回来。

        ⚠️ 不能用 `wait_for_function` 一等了之：hash 路由是**同文档导航**，上一个机构的卡片
        还留在 DOM 里，条件会立刻为真、于是把上一家的岗位当成这一家的（第一版就是这么
        只抓到 2 个岗、还自称抓全了）。调用方必须先 reload 让文档真的换掉，这里只负责等渲染。

        ⚠️ 等待要给够：农银人寿 34 个岗实测 >8s 才渲染出来，只等 8s 会得到「0 个岗」这种
        看着正常、其实是漏抓的结果。等满 RENDER_TIMEOUT_MS 仍为空，才认「这家当期没在招」。
        """
        deadline = time.monotonic() + cls.RENDER_TIMEOUT_MS / 1000.0
        while True:
            found = page.evaluate(_COLLECT_JS, state_key) or []
            if found or time.monotonic() >= deadline:
                return found
            page.wait_for_timeout(cls.POLL_INTERVAL_MS)

    @classmethod
    def _page_is_blank(cls, page) -> bool:
        """整页一个字都没渲染出来 —— 此时「0 个岗」是我们没看见，不是对方没在招。"""
        try:
            text = page.evaluate("document.body ? (document.body.innerText || '') : ''") or ""
        except Exception:
            return True
        return len(text.strip()) < cls._RENDERED_MIN_CHARS

    def _open(self, page, url: str) -> None:
        """打开 hash 路由。hash 是**同文档导航**，不 reload 的话上一页的卡片还留在 DOM 里，
        会把上一家的岗位当成这一家的（模块 docstring 里那个「只抓到 2 个岗还自称抓全」）。"""
        page.goto(url, wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
        page.reload(wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)

    def _collect_positions(self, page, url: str) -> list:
        """取一家机构的岗位卡，**整页空白时重试一次**。

        ⚠️ 为什么要这层重试：这个站会间歇性地把详情/机构页渲染成完全空白（body 长度为 0），
        实测 14 家里撞上好几家，reload 一次基本就好。原实现只要 `_collect` 返回空就当
        「这家当期没在招」，于是这些机构的岗位**静默消失**、而 fetch_complete 还是 True ——
        正是 CLAUDE.md「接口返 0 不能证明对方没开」那条碑的同一个病。

        ⚠️ 只在**整页空白**时重试：页面确实渲染出来了、只是没有卡片，那才是真的没在招；
        对这种情况重试只会在每家身上白等一整个 RENDER_TIMEOUT_MS。
        """
        for attempt in (1, 2):
            self._open(page, url)
            found = self._collect(page, "posCardInfo")
            if found:
                return found
            if not self._page_is_blank(page):
                return []          # 渲染了、就是没岗
            logger.info("abchina: blank render on %s (attempt %d)", url, attempt)
        return []

    def _detail_of(self, page, job_id: str, want_name: str) -> Optional[dict]:
        """打开逐岗详情页，把解密后的 posDetails 读回来；拿不到就返回 None（留薄卡，不编）。

        ⚠️ 归属校验：详情里的 posName 必须与列表卡一致才收。reload 已经换了文档、正常不会
        串味，但「宁可漏一条正文，也不能把 A 岗的正文挂到 B 岗上」——这是产品红线。
        """
        for attempt in (1, 2):
            try:
                self._open(page, self.DETAIL_URL.format(job_publish_id=job_id))
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

        起点按天轮转，见 _DETAIL_ROTATE_STRIDE：预算用完就停的话，恒从头开始会让尾部的岗
        永远是薄卡。
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
        incomplete = False      # 有机构页打不开 → 这一轮不算抓全（见文末 fetch_complete）

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
                    orgs = self._collect(page, "batchCardInfo")
                    for org in orgs:
                        org_id = _clean(org.get("orgId"))
                        if not org_id:
                            continue
                        try:
                            found = self._collect_positions(
                                page, self.ORG_URL.format(recruit_type=recruit_type, org_id=org_id))
                        except Exception as exc:
                            # 这个站会间歇性掐连接（net::ERR_EMPTY_RESPONSE）。一家机构打不开
                            # 就把整源扔掉是错的取舍（同 sf_express 那次「末页少 2 条 → 2,164 个
                            # 在招岗全丢」）：记下没抓全，把已经拿到的交出去。
                            logger.warning("abchina: org %s (%s) failed: %s", org_id, recruit_type, exc)
                            incomplete = True
                            continue
                        for pos in found:
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

                # ── 逐岗正文 ──────────────────────────────────────────────────
                # 列表卡里一个字的正文都没有（posCardInfo 只有岗位名/地点/人数/截止），
                # 不补就是 100% 薄卡 —— 进不了 count_valid_active_jobs，等于这家公司
                # 在「必投清单健康覆盖」里恒为 0。正文只在详情页的 posDetails 里。
                self._fill_bodies(page, rows, resolve_detail_cap(self._DETAIL_CAP))
            finally:
                browser.close()

        if not rows:
            raise RuntimeError("abchina: no positions found on any org page")
        self.reported_total = len(rows)
        # 站点不自报总数（接口是密文），只能诚实记「看见的全部」；撞上限 / 有机构没打开时不算抓全。
        # ⚠️ fetch_complete=False 是有下游后果的（list-absence 撤岗会跳过这一轮），这正是我们要的：
        #    没抓全的那一轮绝不能被当成「剩下的都撤岗了」。
        self.fetch_complete = not truncated and not incomplete
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
