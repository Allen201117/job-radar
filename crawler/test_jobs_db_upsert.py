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
        # （status 不在此列——它走「expired 黏住」的 CASE，见 test_status_keeps_expired_on_recrawl。）
        for col in ("company", "title", "location", "jd_url", "last_seen_at"):
            self.assertIn(f"{col} = %s", clause)
            self.assertNotIn(f"COALESCE(NULLIF(%s, ''), {col})", clause)

    def test_status_keeps_expired_on_recrawl(self):
        # 列表重抓**不得复活** detail 探活确认撤岗的 expired 岗：wt~52%/hotjob~71% 的列表仍夹带
        # 已关闭岗（除身份字段外与在招岗无异），裸 status=%s 会把 sweep 判死的岗每天刷回 active
        # → 用户点开 404/已下线（本次排查的直接根因）。expired 黏住、removed/active 仍刷 active
        # （复活漏看岗、保 job_actions 外键）。status 仍恰好消费一个 %s（ELSE 分支）。
        clause = jobs_db._update_set_clause()
        self.assertIn(
            "status = CASE WHEN jobs.status = 'expired' THEN 'expired' ELSE %s END", clause)
        self.assertNotIn("status = %s", clause)

    def test_enrich_bookkeeping_not_clobbered_by_recrawl(self):
        # enrich_checked_at / enrich_fail_count 由 enrich/sweep 子系统独占（enrich_backlog 直接 UPDATE）。
        # 列表重抓必须不碰它们：否则每次重爬把 enrich_checked_at 抹回 NULL，而死活巡检按
        # enrich_checked_at nulls first 轮转 → 被抹的岗反复插队、sweep 永远追不上（81% never-checked 真因）。
        for col in ("enrich_checked_at", "enrich_fail_count"):
            self.assertNotIn(col, jobs_db._UPDATE_COLS, f"{col} 不应被列表重抓 UPDATE")
        clause = jobs_db._update_set_clause()
        self.assertNotIn("enrich_checked_at", clause)
        self.assertNotIn("enrich_fail_count", clause)

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
