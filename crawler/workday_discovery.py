"""Workday 租户/站点发现器：把公司名 → 可用的 Workday CXS jobs 端点。

为什么需要它（而不是像 greenhouse/lever 那样拼模板）：
  greenhouse/lever/ashby 的 URL = 一个 slug 就能拼出来（见 probe._ATS_URL）。
  但 Workday 的端点是三段自定义：https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  —— wd 编号（wd1/wd3/wd5/wd12…）和 site 名都由各公司自选，且 site 名毫无规律
  （库里已有的就有 LLY / External / MarvellCareers / kenvue / Careers / Diageo_Careers）。
  拼不出来 → 海外必投里的 workday 系大厂（Salesforce/Pfizer/Visa/Cisco…）此前一个都探不到。

发现信号（2026-07-14 live 校准，用「确定不存在的租户」反向验过，别凭直觉改）：
  · 422  = **租户不存在**（不存在的 tenant/wd 一律 422；曾误以为 422=租户存在，方向正好反）
  · 404  = **租户存在，只是 site 名猜错了** → 这才是「继续枚举 site」的信号
  · 200 + total>0 = 命中
  · 请求体必须带 appliedFacets（漏了会被部分租户 422 拒，与「租户不存在」混淆）

命中率（live 实测 15 家 workday 系大厂）：5/15。探不到的自动丢弃、零污染——这正是精度红线允许
「猜」的前提：猜错的进不了库。
"""
import time

import httpx

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
# appliedFacets 必填：漏了会被部分租户 422 拒（与「租户不存在」的 422 撞信号）。
_BODY = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}

WD_NUMBERS = ("wd1", "wd3", "wd5", "wd12", "wd2", "wd10")
_DUMMY_SITE = "ZzNoSuchSite"   # 探租户存在性用：404=租户在 / 422=租户不在


def cxs_url(tenant: str, wd: str, site: str) -> str:
    return f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"


def site_candidates(tenant: str, display: str):
    """site 名候选：从库里已有 workday 源归纳的命名模式（External / Careers / {Co}Careers /
    {Co}_Careers / {tenant} …）。命不中就算了——探不到不入库，成本只有几个 httpx 请求。"""
    cap = "".join(ch for ch in (display or "") if ch.isalnum())
    out = ["External", "Careers", "External_Career_Site", f"{cap}Careers", f"{cap}_Careers",
           tenant, cap, "ExternalCareers", "External_Careers", f"{cap}_External",
           "Global", "careers", f"{cap}Jobs"]
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _probe(url: str, timeout: int):
    """→ (status, total)。网络异常重试一次再按「租户不存在」处理（ERR）。
    ⚠️ 2026-07-16 live 踩坑：并发探活时瞬时限流/连接被重置 → ERR 被当成 422 同义（租户不存在）
    静默跳过 → Salesforce(wd12,1446 岗)/Target(wd5,2000 岗)/Snap 这类真租户整批漏掉；
    单发重试即可命中。方向敏感（ERR≠不存在），故本体重试而不是交给调用方。"""
    for attempt in (0, 1):
        try:
            r = httpx.post(url, headers=_HEADERS, json=_BODY, timeout=timeout)
            break
        except Exception:
            if attempt == 1:
                return "ERR", 0
            time.sleep(1.0)
    if r.status_code == 200:
        try:
            return 200, int((r.json() or {}).get("total") or 0)
        except Exception:
            return 200, 0
    return r.status_code, 0


def discover(display: str, slugs, timeout: int = 8, probe_fn=None):
    """在 slugs × WD_NUMBERS × site 候选里找一个真返回岗位的 CXS 端点；找不到返回 None。
    先用 dummy site 探租户（404 才继续枚举 site），避免对不存在的租户白跑十几个 site。"""
    probe = probe_fn or _probe
    for tenant in (slugs or []):
        tenant = str(tenant or "").strip().lower()
        if not tenant:
            continue
        for wd in WD_NUMBERS:
            status, _ = probe(cxs_url(tenant, wd, _DUMMY_SITE), timeout)
            if status != 404:      # 422/ERR = 租户不存在；200 = 撞上真 site（极小概率）也不当命中
                continue
            for site in site_candidates(tenant, display):
                status, total = probe(cxs_url(tenant, wd, site), timeout)
                if status == 200 and total > 0:
                    return {"tenant": tenant, "wd": wd, "site": site, "total": total,
                            "url": cxs_url(tenant, wd, site)}
    return None
