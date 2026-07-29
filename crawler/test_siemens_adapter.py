import json
import re
import unittest

from adapters.siemens import SiemensAdapter

_CARD = """
<article class="article article--result">
  <h3 class="article__header__text__title">
    <a class="link" href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/{jid}">
      {title}
    </a>
  </h3>
  <span class="list-item-location">
    <span class="list-item-jobCity">{city}</span>,
    <span class="list-item-jobCountry">{country}</span>
  </span>
  <span class="list-item-family">Engineering</span>
</article>
"""


def _page(cards, shown=6, total="999+"):
    body = "".join(cards)
    return f"<div>1 - {shown} of {total} results</div>{body}"


class SiemensAdapterTests(unittest.TestCase):
    def test_parses_search_result_articles_with_detail_links(self):
        """卡片字段抽取契约（地区门是另一层，见 SiemensRegionScopeTest）。"""
        html = _CARD.format(jid=505503, title="Fire Test and Approval Engineer",
                            city="Prague", country="Czech Republic")

        jobs = SiemensAdapter()._parse_cards(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Fire Test and Approval Engineer")
        self.assertEqual(jobs[0].location, "Prague, Czech Republic")
        self.assertEqual(jobs[0].job_type, "Engineering")
        self.assertEqual(
            jobs[0].jd_url,
            "https://jobs.siemens.com/en_US/externaljobs/JobDetail/505503",
        )


class SiemensPaginationTest(unittest.TestCase):
    """回归守卫：Siemens 必须按 offset 翻到底，不能只拿搜索页首屏。

    2026-07-28 实测：旧实现只 GET 一次 SearchJobs → 恒定 6 条，而站点自报 "999+ results"
    （offset=2000 仍有货，3000 才空）。库里 481 个 active 里的老岗 509645/510192 **仍在招**
    （详情页 200、JD 完整），只是永远挤不进那 6 条 → 永不刷新，3 天刷新率仅 7%。
    页长是服务端锁死的 6（recordsPerPage/limit/pageSize/rpp/perPage 全试过，改不动）。
    """

    def _fake_client(self, total_by_term):
        calls = []

        class FakeResp:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        class FakeClient:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return False

            def get(self_inner, url):
                calls.append(url)
                term = re.search(r"search=([^&]*)", url)
                term = term.group(1) if term else ""
                offset = int(re.search(r"offset=(\d+)", url).group(1))
                total = total_by_term.get(term, 0)
                cards = [
                    _CARD.format(jid=1000 + i, title=f"Engineer {i}",
                                 city="Shanghai", country="China")
                    for i in range(offset, min(offset + 6, total))
                ]
                return FakeResp(_page(cards, total=str(total)))

        return FakeClient, calls

    def test_walks_every_offset_page(self):
        FakeClient, calls = self._fake_client({"China": 20})
        adapter = SiemensAdapter()
        adapter.regions = ["CN"]
        import adapters.siemens as mod
        orig, mod.httpx.Client = mod.httpx.Client, lambda *a, **k: FakeClient()
        try:
            jobs = adapter.parse(adapter.fetch(SiemensAdapter.SEARCH_URL))
        finally:
            mod.httpx.Client = orig

        self.assertEqual(len(jobs), 20, "20 个岗必须全抓到，不能停在首屏 6 条")
        offsets = sorted(int(re.search(r"offset=(\d+)", u).group(1)) for u in calls)
        self.assertEqual(offsets[:4], [0, 6, 12, 18], f"没按 6 逐页递进: {offsets}")

    def test_dedupes_across_pages_and_terms(self):
        FakeClient, _ = self._fake_client({"China": 8, "Hong Kong": 8})
        adapter = SiemensAdapter()
        adapter.regions = ["CN", "HK"]   # 两个关键词会捞回同一批 id
        import adapters.siemens as mod
        orig, mod.httpx.Client = mod.httpx.Client, lambda *a, **k: FakeClient()
        try:
            jobs = adapter.parse(adapter.fetch(SiemensAdapter.SEARCH_URL))
        finally:
            mod.httpx.Client = orig

        self.assertEqual(len(jobs), len({j.jd_url for j in jobs}), "跨关键词没按 jd_url 去重")
        self.assertEqual(len(jobs), 8)


class SiemensRegionScopeTest(unittest.TestCase):
    """回归守卫：regions=['CN'] 的源不许被全球岗灌满。

    站内 search 是全文匹配（正文提到 "China" 的德国岗也会命中），必须再过一道地点门。
    2026-07-28 实测：库里 484 个 Siemens active 岗有 426 个地点没解析出国家、默认落进
    domestic —— 丹麦/印度/危地马拉岗混在国内看板里。
    """

    def _parse_pages(self, adapter, cards):
        return adapter.parse(json.dumps({"_pages": [_page(cards)]}))

    def test_keeps_china_drops_foreign(self):
        adapter = SiemensAdapter()
        adapter.regions = ["CN"]
        cards = [
            _CARD.format(jid=1, title="Sales CN", city="Shanghai", country="China"),
            _CARD.format(jid=2, title="Sales DK", city="Ballerup", country="Denmark"),
            _CARD.format(jid=3, title="Sales IN", city="Bangalore", country="India"),
        ]
        jobs = self._parse_pages(adapter, cards)
        self.assertEqual([j.title for j in jobs], ["Sales CN"])

    def test_taiwan_never_enters_a_cn_source(self):
        """台湾按项目口径不抓。'Taiwan, Province of China' 含 china 字样，曾被判成 CN 放行。"""
        adapter = SiemensAdapter()
        adapter.regions = ["CN"]
        cards = [
            _CARD.format(jid=1, title="Shanghai role", city="Shanghai", country="China"),
            _CARD.format(jid=2, title="Taipei role", city="Taipei",
                         country="Taiwan, Province of China"),
        ]
        jobs = self._parse_pages(adapter, cards)
        self.assertEqual([j.title for j in jobs], ["Shanghai role"])


if __name__ == "__main__":
    unittest.main()
