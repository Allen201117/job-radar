"""验证引擎纯决策逻辑单测（无网络）。这是「机器验证替代人审」闸门的核心。"""
import os
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

    def test_registrable_host_merges_subdomains_and_mobile_prefixes(self):
        self.assertEqual(E.registrable_host("https://zhihu.com/question/1"), "zhihu.com")
        self.assertEqual(E.registrable_host("https://zhuanlan.zhihu.com/p/2"), "zhihu.com")
        self.assertEqual(E.registrable_host("https://m.example.com/a"), "example.com")


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

    def test_pipeline_uses_url_domain_not_provider_label_for_consensus(self):
        E.extract_claims = lambda *a, **k: [{"content": "c", "grade": "experience", "source_idx": 0}]
        E.judge_claim = lambda *a, **k: {
            "verdict": "entailment", "confidence": 0.9,
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0, 1], "sample_size": None,
        }
        res = E.run_pipeline("X", "culture", [
            {"url": "https://zhihu.com/question/1", "publisher": "provider-a", "text": "t"},
            {"url": "https://zhuanlan.zhihu.com/p/2", "publisher": "provider-b", "text": "t"},
        ])
        self.assertEqual(res[0]["status"], "drop")

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


class TestQuotePrescreen(unittest.TestCase):
    """judge 之前的零成本引文预筛：编造的丢、格式差异的仍过、拿不准一律放行。"""

    SRC = "据多位受访者称，该公司晚上 9 点后仍有不少人加班，年终奖普遍 2-3 个月。"

    def setUp(self):
        self._extract, self._judge = E.extract_claims, E.judge_claim

    def tearDown(self):
        E.extract_claims, E.judge_claim = self._extract, self._judge

    def test_real_quote_passes(self):
        self.assertTrue(E.quote_supported("晚上 9 点后仍有不少人加班", [self.SRC]))

    def test_fabricated_quote_dropped(self):
        self.assertFalse(E.quote_supported("公司提供每年 20 天带薪年假", [self.SRC]))

    def test_only_whitespace_or_punct_or_fullwidth_diff_still_passes(self):
        self.assertTrue(E.quote_supported("晚上9点后仍有不少人加班", [self.SRC]))        # 少空格
        self.assertTrue(E.quote_supported("晚上 ９ 点后，仍有不少人加班。", [self.SRC]))   # 全角+多标点
        self.assertTrue(E.quote_supported("  年终奖普遍2—3个月  ", [self.SRC]))          # 破折号/首尾空白

    def test_ellipsis_fragments_must_all_come_from_same_source(self):
        self.assertTrue(E.quote_supported("晚上 9 点后……年终奖普遍 2-3 个月", [self.SRC]))
        # 两段分别出自两条来源 = 拼接编造 → 丢
        self.assertFalse(E.quote_supported(
            "晚上 9 点后……人均月薪三万", [self.SRC, "另一篇文章提到人均月薪三万"]))

    def test_missing_or_tiny_quote_and_empty_sources_pass(self):
        self.assertTrue(E.quote_supported(None, [self.SRC]))
        self.assertTrue(E.quote_supported("", [self.SRC]))
        self.assertTrue(E.quote_supported("加班", [self.SRC]))    # 归一后 < 4 字 → 不判定
        self.assertTrue(E.quote_supported("任何引文", []))         # 无正文可比 → 不判定
        self.assertTrue(E.quote_supported("任何引文", [None, ""]))

    def test_pipeline_skips_judge_for_fabricated_quote(self):
        calls = []
        E.extract_claims = lambda *a, **k: [
            {"content": "编的", "grade": "experience", "source_idx": 0, "quote": "公司发 20 个月年终奖"},
            {"content": "真的", "grade": "experience", "source_idx": 0, "quote": "仍有不少人加班"},
        ]

        def _judge(*a, **k):
            calls.append(1)
            return {"verdict": "entailment", "confidence": 0.9, "reason": "",
                    "company_relevant": True, "dimension_relevant": True,
                    "supported_source_idxs": [0, 1], "sample_size": 9}

        E.judge_claim = _judge
        res = E.run_pipeline("X", "culture", [
            {"url": "u1", "publisher": "A", "text": self.SRC},
            {"url": "u2", "publisher": "B", "text": self.SRC},
        ])
        self.assertEqual(res[0]["status"], "drop")
        self.assertIsNone(res[0]["judge"])       # 编造引文 → 判官没被调用
        self.assertEqual(res[1]["status"], "active")
        self.assertEqual(len(calls), 1)          # 两条 claim 只花一次判官调用


class TestWriterSourceCap(unittest.TestCase):
    """writer 只喂前 N 条来源（省 token），且必须是前缀截断以保住 source_idx 语义。"""

    def setUp(self):
        self._chat_json = E.chat_json
        self.captured = {}

        def _fake(messages, **kwargs):
            self.captured["user"] = messages[-1]["content"]
            self.captured["tag"] = kwargs.get("tag")
            return {"claims": []}

        E.chat_json = _fake

    def tearDown(self):
        E.chat_json = self._chat_json
        os.environ.pop("INSIGHT_WRITER_MAX_SOURCES", None)

    @staticmethod
    def _sources(n):
        return [{"url": f"u{i}", "publisher": f"P{i}", "text": f"正文{i}"} for i in range(n)]

    def test_caps_at_eight_and_keeps_prefix_order(self):
        E.extract_claims("X", "culture", self._sources(20))
        user = self.captured["user"]
        self.assertEqual(E.WRITER_MAX_SOURCES, 8)
        self.assertEqual(user.count("[来源"), E.WRITER_MAX_SOURCES)
        self.assertIn("[来源0]", user)
        self.assertIn("[来源7]", user)
        self.assertNotIn("[来源8]", user)   # 第 9 条起不喂
        self.assertNotIn("正文19", user)
        self.assertEqual(self.captured["tag"], "t3-writer")

    def test_env_override_and_fewer_sources_than_cap(self):
        os.environ["INSIGHT_WRITER_MAX_SOURCES"] = "3"
        E.extract_claims("X", "culture", self._sources(20))
        self.assertEqual(self.captured["user"].count("[来源"), 3)
        os.environ["INSIGHT_WRITER_MAX_SOURCES"] = "0"      # 非法值 → 回默认
        self.assertEqual(E.writer_max_sources(), E.WRITER_MAX_SOURCES)
        os.environ["INSIGHT_WRITER_MAX_SOURCES"] = "abc"
        self.assertEqual(E.writer_max_sources(), E.WRITER_MAX_SOURCES)
        os.environ.pop("INSIGHT_WRITER_MAX_SOURCES")
        E.extract_claims("X", "culture", self._sources(2))  # 来源少于上限 → 全喂
        self.assertEqual(self.captured["user"].count("[来源"), 2)


class TestUsageAccounting(unittest.TestCase):
    """真实 token 用量必须被记下来（以前只能按字符数瞎估，欠费无人察觉）。"""

    class _UsageResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{\"ok\": true}"}}],
                    "usage": {"prompt_tokens": 1200, "completion_tokens": 40}}

    class _UsageClient:
        def post(self, _url, json=None, headers=None, timeout=None):
            return TestUsageAccounting._UsageResponse()

    def setUp(self):
        self._api_key = E.os.environ.get("SILICONFLOW_API_KEY")
        E.os.environ["SILICONFLOW_API_KEY"] = "test-key"
        E.reset_llm_usage()

    def tearDown(self):
        E.reset_llm_usage()
        if self._api_key is None:
            E.os.environ.pop("SILICONFLOW_API_KEY", None)
        else:
            E.os.environ["SILICONFLOW_API_KEY"] = self._api_key

    def test_totals_accumulate_per_model(self):
        client = self._UsageClient()
        E.chat_json([{"role": "user", "content": "x"}], client=client, tag="t3-judge")
        E.chat_json([{"role": "user", "content": "x"}], client=client, tag="t3-writer")
        totals = E.llm_usage_totals()
        self.assertEqual(totals["calls"], 2)
        self.assertEqual(totals["prompt_tokens"], 2400)
        self.assertEqual(totals["completion_tokens"], 80)
        self.assertEqual(totals["by_model"][E.llm_config()["model"]]["calls"], 2)

    def test_missing_usage_field_does_not_break_call(self):
        E._record_usage("m", None, "t")          # 接口没返 usage 也不能抛
        self.assertEqual(E.llm_usage_totals()["calls"], 1)

    def test_ops_run_ledger_never_raises(self):
        class _Boom:
            def table(self, _name):
                raise RuntimeError("db down")

        E.chat_json([{"role": "user", "content": "x"}], client=self._UsageClient())
        self.assertFalse(E.record_usage_ops_run(_Boom()))   # 写库炸了也只返回 False
        E.reset_llm_usage()
        self.assertFalse(E.record_usage_ops_run(_Boom()))   # 本轮没调过 LLM → 不写空账


class TestDefaultModels(unittest.TestCase):
    """换模型省钱的两条硬约束：不带 Pro/ 前缀、主备**跨厂商**。"""

    def test_no_pro_prefix_and_cross_vendor_fallback(self):
        self.assertFalse(E.DEFAULT_MODEL.startswith("Pro/"))
        self.assertFalse(E.DEFAULT_FALLBACK_MODEL.startswith("Pro/"))
        self.assertNotEqual(E.DEFAULT_MODEL.split("/")[0].casefold(),
                            E.DEFAULT_FALLBACK_MODEL.split("/")[0].casefold())


class TestJudgeParsing(unittest.TestCase):
    def test_judge_keeps_sample_size_only_when_supported_source_has_literal_number(self):
        original = E.chat_json
        E.chat_json = lambda *a, **k: {
            "verdict": "entailment", "confidence": "0.8", "reason": "原文直接提及",
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0, "1", 9, -1], "sample_size": "12",
            "evidence_kind": "direct",
        }
        try:
            result = E.judge_claim("目标公司", "culture", "据公开讨论…", [
                {"publisher": "A", "text": "样本一"},
                {"publisher": "B", "text": "样本 12 条评价"},
            ])
        finally:
            E.chat_json = original
        self.assertEqual(result["supported_source_idxs"], [0, 1])
        self.assertEqual(result["sample_size"], 12)
        self.assertEqual(result["evidence_kind"], "direct")
        self.assertTrue(result["company_relevant"])
        self.assertTrue(result["dimension_relevant"])

    def test_judge_clears_sample_size_when_number_is_not_in_supported_sources(self):
        original = E.chat_json
        E.chat_json = lambda *a, **k: {
            "verdict": "entailment", "confidence": 0.9,
            "company_relevant": True, "dimension_relevant": True,
            "supported_source_idxs": [0], "sample_size": 18, "evidence_kind": "direct",
        }
        try:
            result = E.judge_claim("目标公司", "culture", "据公开讨论…", [
                {"publisher": "A", "text": "多位员工提到工作节奏快"},
            ])
        finally:
            E.chat_json = original
        self.assertIsNone(result["sample_size"])

    def test_judge_caps_confidence_by_evidence_kind(self):
        original = E.chat_json
        try:
            E.chat_json = lambda *a, **k: {
                "verdict": "entailment", "confidence": 0.95,
                "company_relevant": True, "dimension_relevant": True,
                "supported_source_idxs": [0], "sample_size": None, "evidence_kind": "indirect",
            }
            indirect = E.judge_claim("目标公司", "culture", "c", [{"text": "正文"}])
            E.chat_json = lambda *a, **k: {
                "verdict": "entailment", "confidence": 0.95,
                "company_relevant": True, "dimension_relevant": True,
                "supported_source_idxs": [0], "sample_size": None, "evidence_kind": "listing",
            }
            listing = E.judge_claim("目标公司", "culture", "c", [{"text": "正文"}])
        finally:
            E.chat_json = original
        self.assertEqual(indirect["confidence"], 0.8)
        self.assertEqual(listing["confidence"], 0.4)


if __name__ == "__main__":
    unittest.main()
