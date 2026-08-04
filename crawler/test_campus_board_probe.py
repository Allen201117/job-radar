import unittest

from campus_board_probe import (
    NEEDS_SEPARATE_CAMPUS_SOURCE,
    classify_empty_result,
    campus_candidate_url,
    is_duplicate_board,
    job_identities,
    job_identity,
)


class TestPlatformsThatNeedNoCampusSource(unittest.TestCase):
    """给「既有源已抓全三类」的平台补校招源 = 造重复源 = 迁移 186 那场灾难重演
    （双源抢岗 → last_seen_at 搁浅 → 缺席探活永久失效 → 死岗下不了架）。"""

    def test_beisen_wt_feishu_never_get_a_candidate(self):
        for adapter, url in (
            ("beisen", "https://asymchem.zhiye.com/social"),      # Category:[] 抓全类别
            ("wt", "https://x.hotjob.cn/wt/BRAND/web/index"),     # _RECRUIT_TYPES=(2,1,12)
            ("feishu", "https://li.jobs.feishu.cn/index/position"),  # live 验证 portal 不影响返回集
            ("xiaomi_feishu", "https://xiaomi.jobs.f.mioffice.cn/index/position"),
        ):
            self.assertIsNone(campus_candidate_url(adapter, url), f"{adapter} 不该产出候选")

    def test_unknown_adapter_gets_no_candidate(self):
        # 白名单式：没验证过的平台一律不推候选，避免凭空猜出重复源
        self.assertIsNone(campus_candidate_url("brand_new_ats", "https://x.com/jobs"))
        self.assertIsNone(campus_candidate_url("", ""))

    def test_registry_marks_verified_platforms(self):
        self.assertTrue(NEEDS_SEPARATE_CAMPUS_SOURCE["hotjob"])
        self.assertTrue(NEEDS_SEPARATE_CAMPUS_SOURCE["moka"])
        self.assertFalse(NEEDS_SEPARATE_CAMPUS_SOURCE["beisen"])
        self.assertFalse(NEEDS_SEPARATE_CAMPUS_SOURCE["feishu"])


class TestCandidateDerivation(unittest.TestCase):
    def test_hotjob_social_to_school(self):
        self.assertEqual(
            campus_candidate_url("hotjob", "https://jd.hotjob.cn/SU69/pb/social.html"),
            "https://jd.hotjob.cn/SU69/pb/school.html")

    def test_hotjob_already_school_returns_none(self):
        self.assertIsNone(campus_candidate_url("hotjob", "https://jd.hotjob.cn/SU69/pb/school.html"))

    def test_moka_drops_portal_id_for_redirect(self):
        # portal id 不可推导（实测约一半是 social+1，另一半完全无关）→ 交给 moka 302 跳转
        self.assertEqual(
            campus_candidate_url("moka", "https://app.mokahr.com/social-recruitment/xcmg/148090"),
            "https://app.mokahr.com/campus-recruitment/xcmg")

    def test_moka_already_campus_returns_none(self):
        self.assertIsNone(
            campus_candidate_url("moka", "https://app.mokahr.com/campus-recruitment/xcmg/148091"))
        self.assertIsNone(
            campus_candidate_url("moka", "https://app.mokahr.com/campus_apply/trip/37757"))

    def test_moka_custom_host_preserved(self):
        self.assertEqual(
            campus_candidate_url("moka", "https://apply.careers.dji.com/social-recruitment/dji/170070"),
            "https://apply.careers.dji.com/campus-recruitment/dji")


class TestJobIdentity(unittest.TestCase):
    def test_extracts_id_across_platforms(self):
        self.assertEqual(job_identity("https://x.jobs.feishu.cn/campus/position/7412/detail"), "7412")
        self.assertEqual(job_identity("https://campus.kuaishou.cn/#/campus/job-info/13012"), "13012")
        self.assertEqual(job_identity("https://t.com/p?positionId=199902900003"), "199902900003")
        self.assertEqual(job_identity("https://zhaopin.meituan.com/x?jobUnionId=4612723000"), "4612723000")

    def test_portal_prefix_does_not_change_identity(self):
        # 这是整个非重复门的支点：同一个岗在不同 portal 下 URL 不同，身份必须相同
        a = job_identity("https://x.jobs.feishu.cn/index/position/7412/detail")
        b = job_identity("https://x.jobs.feishu.cn/campus/position/7412/detail")
        self.assertEqual(a, b)

    def test_unparseable_returns_none_and_is_dropped(self):
        self.assertIsNone(job_identity("https://x.com/careers"))
        self.assertIsNone(job_identity(""))
        self.assertIsNone(job_identity(None))
        self.assertEqual(job_identities(["https://x.com/careers", None]), set())


class TestDuplicateBoardGate(unittest.TestCase):
    """今天真差点栽的那个坑：飞书 /campus 与 /index 的 jd_url 完全不同（portal 前缀不同），
    按 URL 比交集 0 像两个板块；按岗位 ID 比才发现是同一批 600 个岗。"""

    def test_same_jobs_under_different_portal_is_duplicate(self):
        existing = [f"https://x.jobs.feishu.cn/index/position/{i}/detail" for i in range(100)]
        candidate = [f"https://x.jobs.feishu.cn/campus/position/{i}/detail" for i in range(100)]
        self.assertEqual(len(set(existing) & set(candidate)), 0)   # URL 层面毫无交集
        self.assertTrue(is_duplicate_board(existing, candidate))   # 身份层面完全重复

    def test_genuinely_different_board_passes(self):
        existing = [f"https://x.mokahr.com/social/?jobId={i}" for i in range(100)]
        candidate = [f"https://x.mokahr.com/campus/?jobId={1000+i}" for i in range(100)]
        self.assertFalse(is_duplicate_board(existing, candidate))

    def test_partial_overlap_below_threshold_passes(self):
        existing = [f"https://x/?jobId={i}" for i in range(100)]
        candidate = [f"https://y/?jobId={i}" for i in range(50, 150)]  # 50% 重叠
        self.assertFalse(is_duplicate_board(existing, candidate))

    def test_overlap_at_threshold_is_duplicate(self):
        existing = [f"https://x/?jobId={i}" for i in range(100)]
        candidate = [f"https://y/?jobId={i}" for i in range(20, 120)]  # 80% 重叠
        self.assertTrue(is_duplicate_board(existing, candidate))

    def test_unparseable_identities_default_to_duplicate(self):
        # 保守：宁可漏建一个源，也不建重复源——漏建少抓一个板块，建重复会让
        # 该租户的缺席探活永久失效（迁移 186 教训）
        self.assertTrue(is_duplicate_board(["https://x.com/a"], ["https://x.com/b"]))
        self.assertTrue(is_duplicate_board([], ["https://x/?jobId=1"]))
        self.assertTrue(is_duplicate_board(["https://x/?jobId=1"], []))


class TestClassifyEmptyResult(unittest.TestCase):
    """栽过三次的区分：「等开闸时什么都没等到」是正常态，不是故障态。
    判错代价不对称——当故障 = 吃长退避、错过整个开闸窗口；当空板块 = 最多多探一次。"""

    def test_empty_status_is_an_empty_board_not_a_failure(self):
        # run_crawl 的 "empty"（列表返回空）既不计 success 也不计 failed，
        # 只看 success 会把 11 个正常源全判成抓取失败（2026-08-04 实测）
        self.assertEqual(classify_empty_result({"success": 0, "failed": 0, "empty": 1}), "empty_board")

    def test_success_with_zero_jobs_is_empty_board(self):
        self.assertEqual(classify_empty_result({"success": 1, "failed": 0, "empty": 0}), "empty_board")

    def test_real_failure_stays_a_failure(self):
        self.assertEqual(classify_empty_result({"success": 0, "failed": 1, "empty": 0}), "no_healthy_jobs")

    def test_skipped_only_counts_as_failure(self):
        # robots skipped：既没 success 也没 empty → 不算「板块空着」，走长退避
        self.assertEqual(classify_empty_result({"success": 0, "failed": 0, "empty": 0, "skipped": 1}),
                         "no_healthy_jobs")

    def test_missing_or_none_result_is_failure(self):
        self.assertEqual(classify_empty_result(None), "no_healthy_jobs")
        self.assertEqual(classify_empty_result({}), "no_healthy_jobs")


if __name__ == "__main__":
    unittest.main()
