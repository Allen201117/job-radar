import unittest

import db


def _wt_url(i):
    # wt/hotjob 的长 query 串 jd_url（编码后约 1.7×）——固定 200 条/块时 .in_() URI 达 ~28KB → 网关 400。
    return ("https://cgn.hotjob.cn/wt/CGN/mobweb/position/detail"
            f"?brandCode=1&safe=Y&recruitType=2&postIdsAry={172000 + i}")


class JobsBatchSelectChunkTests(unittest.TestCase):
    def test_long_query_urls_split_under_uri_budget(self):
        urls = [_wt_url(i) for i in range(200)]
        chunks = list(db._chunk_by_uri_budget(urls))
        # 每块 URL 总长 ≤ 预算 → 编码后 URI 稳在网关上限内
        for ch in chunks:
            self.assertLessEqual(sum(len(u) for u in ch), db._SELECT_URI_BUDGET_CHARS)
        # 200 条长链必须切成多块（旧固定 200 是 1 块 → 28KB URI → 400）
        self.assertGreater(len(chunks), 1)
        # 不丢、不乱序、不重复
        self.assertEqual([u for ch in chunks for u in ch], urls)

    def test_short_urls_pack_into_few_chunks(self):
        urls = [f"https://x.io/j/{i}" for i in range(200)]
        chunks = list(db._chunk_by_uri_budget(urls))
        # 短链远低于预算 → 受条数上限约束、不被过度切分（不增往返）
        self.assertLessEqual(len(chunks), 2)
        self.assertEqual([u for ch in chunks for u in ch], urls)

    def test_single_oversized_url_is_its_own_chunk(self):
        big = "https://x.io/" + "a" * (db._SELECT_URI_BUDGET_CHARS + 100)
        self.assertEqual(list(db._chunk_by_uri_budget([big])), [[big]])

    def test_empty_input_yields_no_chunks(self):
        self.assertEqual(list(db._chunk_by_uri_budget([])), [])


if __name__ == "__main__":
    unittest.main()
