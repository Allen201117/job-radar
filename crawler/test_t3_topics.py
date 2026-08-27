"""T3 多维查询包主题清单单测（纯函数，不打网络 / 不碰 DB / 不调 LLM）。

主题数直接等比放大 LLM 账单（每主题 ≈ 1 writer + ~2.7 judge），所以这里把「默认 3 个」
和「env 能一键调回来」钉死：改主题必须改 env，不该再改代码。
"""
import unittest

import insight_backlog as B


class T3TopicResolutionTest(unittest.TestCase):
    def test_catalog_keeps_all_five_topics_for_rollback(self):
        """砍掉的两个主题留在目录里（只是不默认跑）→ 一个 env 就能恢复五主题。"""
        self.assertEqual(
            set(B.T3_TOPIC_CATALOG),
            {"加班文化", "实习体验", "年终奖", "晋升发展", "面试难度"},
        )

    def test_default_pack_is_three_topics(self):
        pack = B.resolve_query_pack(None)
        self.assertEqual([p["topic"] for p in pack], ["年终奖", "加班文化", "晋升发展"])

    def test_default_topics_cover_three_distinct_dimensions(self):
        """保留的 3 个各占一个「没有免费供给层」的维度：comp / culture / path，不许重复占坑。"""
        dims = [p["dimension"] for p in B.resolve_query_pack(None)]
        self.assertEqual(sorted(dims), ["compensation_intensity", "culture", "path"])
        self.assertEqual(len(set(dims)), 3)

    def test_env_can_restore_five_topics_in_given_order(self):
        pack = B.resolve_query_pack("年终奖,加班文化,晋升发展,实习体验,面试难度")
        self.assertEqual(
            [p["topic"] for p in pack],
            ["年终奖", "加班文化", "晋升发展", "实习体验", "面试难度"],
        )

    def test_env_can_narrow_further(self):
        pack = B.resolve_query_pack(" 年终奖 ")
        self.assertEqual([p["topic"] for p in pack], ["年终奖"])

    def test_unknown_topic_is_skipped_not_fatal(self):
        pack = B.resolve_query_pack("年终奖,不存在的主题,晋升发展")
        self.assertEqual([p["topic"] for p in pack], ["年终奖", "晋升发展"])

    def test_all_invalid_falls_back_to_default(self):
        """repo Variable 打错一个字不该让整轮 T3 空转 → 回落默认 3 主题，绝不返回空包。"""
        for raw in ("", "   ", ",,,", "typo1,typo2"):
            self.assertEqual([p["topic"] for p in B.resolve_query_pack(raw)],
                             ["年终奖", "加班文化", "晋升发展"], raw)

    def test_duplicates_collapse(self):
        pack = B.resolve_query_pack("年终奖,年终奖,加班文化")
        self.assertEqual([p["topic"] for p in pack], ["年终奖", "加班文化"])

    def test_resolved_pack_entries_are_copies(self):
        """返回的是目录条目的拷贝——调用方改了不该污染全局目录。"""
        pack = B.resolve_query_pack("年终奖")
        pack[0]["query"] = "tampered"
        self.assertNotEqual(B.T3_TOPIC_CATALOG["年终奖"]["query"], "tampered")

    def test_module_level_pack_comes_from_catalog(self):
        for entry in B.T3_QUERY_PACK:
            self.assertIn(entry["topic"], B.T3_TOPIC_CATALOG)
            self.assertEqual(entry, B.T3_TOPIC_CATALOG[entry["topic"]])
        self.assertTrue(B.T3_QUERY_PACK)


if __name__ == "__main__":
    unittest.main()
