"""兴业银行招聘门户（job.cib.com.cn/portal）适配器（Playwright，调用页面自己的请求函数）。

⚠️ 为什么不用 httpx：门户建在兴业银行的 JUP 前端框架上，**每个请求都要带现场签算的两个头**，
裸请求一律 500（2026-09-23 live）：
  · X-VALID-TOKEN      = SM3-HMAC(按键排序后的请求体, signKey)
  · X-AntiReplay-Token = SM4(访问令牌 | 时间戳尾数+6位随机数 | 时间戳, sm4Key)
  两把会话密钥来自页面启动时的握手：POST /api/authPrehandler 发 SM2 公钥 + salt，
  POST /api/cfn/sysToken 用随机串换回 SM4 加密的 tokenKey / signKey。

🔎 性质判定（2026-09-23 读前端源码逐段核过，证据见 docs/crawler-adapter-notes.md「兴业银行」）：
  这是框架自带的**请求完整性签名 + 防重放**，算法公开在前端代码里（国密 SM2/SM3/SM4），输入只有
  请求体、时间戳、随机数和服务端下发的会话密钥——**没有滑块、没有设备指纹、没有行为校验**；图形验证码
  只出现在登录框（手机号 / 邮箱登录），浏览岗位列表用不到；错误码 915021「needRecheck」是银行系统的
  「复核」（操作需另一人审批），不是人机校验。所以按「前端公开算法算出来的普通接口参数」处理。
  不在 Python 里复刻国密算法（要引新的加密依赖）：打开门户后**直接调用页面自己的 jup__ajax**，
  签名由页面自己的代码完成——与农业银行（abchina，读页面内存里的明文）同一路数。

列表接口 recruitpositionportalPage 一次可取 200 条，行内自带职责 + 任职要求全文，不需要逐岗补正文；
社招 SR / 校招 CR / 实习 TR 混在同一个列表里（total 覆盖三类）。
逐岗详情 `…/portal/recruit/814456617331937281?recruitType={类型}#/positionDetails/{positionId}`：
真 id 渲染出岗位（匿名可看），假 id 只剩页头页脚空壳（真假 id 对拍过）。
⚠️ 详情是 hash 路由：若日后接浏览器巡检，同文档导航会留着上一个岗（CLAUDE.md 立碑），必须 reload。
"""
import json
import logging
import re
from typing import Callable, List, Optional

from .base import BaseAdapter, RawJob

logger = logging.getLogger(__name__)

_ENTRY = "https://job.cib.com.cn/portal/recruit/814456617331937281?recruitType=SR"
_DETAIL = "https://job.cib.com.cn/portal/recruit/814456617331937281?recruitType={rt}#/positionDetails/{pid}"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_JOB_TYPES = {"SR": "社招", "CR": "校招", "TR": "实习"}

_READY_JS = """() => { const el = document.querySelector('#app');
  return !!(el && el.__vue__ && typeof el.__vue__.jup__ajax === 'function'); }"""
# 页面自己的请求函数：签名 / 防重放头都由它加。返回 {code, message, total, list}。
_PAGE_JS = """async ({pageIndex, pageSize}) => {
  const vm = document.querySelector('#app').__vue__;
  const r = await vm.jup__ajax('recruitpositionportalPage',
    {visibilityFlag: 'Y', positionStatus: 'P', pagination: {pageIndex, pageSize}}, null, null, {});
  const d = (r && r.data) || r || {};
  const body = d.data || {};
  return {code: d.code, message: d.message, total: body.total, list: body.list || []};
}"""


def _clean(value) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", str(value or "")).strip()


def collect_pages(call: Callable[[int], dict], page_size: int, max_pages: int = 50):
    """翻到底：返回 (rows, reported_total, complete)。只在「按 positionId 去重后收满站点自报总数」时 complete。

    抽成纯函数是为了能不开浏览器单测翻页与抓全判定（BeisenAdapter 那块碑：抓漏 + 自称抓全 = 误杀在招岗）。
    """
    rows, seen, total = [], set(), None
    for page_index in range(1, max_pages + 1):
        res = call(page_index) or {}
        if res.get("code") not in (None, "0000"):
            raise RuntimeError("cib: portalPage code=%s message=%s" % (res.get("code"), res.get("message")))
        if total is None and isinstance(res.get("total"), int):
            total = res["total"]
        batch = [r for r in (res.get("list") or []) if isinstance(r, dict) and r.get("positionId")]
        fresh = [r for r in batch if str(r["positionId"]) not in seen]
        if not fresh:
            break
        for r in fresh:
            seen.add(str(r["positionId"]))
        rows.extend(fresh)
        if total is not None and len(rows) >= total:
            break
        if len(batch) < page_size:
            break
    complete = total is not None and len(rows) >= total
    return rows, total, complete


class CibAdapter(BaseAdapter):
    name = "cib"
    PAGE_SIZE = 200
    GOTO_TIMEOUT_MS = 45000
    READY_TIMEOUT_MS = 30000

    def should_skip(self, source_url: str) -> Optional[str]:
        return None  # SPA 入口，HEAD 预检没有意义（同 abchina）

    def fetch(self, source_url: str) -> str:
        from playwright.sync_api import sync_playwright

        self.reported_total = None
        self.fetch_complete = False
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=_UA)

                def _dismiss(dialog):   # CI 上没人点弹窗，不接管会让驱动卡死（CLAUDE.md 立碑）
                    try:
                        dialog.dismiss()
                    except Exception:
                        pass
                page.on("dialog", _dismiss)
                # 不等 networkidle：页面有常驻请求，CI 上会一直等不到（moka 那块碑）。等到页面自己的请求函数就绪即可。
                page.goto(_ENTRY, wait_until="domcontentloaded", timeout=self.GOTO_TIMEOUT_MS)
                page.wait_for_function(_READY_JS, timeout=self.READY_TIMEOUT_MS)
                rows, total, complete = collect_pages(
                    lambda i: page.evaluate(_PAGE_JS, {"pageIndex": i, "pageSize": self.PAGE_SIZE}),
                    page_size=self.PAGE_SIZE,
                )
            finally:
                browser.close()
        if not rows and total != 0:
            raise RuntimeError("cib: portalPage returned no jobs")
        self.reported_total = total
        self.fetch_complete = complete
        return json.dumps({"jobs": rows}, ensure_ascii=False)

    @staticmethod
    def _summary_of(row: dict) -> Optional[str]:
        parts = []
        duty, req = _clean(row.get("jobDuty")), _clean(row.get("positionRequirment"))
        if duty:
            parts.append("【岗位职责】\n" + duty)
        if req:
            parts.append("【任职要求】\n" + req)
        return "\n".join(parts) or None

    def parse(self, payload: str) -> List[RawJob]:
        try:
            rows = (json.loads(payload) or {}).get("jobs") or []
        except (json.JSONDecodeError, TypeError):
            return []
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = str(row.get("positionId") or "").strip()
            name = re.sub(r"\s+", " ", str(row.get("positionName") or "")).strip()
            if not (pid and name):
                continue
            rt = str(row.get("recruitType") or "SR").strip().upper()
            org = re.sub(r"\s+", " ", str(row.get("businessUnitDesc") or row.get("departmentDesc") or "")).strip()
            # 几十个分行都叫「运营支持类」「对公客户经理」，机构名进标题才分得开（同 citicbank）。
            title = "%s（%s）" % (name, org) if org and org not in name else name
            jd_url = _DETAIL.format(rt=rt, pid=pid)
            expiry = str(row.get("expiryDate") or "")[:10]
            jobs.append(RawJob(
                company="", title=title,
                location=re.sub(r"\s+", "", str(row.get("positionAddr") or ""))[:200] or None,
                job_type=_JOB_TYPES.get(rt, "社招"),
                summary=self._summary_of(row),
                jd_url=jd_url, apply_url=jd_url,
                posted_at=str(row.get("publishTime") or "")[:10] or None,
                # 「长期」岗站点写 3000-01-01 这种哨兵值，当成「无截止」不往下游传（同 spdb 的 2100）。
                deadline=None if (not expiry or expiry.startswith(("3000", "2999", "2100"))) else expiry,
            ))
        return jobs
