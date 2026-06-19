import unittest

import jobs_db


class UpdateSetClauseTests(unittest.TestCase):
    """jobs_db._update_set_clause：保留型富化字段空值不抹既有内容（moka 1% 覆盖根因的修复）。"""

    def test_preserved_fields_use_coalesce_nullif(self):
        clause = jobs_db._update_set_clause()
        for col in ("summary", "job_type", "experience", "education", "deadline"):
            self.assertIn(f"{col} = COALESCE(NULLIF(%s, ''), {col})", clause,
                          f"{col} 应空值保留旧值（防列表重抓抹掉富化内容）")

    def test_non_preserved_fields_overwrite_plainly(self):
        clause = jobs_db._update_set_clause()
        # 标题/公司/链接等列表每次都带的字段：直接覆盖，不走保留逻辑。
        for col in ("company", "title", "location", "jd_url", "status", "last_seen_at"):
            self.assertIn(f"{col} = %s", clause)
            self.assertNotIn(f"COALESCE(NULLIF(%s, ''), {col})", clause)

    def test_placeholder_count_matches_columns(self):
        # 关键不变量：每列恰好消费一个 %s，占位符顺序与 _row_tuple(job, _UPDATE_COLS) 一致，
        # 否则参数错位会写错列。COALESCE(NULLIF(%s,''), col) 也只含一个 %s。
        clause = jobs_db._update_set_clause()
        self.assertEqual(clause.count("%s"), len(jobs_db._UPDATE_COLS))

    def test_clause_column_order_matches_update_cols(self):
        # 列在子句中的出现顺序须与 _UPDATE_COLS 严格一致（参数元组按此顺序投影）。
        clause = jobs_db._update_set_clause()
        positions = [clause.index(f"{c} = ") for c in jobs_db._UPDATE_COLS]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
