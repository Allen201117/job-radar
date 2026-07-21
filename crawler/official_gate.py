"""校招往年时间线 B2 —— 官方源门（宁缺不编的机器落地，纯函数，不打网络）。

选项 A（创始人 2026-07-21 拍板）：往年时间线走机器自动发布、无人工，但**只 auto-verify
「公司官方招聘域名 grounding + 判官判 entailment」的**；够不着官方证据的一律停 draft、不展示。
draft 行受 RLS 读策略保护（只读 verified 且未过期），用户看不到。
"""
from urllib.parse import urlsplit

# 共享 ATS / 第三方聚合 host：这些 host 上的页面不能代表「某一家公司的官方招聘域名」
# （app.mokahr.com 上挂着成千上万家，命中 host 会张冠李戴）→ 不进官方 allowlist。
# ⚠️ 只放「共享基建」host——在该 host 上无法识别是哪一家公司。绝不放公司自有域名
# （如 talent.baidu.com / careers.tencent.com 是该公司官方招聘域名，必须放行）：
#  - 共享 ATS 平台（成千上万家共用一个 host）
#  - 第三方招聘平台 / 社区 / 内容平台（公司在上面发帖不等于官方招聘页）
_SHARED_ATS_HOSTS = {
    "mokahr.com", "app.mokahr.com",
    "feishu.cn", "jobs.feishu.cn",
    "zhiye.com", "italent.cn",
    "hotjob.cn", "wecruit.hotjob.cn",
    "dayeetech.com", "eteams.cn",
    # 第三方招聘平台 / 聚合 / 社区 / 内容平台（绝不当官方）
    "yingjiesheng.com", "nowcoder.com", "maimai.cn", "zhihu.com",
    "weixin.qq.com", "mp.weixin.qq.com",
    "zhipin.com", "liepin.com", "lagou.com", "51job.com", "zhaopin.com",
}


def _host(url):
    return (urlsplit(url or "").netloc or "").lower().strip().strip(".")


def _registrable(host):
    """粗取可注册域名（末两段）；仅用于共享 ATS denylist 命中判断。"""
    h = (host or "").lower().strip().strip(".")
    if h.startswith("www."):
        h = h[4:]
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def official_hosts_from_sources(source_urls):
    """从公司 sources.source_url 提取「该公司自有」官方招聘 host 集合。
    排除共享 ATS / 第三方 host（它们代表不了这一家的官方域名）。返回 set。"""
    hosts = set()
    for u in source_urls or []:
        h = _host(u)
        if not h:
            continue
        if h in _SHARED_ATS_HOSTS or _registrable(h) in _SHARED_ATS_HOSTS:
            continue
        hosts.add(h)
    return hosts


def is_official_grounding(url, official_hosts):
    """grounding 源是否落在该公司官方招聘域名上（含子域双向匹配）。"""
    h = _host(url)
    if not h or not official_hosts:
        return False
    for oh in official_hosts:
        if not oh:
            continue
        if h == oh or h.endswith("." + oh) or oh.endswith("." + h):
            return True
    return False


# 判官置信度门（对齐 insight_engine.JUDGE_CONFIDENCE_MIN）
_ENTAIL_CONF_MIN = 0.6


def decide_cycle_status(judge_verdict, judge_confidence, has_official_grounding):
    """返回 (verify_status, source_kind, confidence)。
    官方门（选项 A）：
      - 官方域名 grounding + 判官 entailment(≥0.6) → ('verified','official_notice','high')（自动发布）
      - 判官 entailment 但非官方源 → ('draft','public_aggregate','medium')（停草稿、不展示）
      - 判官不支持（neutral/contradiction）→ ('draft','llm_draft','low')
    """
    try:
        conf = float(judge_confidence)
    except (TypeError, ValueError):
        conf = 0.0
    entail = judge_verdict == "entailment" and conf >= _ENTAIL_CONF_MIN
    if entail and has_official_grounding:
        return ("verified", "official_notice", "high")
    if entail:
        return ("draft", "public_aggregate", "medium")
    return ("draft", "llm_draft", "low")
