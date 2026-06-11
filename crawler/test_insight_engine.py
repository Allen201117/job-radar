"""验证引擎纯决策逻辑单测（无网络）。这是「机器验证替代人审」闸门的核心。"""
import unittest

import insight_engine as E


class TestEngineDecision(unittest.TestCase):
    def test_decide_status(self):
        self.assertEqual(E.decide_status("entailment", 0.9), "active")
        self.assertEqual(E.decide_status("entailment", 0.6), "active")
        self.assertEqual(E.decide_status("entailment", 0.5), "pending_review")
        self.assertEqual(E.decide_status("entailment", 0.3), "drop")
        self.assertEqual(E.decide_status("contradiction", 0.99), "drop")
        self.assertEqual(E.decide_status("neutral", 0.99), "drop")

    def test_consensus_ok(self):
        self.assertTrue(E.consensus_ok("fact", 1))
        self.assertFalse(E.consensus_ok("fact", 0))
        self.assertTrue(E.consensus_ok("experience", 2))
        self.assertFalse(E.consensus_ok("experience", 1))

    def test_final_status(self):
        # experience 判官过但仅 1 源 → 共识不足 → drop
        self.assertEqual(E.final_status("entailment", 0.9, "experience", 1), "drop")
        self.assertEqual(E.final_status("entailment", 0.9, "experience", 2), "active")
        self.assertEqual(E.final_status("entailment", 0.9, "fact", 1), "active")
        self.assertEqual(E.final_status("entailment", 0.5, "fact", 1), "pending_review")
        self.assertEqual(E.final_status("contradiction", 0.9, "fact", 5), "drop")

    def test_parse_json_loose(self):
        self.assertEqual(E.parse_json_loose('{"a":1}')["a"], 1)
        self.assertEqual(E.parse_json_loose('啰嗦 {"a":2} 收尾')["a"], 2)
        with self.assertRaises(ValueError):
            E.parse_json_loose("no json here")


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self._e, self._j = E.extract_claims, E.judge_claim

    def tearDown(self):
        E.extract_claims, E.judge_claim = self._e, self._j

    def test_pipeline_active_and_drop(self):
        E.extract_claims = lambda company, dim, sources, client=None: [
            {"content": "据公开讨论该公司强度偏大", "grade": "experience", "source_idx": 0},
            {"content": "无来源支撑", "grade": "experience", "source_idx": 9},  # 越界 idx → drop
        ]
        E.judge_claim = lambda content, src, client=None: {"verdict": "entailment", "confidence": 0.9, "reason": ""}
        sources = [{"url": "u1", "publisher": "A", "text": "t1"}, {"url": "u2", "publisher": "B", "text": "t2"}]
        res = E.run_pipeline("X", "culture", sources)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["status"], "active")  # entailment 0.9 + 2 publisher → active
        self.assertEqual(res[1]["status"], "drop")    # 越界 source_idx → 无可追溯 → drop

    def test_pipeline_single_publisher_drops_experience(self):
        E.extract_claims = lambda *a, **k: [{"content": "c", "grade": "experience", "source_idx": 0}]
        E.judge_claim = lambda *a, **k: {"verdict": "entailment", "confidence": 0.9}
        res = E.run_pipeline("X", "culture", [{"url": "u", "publisher": "A", "text": "t"}])
        self.assertEqual(res[0]["status"], "drop")  # experience 仅 1 publisher → 共识不足 → drop


if __name__ == "__main__":
    unittest.main()
