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
📌 2026-10-12 复核：`new/getInfo` 是应用外壳在**每次文档加载**时自己发的（读 bundle），当天冷启动
直接开 `index.html#/99` 也渲染出了 46 个机构。上面那次「222 字空壳」更像是页面被对方清空（见下一条），
不是缺会话。先过首页这一步留着（无害、不多加载文档），但别再把它当必要条件去推别的结论。

⚠️ **这个 SPA 渲染慢**：即便会话已建好，机构页首帧到出卡片也要几秒。用 `wait_for_function`
等到真出现卡片，不要用固定 sleep（我第一次等 6 秒看到空壳，据此错判「直接 hash 导航打不开」）。

⚠️ **页面会被对方自己清空（2026-10-12 查实）**——2026-09-05 ~ 10-11 这条源 39 轮里 35 轮 failed 的真因。
❌ 现象：`Page.goto: Navigation to "…#/100" is interrupted by another navigation to "…/99/262"`，
   每个机构页都「打开失败」，偶尔报 `net::ERR_EMPTY_RESPONSE` / `chrome-error://chromewebdata`。
✅ 根因：入口页引的 `sm3/core.js`（名字是加密库，里面夹着一段检测）在**每次文档加载**时比
   `console.table(大数组)` 与 `console.log(大数组)` 的耗时——有调试协议接着（DevTools，或 Playwright 走的 CDP）
   时前者慢一个数量级。命中就 `for (k in window) window[k] = 0`，其中 `location = 0` 让主文档自己跳去
   `…/build/0`，对方网关对它回空响应，页面变成 chrome-error。
   · 证据：CDP `Network.requestWillBeSent` 的 initiator 调用栈落在 sm3/core.js 的 eval 代码里（`_$V`）；
     不挂自动化的 headless Chrome 连开 6 次全正常；CI 与本机报错逐字相同（不是 CI 环境问题）。
   · 概率性的（`console.log` 那一下要计到 ≥1ms 才判），随机器快慢波动很大：诊断时多挂了 CDP 网络监听，
     4 次新加载 3 次被清空；本文件自己的流程本机跑了 17 次（多数只加载 1 次文档），5 次撞上。那 39 轮拆开看：
     对方还在招的 09-05~10-08 共 35 轮 = 3 轮成功、1 轮部分成功、31 轮失败；10-09 起的 4 轮是
     对方已经没在招、被记成了失败（见下一条）。所以有的晚上整轮没撞上、看着像「偶尔能成」。
   · 旧代码不认识它：被清空后的页面每次导航都被那次跳转打断，被当成「单个机构抖了一下」吞掉，
     最后崩在没保护的 `goto(#/100)` ——报错讲的是导航，已经读到的岗也跟着全丢。
✅ 现行处理：`_note_navigation` 记下「主文档被带去了招聘应用之外」，**一发现就停**（`_PageLeft`）：
   已读到的岗照常返回、本轮不算抓全；一个都没读到就带着真实原因失败。
🚫 **不重试、不绕**：被清空后不重新加载再碰运气，也不屏蔽 / 改写对方的检测脚本——那是对方明确设的
   技术防护，绕不绕不是 adapter 能自己定的事（要改先问创始人）。能做的只有**少加载文档**：
   每次 reload 都是它再判一次的机会，列表页之间因此走「退回首页再进」而不是 reload。

⚠️ **「0 个岗」只认对方自己写的空态文案，不认固定标题**（2026-10-12，读 bundle 的 render 分支 + 线上核对）：
列表页「热招事项」、机构页「在招岗位」是固定标题，接口没回来 / 被限流（它回「请求过于频繁」时组件不更新）
时照样在页面上。接口成功且 0 条，页面才写「暂无热招事项」/「该机构暂无在招岗位」。
顶栏上的三个板块（校招 / 社招 / 专项）都写着「暂无热招事项」= 对方当期确实没在招，返回 0 岗（run.py 记 success）；
没读到岗、对方又没这么说 = 我们没读到，必须抛错（记 failed）。
"""
import json
import logging
import time
from typing import List, Optional, Tuple

from .base import BaseAdapter, RawJob, exc_brief, resolve_detail_cap, resolve_list_cap

logger = logging.getLogger(__name__)

_ENTRY = "https://career.abchina.com/build/index.html"
# 反调试脚本清空页面时主文档跳去的地址：`location = 0` 按入口文档解析出来就是它（2026-10-12 实测）。
_WIPE_TARGET = _ENTRY.rsplit("/", 1)[0] + "/0"

# 浏览器 UA：与 playwright_base 同口径。这个站对 UA 不算敏感，但无头浏览器带爬虫 UA
# 是自找麻烦，且真实浏览器行为才是我们在这里想复现的东西。
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 板块：站点顶栏「校园招聘」= 99 / 「社会招聘」= 100 / 「专项招聘」= 102（hash 路由里就是这个数字；
# 102 是 2026-10-12 点顶栏得到的，不是猜的）。第二项是写给岗位的招聘类型提示：
# 专项板块列的是博士后工作站这类机构，岗位该归校招还是社招没核过 → 不给提示，交逐岗分类去判。
# ⚠️ 「对方当期没在招」要这里列的每个板块都这么说才成立，所以顶栏上有的板块都得列进来。
# bundle 的路由清单里还有 103 / 498~501 五个同类列表页，顶栏没有入口，不猜。
_RECRUIT_TYPES = ((99, "校招"), (100, "社招"), (102, None))
_BOARD_NAMES = {99: "校招", 100: "社招", 102: "专项"}

# 对方页面自己的空态文案：接口**成功返回 0 条**时才出现（站点 bundle 的 render 分支，2026-10-12 线上逐字核过）。
# 用它把「对方说没有」和「我们没读到」分开 —— 两者都表现为「0 个岗」，一个正常、一个是漏抓。
# ⚠️ 别退回去认固定标题（旧判据是「招聘机构」「在招岗位」）：标题在数据回来之前、接口被限流时都在，
#    认它等于把「没读到」记成「没在招」。两页文案不一样，别混用。
_LIST_EMPTY_MARKER = "暂无热招事项"        # `#/{recruitType}` 列表页
_ORG_EMPTY_MARKER = "该机构暂无在招岗位"   # `#/RecruitmentOrgDetails/...` 机构页
# 列表页的固定标题，只用来判「列表组件还挂在页面上没有」，不用来判数据回没回来。
_LIST_HEADER = "热招事项"

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


# 列表页「招聘机构」那一栏的机构清单（state.areaData）：对方给每个机构带一个 flag，页面按
# `disabled: '1' != flag` 画按钮 —— '1' 才可点，也就是对方自己标的「这个板块里它在招」。
# 返回 [{name, open}]；清单还没渲染出来返回 null。只用来给「暂无热招事项」对账（见 _open_list）。
_AREA_ORGS_JS = """
() => {
  for (const el of document.querySelectorAll('*')) {
    const fk = Object.keys(el).find(k => k.startsWith('__reactInternalInstance$') || k.startsWith('__reactFiber$'));
    if (!fk) continue;
    let fiber = el[fk];
    for (let i = 0; i < 10 && fiber; i++) {
      const st = fiber.stateNode && fiber.stateNode.state;
      if (st && Array.isArray(st.areaData) && st.areaData.length) {
        const orgs = [];
        for (const area of st.areaData) {
          for (const org of (area && area.children) || []) {
            orgs.push({name: String(org.label), open: String(org.flag) === '1'});
          }
        }
        return orgs;
      }
      fiber = fiber.return;
    }
  }
  return null;
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


class _PageLeft(RuntimeError):
    """主文档被对方脚本带离了招聘应用（见模块 docstring「页面会被对方自己清空」）。

    不是「某个机构页抖了一下」：页面已经没了，这一轮到此为止，不重试。"""

    def __init__(self, target: str):
        super().__init__(target)
        self.target = target


class AbchinaAdapter(BaseAdapter):
    name = "abchina"

    DETAIL_URL = _ENTRY + "#/PositionDetails/:{job_publish_id}"
    ORG_URL = _ENTRY + "#/RecruitmentOrgDetails/{recruit_type}/{org_id}"
    LIST_URL = _ENTRY + "#/{recruit_type}"
    HOME_URL = _ENTRY + "#/"
    # 主文档被带去了哪（None = 还在招聘应用里）。由 _note_navigation 写，每轮 _harvest 开头清掉。
    _left_for: Optional[str] = None
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

    def _note_navigation(self, request) -> None:
        """`page.on("request")` 的回调：记下「主文档被带去了招聘应用之外的地址」。

        我们自己的 goto / reload 目标永远是入口文档（只差 hash）。主文档去请求别的 http(s) 地址，
        就是页面被带走了 —— 查实过的成因是反调试脚本的 `location = 0`（→ `…/build/0`，见模块 docstring）。
        只记第一次：后面的自动重试没有信息量。浏览器自己的 chrome-error 页不算（那是结果，不是谁带走的）。
        """
        try:
            if not request.is_navigation_request() or request.frame.parent_frame is not None:
                return
            target = request.url
        except Exception:      # 取不到 frame（如 service worker 的请求）= 不是主文档导航
            return
        if (self._left_for is None and target.startswith(("http://", "https://"))
                and target.split("#", 1)[0].split("?", 1)[0] != _ENTRY):
            self._left_for = target

    def _raise_if_left(self) -> None:
        if self._left_for:
            raise _PageLeft(self._left_for)

    @staticmethod
    def _left_reason(target: str) -> str:
        """给人看的一句话（会进 crawl_runs.error_message）：先说看到了什么，成因只在查实过的那一种上写。"""
        if target == _WIPE_TARGET:
            return (f"页面被对方的反调试脚本清空并跳到 {target}"
                    "（它发现浏览器被调试协议接管就会这么做，见 adapters/abchina.py 文件头）")
        return f"主文档被带离招聘应用，跳到 {target}（原因没查过，不是已知的 {_WIPE_TARGET} 那一种）"

    def _note(self, message: str) -> None:
        """记一笔「哪一页没给出答案、为什么」：打印，并留给 _harvest 拼进报错。
        报错进 crawl_runs.error_message；CI 的 stdout 是块缓冲，被杀的那一片尾巴日志留不住。"""
        print(f"[abchina] {message}")
        self.__dict__.setdefault("_notes", []).append(message)

    @staticmethod
    def _body_text(page) -> Optional[str]:
        """页面正文；读不到（页面正在换文档）返回 None —— 「读不到」往哪边算由调用方定，别在这里替它选。"""
        try:
            return page.inner_text("body") or ""
        except Exception:
            return None

    def _poll(self, page, probe, timeout_ms: int):
        """每隔 POLL_INTERVAL_MS 问一次 probe()：拿到真值就返回它，到点还没有返回 None。

        每一轮先看页面是不是已经被对方带走。所有「等页面」的地方都走这里，免得哪个循环忘了查。
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            self._raise_if_left()
            value = probe()
            if value:
                return value
            if time.monotonic() >= deadline:
                return None
            page.wait_for_timeout(self.POLL_INTERVAL_MS)

    def _collect(self, page, state_key: str, empty_marker: str) -> Tuple[List[dict], bool]:
        """轮询到页面把带 state_key 的组件渲染出来，再把这些 state 取回来。

        ⚠️ 不能用 `wait_for_function` 一等了之：hash 路由是**同文档导航**，上一个机构的卡片
        还留在 DOM 里，条件会立刻为真、于是把上一家的岗位当成这一家的（第一版就是这么
        只抓到 2 个岗、还自称抓全了）。调用方必须先让旧内容真的离开页面（机构页 reload、
        列表页退回首页再进，见 _open_list），这里只负责等渲染。

        ⚠️ 等待要给够：农银人寿 34 个岗实测 >8s 才渲染出来，只等 8s 会得到「0 个岗」这种
        看着正常、其实是漏抓的结果。

        返回 `(找到的 state 列表, 页面是否给出了确定答案)`。第二个值是**诚实度开关**：
        有卡片 = 答了；页面写着 empty_marker（对方自己的空态文案）= 答了「没有」；
        等满 RENDER_TIMEOUT_MS 两样都没有 = **没答**，调用方据此把 fetch_complete 打成 False。
        CI 比本机慢，2026-09-05 首轮线上就比本机少抓了 162 个岗（2,418 vs 2,580），
        而当时 fetch_complete 还是 True —— 正是「没抓全却自称抓全」。
        """
        def probe():
            found = page.evaluate(_COLLECT_JS, state_key) or []
            if found:
                return found, True
            if empty_marker in (self._body_text(page) or ""):    # 读不到正文 = 还没答
                return [], True
            return None

        return self._poll(page, probe, self.RENDER_TIMEOUT_MS) or ([], False)

    def _empty_list_confirmed(self, page, board: str) -> bool:
        """板块写着「暂无热招事项」时，拿同一页上对方的「招聘机构」清单对一遍账。

        「暂无热招事项」只说明没有热招事项卡，而机构正是靠这些卡枚举的：清单里还有机构标着在招
        （或清单没渲染出来、对不了账），就不能把这个板块记成「对方没在招」。
        """
        orgs = self._poll(page, lambda: page.evaluate(_AREA_ORGS_JS), self.RENDER_TIMEOUT_MS)
        if orgs is None:
            self._note(f"{board}：写着「{_LIST_EMPTY_MARKER}」，但机构清单没渲染出来，对不了账")
            return False
        marked_open = [_clean(org.get("name")) for org in orgs if org.get("open")]
        if marked_open:
            self._note(f"{board}：写着「{_LIST_EMPTY_MARKER}」，但对方把 {len(marked_open)} 个机构标成在招"
                       f"（{'、'.join(marked_open[:8])}），靠热招事项卡枚举机构漏了它们")
            return False
        return True

    def _open_list(self, page, recruit_type) -> Tuple[List[dict], bool]:
        """打开一个板块的列表页，取回「热招事项」卡的 state。返回 (机构列表, 页面是否给出了确定答案)。

        ⚠️ 列表页之间只差 hash、且是同一个路由组件：从 `#/99` 直接跳 `#/100` 组件不重挂，上一个板块的
        卡片 / 「暂无热招事项」会留在页面上，直到新请求回来——新请求要是没回来（或被限流，组件不更新），
        读到的就是上一个板块的答案。所以页面上还挂着列表时，先退回首页让它卸载，再进下一个板块。
        不用 reload：每多加载一次文档，就多给对方的反调试脚本一次清空页面的机会。
        """
        board = f"{_BOARD_NAMES.get(recruit_type, '')}板块 #/{recruit_type}"

        def list_unmounted():
            text = self._body_text(page)
            return text is not None and _LIST_HEADER not in text

        try:
            self._raise_if_left()
            # 读不到正文按「还挂着」算：这里判错的方向必须是多退一次首页，不能是少退一次。
            if not list_unmounted():
                page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                if not self._poll(page, list_unmounted, self.RENDER_TIMEOUT_MS):
                    self._note(f"{board}：退回首页后上一个列表一直没卸载，读到的是谁的说不清")
                    return [], False
            page.goto(self.LIST_URL.format(recruit_type=recruit_type),
                      wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
            orgs, answered = self._collect(page, "batchCardInfo", _LIST_EMPTY_MARKER)
            if not answered:
                self._note(f"{board}：既没出热招事项卡，也没写「{_LIST_EMPTY_MARKER}」")
            elif not orgs and not self._empty_list_confirmed(page, board):
                return [], False
            return orgs, answered
        except _PageLeft:
            raise
        except Exception as exc:
            self._raise_if_left()         # 同 _scan_org：先认「页面被带走」这一种
            # 一个板块打不开，不该连累另一个板块已经读到的岗（旧代码正是崩在这一步、把校招的岗全丢了）。
            # 记成「没答」：有岗就不算抓全，一个岗都没有就由 _harvest 报失败。
            self._note(f"{board}：列表页打开失败（{exc_brief(exc)}）")
            return [], False

    def _scan_org(self, page, recruit_type, org) -> Tuple[List[dict], bool]:
        """打开一个机构页并取回岗位卡的 state。返回 (岗位列表, 页面是否给出了确定答案)。"""
        org_id = _clean(org.get("orgId"))
        # 地址照站点自己的点击跳转来拼：热招事项卡的 onClick 是
        # `'/RecruitmentOrgDetails/' + batchCardInfo.recruitType + '/' + batchCardInfo.orgId`，
        # 用的是**卡片自带**的招聘类型，不是所在板块的编号（两者在专项板块里未必相同）。
        card_type = _clean(org.get("recruitType")) or recruit_type
        try:
            self._raise_if_left()
            page.goto(self.ORG_URL.format(recruit_type=card_type, org_id=org_id),
                      wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
            # 只改 hash 是同文档导航，上一家的卡片会留在 DOM 里 → 必须真的重载。
            page.reload(wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
            return self._collect(page, "posCardInfo", _ORG_EMPTY_MARKER)
        except _PageLeft:
            raise
        except Exception as exc:
            # 页面被对方带走时，Playwright 先抛出来的往往是别的错（导航被打断 / 执行上下文销毁 /
            # reload 报 net::ERR_EMPTY_RESPONSE）。先认这一种：它不是「这个机构抖了一下」，往后每个机构
            # 都只会再失败一次（2026-10-08 CI：37 个机构逐个「打开失败」，然后整轮崩掉）。
            self._raise_if_left()
            # ⚠️ 真的只是单个机构页抖一下，不该炸掉整轮 ——
            # 前面几十家已经抓到的岗会跟着一起丢，run.py 还会把整个源记成 failed。
            # 带上报错首行：只记类名时，10-08 那 37 行全是「Error」，看不出是导航被打断。
            self._note(f"机构 {org.get('orgName') or org_id}：打开失败（{exc_brief(exc)}）")
            return [], False

    def _detail_of(self, page, job_id: str, want_name: str) -> Optional[dict]:
        """打开逐岗详情页，把解密后的 posDetails 读回来；拿不到就返回 None（留薄卡，不编）。

        ⚠️ 归属校验：详情里的 posName 必须与列表卡一致才收。reload 已经换了文档、正常不会
        串味，但「宁可漏一条正文，也不能把 A 岗的正文挂到 B 岗上」——这是产品红线。
        """
        for attempt in (1, 2):
            try:
                self._raise_if_left()                     # 页面已被对方带走：不是这个岗的事，别再敲门
                page.goto(self.DETAIL_URL.format(job_publish_id=job_id),
                          wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                # 同 _scan_org：只改 hash 是同文档导航，上一个岗的正文会留在 DOM 里。
                page.reload(wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                detail = self._poll(page, lambda: page.evaluate(_DETAIL_JS), self.DETAIL_TIMEOUT_MS)
            except _PageLeft:
                raise
            except Exception as exc:                      # 单个岗的失败不该拖垮整源
                self._raise_if_left()                     # 同 _scan_org：先认「页面被带走」这一种
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
            try:
                detail = self._detail_of(page, _clean(row.get("jobPublishId")),
                                         _clean(row.get("posName")))
            except _PageLeft as left:
                # 每个岗都要重新加载一次文档，所以正文这一段最容易撞上对方的清空。撞上就停：
                # 列表和已经补好的正文都留着，剩下的岗等以后的轮次（起点按天轮转）。
                print(f"[abchina] 补正文时{self._left_reason(left.target)}；"
                      f"本轮补了 {filled}/{total} 个岗的正文，列表不受影响")
                break
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

    def _harvest(self, page) -> List[dict]:
        """在一个已打开的 page 上走完「列表 → 机构 → 重试轮 → 正文」，返回岗位行，并写好
        reported_total / fetch_complete。

        三种结局必须分清（见模块 docstring 最后两条）：
          · 读到了岗 → 返回；有页面没答 / 撞上限 / 半路被对方清空页面 → 不算抓全；
          · 一个岗都没读到，但每个板块都写着「暂无热招事项」→ 对方当期没在招，返回 []；
          · 一个岗都没读到，对方也没这么说 → 抛错。**绝不安静返回 0 岗。**
        """
        self.reported_total = None
        self.fetch_complete = False
        self._left_for = None
        self._notes = []
        cap = resolve_list_cap(self._MAX_JOBS)
        rows: List[dict] = []
        seen_jobs = set()
        truncated = False
        all_answered = True         # 问过的每个页面（板块列表、机构页）都给了确定答案
        empty_lists = 0             # 多少个板块是对方自己写着「暂无热招事项」
        org_total = 0
        missed_orgs: List[str] = []
        pending: List[tuple] = []   # 第一轮没给出答案的机构，留给下面的重试轮
        page.on("request", self._note_navigation)

        try:
            # 先过一遍首页（见模块 docstring「必须先加载一次首页」及其 2026-10-12 复核）。
            # 对方的清空发生在文档加载时，所以加载完立刻查一次。
            page.goto(_ENTRY, wait_until="networkidle", timeout=self.GOTO_TIMEOUT_MS)
            self._raise_if_left()

            for recruit_type, job_type in _RECRUIT_TYPES:
                orgs, list_answered = self._open_list(page, recruit_type)
                if not list_answered:
                    all_answered = False
                elif not orgs:
                    empty_lists += 1
                for org in orgs:
                    org_id = _clean(org.get("orgId"))
                    if not org_id:
                        continue
                    org_total += 1
                    positions, answered = self._scan_org(page, recruit_type, org)
                    if not answered:
                        # 这家没给出答案 —— 它有多少岗我们不知道，别当成 0，留给重试轮。
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
                positions, answered = self._scan_org(page, recruit_type, org)
                if not answered:
                    all_answered = False
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

            self._raise_if_left()   # 列表阶段的最后一道：过了这里才谈「抓全」和「对方没在招」
        except Exception as exc:
            # 含 _PageLeft。页面被带走时 Playwright 先抛的常是别的错（入口页的 goto 也会）：
            # 是这一种就按这一种算，报错才说得出真实原因；不是的话原样抛出去。
            if not self._left_for:
                raise
            if not isinstance(exc, _PageLeft):
                print(f"[abchina] 页面被带走的同时抛了：{exc_brief(exc)}")

        # 列表阶段的结论。正文阶段再被带走不改它 —— 那时列表已经读完了（_fill_bodies 自己处理）。
        left_for = self._left_for
        if left_for:
            # 一发现就停：不重新加载再碰运气，也不去动对方的检测脚本（见模块 docstring）。
            reason = self._left_reason(left_for)
            if not rows:
                raise RuntimeError(f"abchina: {reason}；本轮一个岗都没读到")
            all_answered = False
            print(f"[abchina] {reason}；本轮只读到 {len(rows)} 个岗，不算抓全")
        if not rows:
            if all_answered and empty_lists == len(_RECRUIT_TYPES):
                # 0 岗是对方的答案，不是没抓到：每个板块的列表都新鲜渲染出来、写着这句话，
                # 且同一页的机构清单里没有一个机构标着在招。
                print(f"[abchina] {len(_RECRUIT_TYPES)} 个板块都写着「{_LIST_EMPTY_MARKER}」："
                      "对方当期没有在招岗位")
                self.reported_total = 0
                self.fetch_complete = True
                return rows
            why = list(self._notes[:6])
            if len(self._notes) > 6:
                why.append(f"…共 {len(self._notes)} 条")
            if missed_orgs:
                why.append(f"{len(missed_orgs)} 个机构页重试后仍没给出答案（{'、'.join(missed_orgs[:5])}）")
            if not why:
                why.append(f"列出的 {org_total} 个机构都答了「没有在招岗位」，和热招事项卡对不上，更像是读法过期")
            raise RuntimeError("abchina: 没读到任何岗位，也不能确认对方当期没在招——" + "；".join(why))
        if missed_orgs:
            print(f"[abchina] {len(missed_orgs)} 个机构页没给出答案（本轮不算抓全）："
                  f"{'、'.join(missed_orgs[:8])}{' …' if len(missed_orgs) > 8 else ''}")

        # ── 逐岗正文 ──────────────────────────────────────────────────
        # 放在列表（含重试轮）之后：正文是「锦上添花」，绝不能因为它挤掉列表的完整性。
        # 快档 CRAWL_DETAIL_CAP=0 时这一步整段跳过；页面已经被带走时也不再开始。
        if not left_for:
            self._fill_bodies(page, rows, resolve_detail_cap(self._DETAIL_CAP))

        self.reported_total = len(rows)
        # 站点不自报总数（接口是密文），只能诚实记「看见的全部」。
        self.fetch_complete = (not truncated) and all_answered
        return rows

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        from .playwright_base import install_dialog_guard

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="zh-CN", viewport={"width": 1440, "height": 900},
                                    user_agent=_UA)
            # 站点 bundle 里有原生 alert（登录 / 手机号校验那几条路，浏览岗位走不到）。照项目的
            # Playwright 红线接管掉：没人接的 dialog 会被驱动自动 dismiss，撞上下一跳导航能拖死驱动进程。
            install_dialog_guard(page)
            try:
                rows = self._harvest(page)
            finally:
                browser.close()
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
