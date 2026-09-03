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
        for col in ("company", "title", "location", "country_code", "job_scope", "jd_url", "last_seen_at"):
            self.assertIn(f"{col} = %s", clause)
            self.assertNotIn(f"COALESCE(NULLIF(%s, ''), {col})", clause)

    def test_geo_fields_are_written_but_not_preserved(self):
        for col in ("country_code", "job_scope", "sponsorship_signal"):
            self.assertIn(col, jobs_db._INSERT_COLS)
            self.assertIn(col, jobs_db._UPDATE_COLS)
            self.assertNotIn(col, jobs_db._PRESERVE_IF_EMPTY)

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


class RecruitmentMaterializationTests(unittest.TestCase):
    """招聘类型物化（2026-09-03）：入库时由 JS 权威规则算好，检索直接查这两列。

    为什么要物化：筛选是「按可信度分层裁决」，而检索只能用「正向信号并集」去近似——两者结构
    不同，必然捞进大量注定被否决的岗（live 实测「深圳+校招」4354 条候选里 43% 属此类）。
    """

    def test_two_columns_are_written(self):
        # 必须**两列都写**：job-filter.jobFilterMatch 同时用「是什么类型」和「有没有明确依据」
        # （无依据时：选社招放行降级、选校招/实习淘汰）。只写 category，SQL 表达不了这条规则。
        for col in ("recruitment_category", "recruitment_explicit"):
            self.assertIn(col, jobs_db._INSERT_COLS)
            self.assertIn(col, jobs_db._UPDATE_COLS)

    def test_degraded_classification_must_not_wipe_existing_values(self):
        # 分类降级时写的是 None（「没算出来」），不是「判定为空」。若直接覆盖，一次 node 不可用
        # 就会把全库这两列抹成 NULL —— 与 summary 被列表重抓抹掉的老坑同形态。
        clause = jobs_db._update_set_clause()
        self.assertIn(
            "recruitment_category = COALESCE(NULLIF(%s, ''), recruitment_category)", clause)
        # boolean 列不能套 NULLIF(%s,'')（'' → boolean 强转会报错，整源写库炸掉），走 COALESCE。
        self.assertIn("recruitment_explicit = COALESCE(%s, recruitment_explicit)", clause)
        self.assertNotIn("NULLIF(%s, ''), recruitment_explicit", clause)

    def test_both_write_paths_classify_before_writing(self):
        import inspect
        for fn in (jobs_db.upsert_job, jobs_db.upsert_jobs_batch):
            src = inspect.getsource(fn)
            self.assertIn("_annotate_recruitment", src,
                          f"{fn.__name__} 必须在写库前补齐招聘类型两列")

    def test_classification_failure_never_breaks_ingestion(self):
        # 主链路不能被这个可选的富化步骤拖垮：任何异常都只降级留空，由补漏任务捡回。
        import recruitment_classify

        jobs = [{"title": "2027届 算法工程师", "summary": "", "jd_url": "", "job_type": "校招"}]
        orig = recruitment_classify.classify
        try:
            recruitment_classify.classify = lambda items: (_ for _ in ()).throw(RuntimeError("boom"))
            # annotate 内部调用 classify；异常必须被兜住，且两列留 None。
            try:
                recruitment_classify.annotate(jobs)
            except Exception as exc:  # pragma: no cover
                self.fail(f"分类失败不得抛给调用方：{exc}")
        finally:
            recruitment_classify.classify = orig
