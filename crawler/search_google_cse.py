"""Google Programmable Search（Custom Search JSON API）provider 解析：
GET https://www.googleapis.com/customsearch/v1。

为何加它（2026-09-18）：找入口这一步的搜索额度是**全局共享**的（见 CLAUDE.md「搜索额度是
全局共享的」），缺口漏斗与 T3 洞察、校招时间线链抢同一个池子。Google CSE 免费 100 次/天、
**不绑卡**，是目前所有已接源里每日额度最大的一个。

💰 **日顶 500 靠的是试用赠金，不是免费额度**：免费档只有 100 次/天，超出部分按
Google Cloud 项目里的 ¥47,813 试用赠金抵扣，而**赠金 2026-12-18 到期**。
到期后要把 `GOOGLE_CSE_DAILY_CAP` 降回 90（= 免费档 100 留 10% 余量），
否则超出的部分会开始真扣钱。

🚩 **它不是全网搜索**：创始人这台 Programmable Search 引擎开不了「整个网络」，只收录了
招聘平台域名（zhiye.com / hotjob.cn / wintalent.cn / app.mokahr.com / jobs.feishu.cn /
iguopin.com / workday.com / myworkdayjobs.com）。两个直接后果：
  · 查询词**不要**再拼 `site:` 限定 —— 引擎侧已经限定死了，再拼只会把结果打空；
    「<公司名> 校园招聘」「<公司名> 招聘」这种裸查询就够，结果天然全是 ATS 入口，
    可以直接喂 platform_fingerprint。
  · 它对「找入口」以外的用途（T3 职业洞察那种要搜新闻/社区的）**恒返 0 条**，
    而 SearchRouter 是「打一次就记一次额度」—— 放进通用池会变成每天白烧 T3 的额度、
    还把 T3 的召回打薄。所以它标了 `general = False`：只有找入口的链（entry_finder）
    显式取用它，通用 router.search() 跳过它。这是与「排在 tavily 之前」那条指令的
    **唯一偏离**，偏离的是「通用池里排第一」，在找入口这条链上它确实排第一。

两个 env 都要配：`GOOGLE_CSE_API_KEY`（凭据）+ `GOOGLE_CSE_CX`（搜索引擎 ID）。
⚠️ 只配 key 不配 cx 会 400，因此 is_configured 必须两个都看 —— HttpSearchProvider 只认一个
key_env，故这里用子类覆盖 is_configured，而不是假装只要 key 就能用（那会每次都白打一发）。

⚠️ 是 **GET + 查询串**，不是 POST + JSON：build_request 的第三项在 method="GET" 时被
HttpSearchProvider 当 params 用。响应形状 `{"items": [{"title","link","snippet"}]}`。
"""
import os

import search_base
from search_provider_http import HttpSearchProvider


CX_ENV = "GOOGLE_CSE_CX"


def parse_response(data):
    """Google CSE JSON → [{title,url,snippet,text,publisher}]。纯函数，无网络。"""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return []
    out = []
    for row in data["items"]:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        url = row.get("link")
        if not (str(title or "").strip() and str(url or "").strip()):
            continue
        snippet = row.get("snippet") or ""
        out.append(search_base.make_result(title, url, snippet, snippet))
    return out


def build_request(key, query, top_k):
    """(url, headers, query_params)。num 上限 10（传更大 Google 直接 400）；
    lr/gl 收中文区；dateRestrict 限近 RECENCY_YEARS 年保即时性。"""
    return (
        "https://www.googleapis.com/customsearch/v1",
        {"Accept": "application/json"},
        {"key": key, "cx": os.environ.get(CX_ENV, ""),
         "q": str(query or "").strip()[:400],
         "num": max(1, min(10, int(top_k or 8))),
         "lr": "lang_zh-CN", "gl": "cn",
         "dateRestrict": "y%d" % search_base.RECENCY_YEARS},
    )


class GoogleCseProvider(HttpSearchProvider):
    """只比通用 HTTP provider 多一件事：cx 没配就当作没配置（见模块 docstring）。"""

    def __init__(self):
        super().__init__(
            "google_cse", "GOOGLE_CSE_API_KEY", parse_response, build_request,
            "GOOGLE_CSE_DAILY_CAP", 500, method="GET",
        )

    # 只收录 ATS 域名 → 不进通用搜索池（理由见模块 docstring 的第二条后果）。
    general = False

    def is_configured(self):
        return bool(os.environ.get(CX_ENV)) and super().is_configured()
