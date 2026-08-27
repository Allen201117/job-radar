"""验证引擎纯决策逻辑单测（无网络）。这是「机器验证替代人审」闸门的核心。"""
import unittest

import insight_engine as E


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}


class _FakeClient:
    def __init__(self):
        self.timeouts = []

    def post(self, _url, json=None, headers=None, timeout=None):
        self.timeouts.append(timeout)
        return _FakeResponse()


class TestEngineDecision(unittest.TestCase):
    def test_402_and_insufficient_balance_are_account_errors(self):
        self.assertTrue(E.is_account_error(402, "Sorry, your account balance is insufficient"))
        self.assertTrue(E.is_account_error(500, "账户余额不足"))
        self.assertFalse(E.is_account_error(429, "System is too busy now"))

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


class TestChatJsonTimeout(unittest.TestCase):
    def setUp(self):
        self._api_key = E.os.environ.get("SILICONFLOW_API_KEY")
        E.os.environ["SILICONFLOW_API_KEY"] = "test-key"

    def tearDown(self):
        if self._api_key is None:
            E.os.environ.pop("SILICONFLOW_API_KEY", None)
        else:
            E.os.environ["SILICONFLOW_API_KEY"] = self._api_key

    def test_chat_json_defaults_to_existing_timeout(self):
        client = _FakeClient()
        self.assertEqual(E.chat_json([{"role": "user", "content": "x"}], client=client), {"ok": True})
        self.assertEqual(client.timeouts, [E.TIMEOUT])

    def test_chat_json_accepts_custom_timeout(self):
        client = _FakeClient()
        self.assertEqual(
            E.chat_json([{"role": "user", "content": "x"}], client=client, timeout=90),
            {"ok": True},
        )
        self.assertEqual(client.timeouts, [90])


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
        E.judge_claim = lambda company, dim, content, sources, client=None: {
            "verdict": "entailment", "confidence": 0.9, "reason": "",
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0, 1], "sample_size": None,
        }
        sources = [{"url": "u1", "publisher": "A", "text": "t1"}, {"url": "u2", "publisher": "B", "text": "t2"}]
        res = E.run_pipeline("X", "culture", sources)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["status"], "active")  # entailment 0.9 + 2 publisher → active
        self.assertEqual(res[1]["status"], "drop")    # 越界 source_idx → 无可追溯 → drop

    def test_pipeline_single_publisher_drops_experience(self):
        E.extract_claims = lambda *a, **k: [{"content": "c", "grade": "experience", "source_idx": 0}]
        E.judge_claim = lambda *a, **k: {
            "verdict": "entailment", "confidence": 0.9,
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0], "sample_size": None,
        }
        res = E.run_pipeline("X", "culture", [{"url": "u", "publisher": "A", "text": "t"}])
        self.assertEqual(res[0]["status"], "drop")  # experience 仅 1 publisher → 共识不足 → drop

    def test_pipeline_drops_claim_about_other_company_or_dimension(self):
        E.extract_claims = lambda *a, **k: [{"content": "c", "grade": "fact", "source_idx": 0}]
        E.judge_claim = lambda *a, **k: {
            "verdict": "entailment", "confidence": 0.9,
            "company_relevant": False, "dimension_relevant": True,
            "supported_source_idxs": [0], "sample_size": None,
        }
        res = E.run_pipeline("目标公司", "hiring", [{"url": "u", "publisher": "A", "text": "行业加班新闻"}])
        self.assertEqual(res[0]["status"], "drop")

        E.judge_claim = lambda *a, **k: {
            "verdict": "entailment", "confidence": 0.9,
            "company_relevant": True, "dimension_relevant": False,
            "supported_source_idxs": [0], "sample_size": None,
        }
        res = E.run_pipeline("目标公司", "hiring", [{"url": "u", "publisher": "A", "text": "加班文化"}])
        self.assertEqual(res[0]["status"], "drop")

    def test_pipeline_uses_only_judge_supported_sources_for_consensus_and_sample(self):
        E.extract_claims = lambda *a, **k: [{"content": "c", "grade": "experience", "source_idx": 0}]
        E.judge_claim = lambda *a, **k: {
            "verdict": "entailment", "confidence": 0.9,
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0], "sample_size": 7,
        }
        sources = [
            {"url": "u1", "publisher": "A", "text": "t1"},
            {"url": "u2", "publisher": "B", "text": "无关结果"},
        ]
        res = E.run_pipeline("X", "culture", sources)
        self.assertEqual(res[0]["status"], "drop")  # 不能拿无关 B 源凑共识
        self.assertEqual(res[0]["claim"]["sample_size"], 7)


class TestJudgeParsing(unittest.TestCase):
    def test_judge_parses_relevance_supporting_sources_and_content_sample_only(self):
        original = E.chat_json
        E.chat_json = lambda *a, **k: {
            "verdict": "entailment", "confidence": "0.8", "reason": "原文直接提及",
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0, "1", 9, -1], "sample_size": "12",
        }
        try:
            result = E.judge_claim("目标公司", "culture", "据公开讨论…", [
                {"publisher": "A", "text": "样本一"},
                {"publisher": "B", "text": "样本二"},
            ])
        finally:
            E.chat_json = original
        self.assertEqual(result["supported_source_idxs"], [0, 1])
        self.assertEqual(result["sample_size"], 12)
        self.assertTrue(result["company_relevant"])
        self.assertTrue(result["dimension_relevant"])


if __name__ == "__main__":
    unittest.main()
