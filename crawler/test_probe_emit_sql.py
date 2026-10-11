"""probe.emit_sql 不许把带招聘渠道后缀的公司名写进迁移（迁移 320 的来由：2026-06 探活批次这样写出了 46 条）。"""
import unittest

import probe


def _cand(company):
    return {"company": company, "url": "https://wecruit.hotjob.cn/SUx/pb/school.html", "adapter": "hotjob",
            "_valid": 12, "_china": 12, "industry": "消费电子"}


class EmitSqlChannelSuffixTest(unittest.TestCase):
    def test_rejects_names_with_channel_suffix(self):
        for name in ("TCL 校招", "华润电力 CR Power 实习", "云尖信息  社招"):
            with self.assertRaises(ValueError, msg=name) as ctx:
                probe.emit_sql("319_seed_probed_sources", [_cand("好公司"), _cand(name)])
            self.assertIn(name, str(ctx.exception))

    def test_plain_names_and_names_that_merely_contain_the_words_pass(self):
        sql = probe.emit_sql("319_seed_probed_sources", [_cand("TCL"), _cand("实习僧"), _cand("某某校招网")])
        for name in ("TCL", "实习僧", "某某校招网"):
            self.assertIn(f"select '{name}',", sql)


if __name__ == "__main__":
    unittest.main()
