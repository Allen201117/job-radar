"""多源搜索路由器：按配置取已启用 provider，逐个在各自每日预算内检索，并取去重，单源报错兜底跳过。

设计：替换 insight_backlog 里对单一 qianfan 的直连——输出形状不变（{title,url,snippet,text,publisher}），
下游 insight_engine.run_pipeline 零改动。多源并取天然喂饱「≥2 不同 publisher」共识门。

provider 协议（见 search_provider_http.SearchProvider / search_qianfan.QianfanProvider）：
  name / is_configured() / remaining(sb) -> int / search(query, top_k, client) -> list / consume(sb, n)
"""
import os


class SearchAccountError(Exception):
    """搜索 provider 的鉴权/欠费类错误；重试同一账户没有意义。"""


_ACCOUNT_ERROR_KEYWORDS = ("payment", "balance", "quota", "suspended", "欠费", "余额", "额度")
_BLACKLISTED_PROVIDERS = set()


def is_search_account_error(status_code, message=""):
    if status_code in (401, 402):
        return True
    text = str(message or "").casefold()
    return any(keyword in text for keyword in _ACCOUNT_ERROR_KEYWORDS)


def provider_blacklisted(provider):
    return getattr(provider, "name", "") in _BLACKLISTED_PROVIDERS


def blacklist_provider(provider, error):
    name = getattr(provider, "name", "?")
    _BLACKLISTED_PROVIDERS.add(name)
    print(f"⚠️ [search-account-error] provider={name}: {str(error)[:120]}")


def campus_reserve() -> int:
    """给校招时间线链预留的每日搜索次数（env SEARCH_RESERVE_CAMPUS，默认 25）。

    设 0 = 不预留（回到「T3 吃光、校招饿死」的旧行为）。非法值回默认。
    """
    raw = os.environ.get("SEARCH_RESERVE_CAMPUS")
    if raw not in (None, ""):
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return 25


def search_fanout_min_results() -> int:
    """首源已够用时停止扇出（env SEARCH_FANOUT_MIN_RESULTS，默认 5）。"""
    raw = os.environ.get("SEARCH_FANOUT_MIN_RESULTS")
    if raw not in (None, ""):
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 5


class SearchRouter:
    def __init__(self, providers):
        self.providers = list(providers or [])

    def _active(self):
        return [
            p for p in self.providers
            if p.is_configured() and not provider_blacklisted(p)
        ]

    def is_configured(self):
        """任一 provider 配置了 key 即可用。"""
        return bool(self._active())

    def remaining(self, sb):
        """已配置 provider 当日剩余额度之和（drain 用它判断是否还能跑）。"""
        return sum(p.remaining(sb) for p in self._active())

    def remaining_above_reserve(self, sb):
        """扣掉「给校招链预留的那一份」之后，**贪心消费方**还能用多少。

        为何要有它：搜索额度是全局共享的，而 T3 洞察 drain 会一路吃到 0
        （`cap = remaining`，队列多长就吃多久）。校招时间线链 cron 排在 T3 之后 45 分钟，
        于是**每天开跑时 remaining 恒为 0、第一家就 break** ——
        2026-08-21~27 连续 7 天 ops_runs 记录 `companies_processed: 0`，
        却因为不抛异常一直报 success（绿灯 ≠ 有产出，CLAUDE.md 体检方法论立过碑）。
        这不是逻辑 bug 是**资源饿死**：靠调 cron 先后只会把饿死的换成另一条。

        口径：**只有 T3 这类贪心方调它**；校招链继续调 `remaining()` 用满预留额度。
        预留量走 env `SEARCH_RESERVE_CAMPUS`（默认 25，够校招链一轮 8 家）。
        """
        return max(0, self.remaining(sb) - campus_reserve())

    def search(self, sb, query, top_k=8, client=None):
        """各已配置且有额度的 provider 依次检索，够用即停 → 按 url 并取去重（保留先出现者）。
        单源报错/无结果不影响其它源；返回统一形状列表。"""
        out, seen = [], set()
        minimum = search_fanout_min_results()
        for p in self._active():
            try:
                if p.remaining(sb) <= 0:
                    continue
                results = p.search(query, top_k, client) or []
                p.consume(sb, 1)  # 实际发起一次检索 → 记一次额度（无论结果多少）
            except SearchAccountError as e:
                blacklist_provider(p, e)
                continue
            except Exception as e:
                print(f"  [search-router] {getattr(p, 'name', '?')} 兜底跳过: "
                      f"{type(e).__name__}: {str(e)[:120]}")
                continue
            new = 0
            for r in results:
                url = (r or {}).get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append(r)
                new += 1
            print(f"  [search] {p.name}: 返回 {len(results)} 条 / 去重后新增 {new} 条")
            if len(out) >= minimum:
                break
        return out


def default_router():
    """按环境变量装配默认多源路由器（顺序=额度可持续性优先，见下方注释）。
    未配 key 的源 router 自会跳过 → 「先用各家免费额度验证灵活性」即配哪个用哪个。
    每源日顶默认值仅为安全上限，正式放量由 *_DAILY_CAP env 按月度预算调。"""
    import search_bocha
    import search_qianfan
    import search_serper
    import search_tavily
    from search_provider_http import HttpSearchProvider

    # ⚠️ 顺序 = **额度可持续性优先**（2026-09-04 改，原来是「中文深度优先」）。
    # search() 是「按本列表顺序逐个试、够 5 条就停」，所以排在前面的先被消耗。
    # 原顺序 博查 → Tavily → Serper → 千帆 把**一次性额度的 Serper 排在每天回血的千帆前面**，
    # 正好是反的：台账实测 2026-06-20 起 68 天里 Serper 已用掉 1,299 / 2,500（52%），
    # 按每月 ~570 次的速度约两个月见底，而千帆每天 50 次免费额度天天没用完。
    # 现顺序按「回血周期」排：每月回血 → 每天回血 → 一次性 → 付费。
    #   1. tavily  每月 1,000 免费（月初重置），日顶 32 ≈ 960/月，留 4% 余量
    #   2. 千帆    每天 50 免费（次日重置），走自身 QIANFAN_DAILY_CAP=40
    #   3. serper  **2,500 一次性总额，用完就没了** → 日顶砍到 10，当最后手段
    #   4. bocha   **付费**（不是免费额度）→ 放最后，避免有人配了 key 就默认先花钱
    # 想临时调回来不必改代码：repo Variables 的 *_DAILY_CAP 可覆盖任一日顶。
    return SearchRouter([
        HttpSearchProvider("tavily", "TAVILY_API_KEY", search_tavily.parse_response,
                           search_tavily.build_request, "TAVILY_DAILY_CAP", 32),
        search_qianfan.QianfanProvider(),
        HttpSearchProvider("serper", "SERPER_API_KEY", search_serper.parse_response,
                           search_serper.build_request, "SERPER_DAILY_CAP", 10),
        HttpSearchProvider("bocha", "BOCHA_API_KEY", search_bocha.parse_response,
                           search_bocha.build_request, "BOCHA_DAILY_CAP", 50),
    ])


# ── 一次性额度的耗尽预警 ────────────────────────────────────────────────
# Serper 的免费额度是 **2,500 次一次性总额**（不是按月重置），用完就静默没了 ——
# 表现会是「T3 突然不产出」，又是一次「绿灯零产出」。这里靠自家台账算累计用量预警，
# 不需要各家的余额 API（那些 key 只在 CI，本地拿不到）。
LIFETIME_QUOTA = {"serper": 2500}
LIFETIME_WARN_RATIO = 0.8


def lifetime_used(sb, provider: str) -> int:
    """某个源自台账建立以来的累计消耗次数。读不到就返回 0（预警不该拖垮主任务）。"""
    try:
        import db
        rows = db.fetch_all_rows(
            lambda: sb.table("search_usage").select("used").eq("provider", provider),
            order_key="day",
        )
        return sum(int(r.get("used") or 0) for r in rows)
    except Exception:
        return 0


def lifetime_warnings(sb) -> list:
    """返回 [(provider, 已用, 总额)]，仅列出已越过 80% 的一次性额度源。"""
    out = []
    for provider, quota in LIFETIME_QUOTA.items():
        used = lifetime_used(sb, provider)
        if used >= quota * LIFETIME_WARN_RATIO:
            out.append((provider, used, quota))
    return out
