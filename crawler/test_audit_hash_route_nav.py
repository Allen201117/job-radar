"""hash 路由源（byd / kuaishou / 农行等）在浏览器巡检里必须 reload，否则会**删掉在招岗**。

2026-09-06 实测（复刻 audit_dead_links 的 goto + 2500ms 导航）：连着探两个快手岗，
第一个已下线、第二个在招，第二个读到的却是第一个的「该职位已下线」→ classify 判 dead →
--apply 置 expired → 次日被 purge-expired 永久删除。加 reload 后第二个正常渲染自己的内容。
成因：浏览器对「只有 # 后面不同」的 goto 属于同文档导航，**不重新渲染**。
影响面：byd 6,362 + kuaishou 2,830 个 active 岗的 jd_url 都是同一个 base + 不同 hash。
"""
import unittest

import audit_dead_links


class SameDocumentNavTest(unittest.TestCase):
    def test_hash_only_change_is_same_document(self):
        for base in ("https://zhaopin.kuaishou.cn/", "https://job.byd.com/portal/pc/",
                     "https://career.abchina.com/build/index.html"):
            self.assertTrue(
                audit_dead_links.is_same_document_nav(base + "#/a/1", base + "#/a/2"), base)

    def test_adding_a_hash_to_the_same_page_is_same_document(self):
        self.assertTrue(audit_dead_links.is_same_document_nav(
            "https://job.byd.com/portal/pc/", "https://job.byd.com/portal/pc/#/social/x"))

    def test_different_page_is_a_real_navigation(self):
        self.assertFalse(audit_dead_links.is_same_document_nav(
            "https://zhaopin.kuaishou.cn/#/a", "https://job.byd.com/portal/pc/#/b"))
        # 路径不同 = 真导航，会重新渲染，不需要多花一次 reload。
        self.assertFalse(audit_dead_links.is_same_document_nav(
            "https://jobs.example.com/jobs/1", "https://jobs.example.com/jobs/2"))

    def test_no_previous_url_is_not_same_document(self):
        """浏览器刚重建（fresh()）或上一跳跳失败时 previous_url 会被清空——那时页面是空白页，
        不可能读到上一个岗的内容，不该白花一次 reload。"""
        self.assertFalse(audit_dead_links.is_same_document_nav(None, "https://a/#/x"))
        self.assertFalse(audit_dead_links.is_same_document_nav("https://a/#/x", None))


if __name__ == "__main__":
    unittest.main()
