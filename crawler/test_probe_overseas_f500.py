"""probe_overseas_f500 纯函数单测（不打网络）：verdict 判定 + source_url 拼接 + 迁移 SQL 生成。"""
import unittest

from probe_overseas_f500 import build_source_url, decide_verdict, emit_migration_sql


class TestBuildSourceUrl(unittest.TestCase):
    def test_greenhouse(self):
        self.assertEqual(
            build_source_url("greenhouse", "databricks"),
            "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true",
        )

    def test_lever(self):
        self.assertEqual(
            build_source_url("lever", "kraken"),
            "https://api.lever.co/v0/postings/kraken?mode=json",
        )

    def test_ashby(self):
        self.assertEqual(
            build_source_url("ashby", "openai"),
            "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true",
        )

    def test_unsupported_raises(self):
        with self.assertRaises(ValueError):
            build_source_url("workday", "acme")


class TestDecideVerdict(unittest.TestCase):
    def test_too_few_overseas_rejected(self):
        ok, reason = decide_verdict(4, [200, 200, 200], min_overseas=5)
        self.assertFalse(ok)
        self.assertIn("too_few_overseas", reason)

    def test_enough_overseas_with_200_verified(self):
        ok, reason = decide_verdict(5, [None, 200], min_overseas=5)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_jd_all_walled_rejected(self):
        # 有海外岗但 jd_url 全 403/失败 → 过不了质量门
        ok, reason = decide_verdict(50, [403, 403, None], min_overseas=5)
        self.assertFalse(ok)
        self.assertIn("jd_url_unreachable", reason)

    def test_boundary_exactly_min_verified(self):
        ok, _ = decide_verdict(5, [200], min_overseas=5)
        self.assertTrue(ok)

    def test_empty_jd_rejected(self):
        ok, reason = decide_verdict(9, [], min_overseas=5)
        self.assertFalse(ok)
        self.assertIn("jd_url_unreachable", reason)


class TestEmitMigrationSql(unittest.TestCase):
    def _rows(self):
        return [
            {"company": "Databricks", "adapter": "greenhouse", "token": "databricks",
             "url": "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true",
             "kept_overseas": 435},
            {"company": "Kraken", "adapter": "lever", "token": "kraken",
             "url": "https://api.lever.co/v0/postings/kraken?mode=json",
             "kept_overseas": 12},
        ]

    def test_only_given_rows_emitted(self):
        sql = emit_migration_sql(self._rows(), "170")
        self.assertEqual(sql.count("insert into sources"), 2)
        self.assertIn("databricks", sql)
        self.assertIn("api.lever.co/v0/postings/kraken", sql)

    def test_each_insert_is_idempotent_guarded(self):
        sql = emit_migration_sql(self._rows(), "170")
        self.assertEqual(sql.count("where not exists (select 1 from sources where source_url ="), 2)

    def test_regions_literal_present(self):
        sql = emit_migration_sql(self._rows(), "170")
        self.assertEqual(sql.count("'{CN,US,SG,Remote}'::text[]"), 2)

    def test_single_quote_escaped(self):
        rows = [{"company": "O'Reilly", "adapter": "greenhouse", "token": "oreilly",
                 "url": "https://boards-api.greenhouse.io/v1/boards/oreilly/jobs?content=true",
                 "kept_overseas": 7}]
        sql = emit_migration_sql(rows, "170")
        self.assertIn("O''Reilly", sql)  # 单引号被转义，SQL 不会破


if __name__ == "__main__":
    unittest.main()
