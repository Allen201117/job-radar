"""京东按事业群派生子公司归属的单测——纯解析、不打网络。

背景：必投清单把「京东科技」「京东物流」记成独立公司，而 jd.py 过去把 company 硬编码成
「京东」，两家明明有在招岗却被算成覆盖缺口。现改为读列表行自报的 positionDeptName 派生。
假数据取自 2026-08-27 live 列表的真实字段形状（positionDeptName 永远是顶层事业群名，
positionDeptCode / positionDeptCodeFullpath 全为空串）。
"""
import json
import unittest

from adapters.jd import JdAdapter, _DEPT_TO_COMPANY


def _row(dept, requirement_id, title):
    """构造一条与 live 同形状的列表行（只保留本测试关心的字段）。"""
    return {
        "positionDeptName": dept,
        "positionDeptCode": "",
        "positionDeptCodeFullpath": "",
        "requirementId": requirement_id,
        "positionNameOpen": title,
        "positionName": title + "岗",
        "workCity": "北京市",
        "jobType": "运营类",
        "workContent": "负责相关工作",
        "qualification": "本科及以上",
        "formatPublishTime": "2026-08-27",
    }


class JdSubsidiaryDerivationTest(unittest.TestCase):
    def _parse(self, rows):
        return JdAdapter().parse(json.dumps(rows, ensure_ascii=False))

    def test_derives_must_apply_subsidiaries(self):
        """必投清单里独立成行的两家 → 派生成清单里的规范写法。"""
        jobs = self._parse([
            _row("京东科技", 223407, "保险履约运营"),
            _row("京东物流", 223408, "仓储运营"),
        ])

        self.assertEqual([j.company for j in jobs], ["京东科技", "京东物流"])

    def test_unknown_dept_falls_back_to_source_company(self):
        """未在映射表里的事业群留空字符串，交给 normalizer 回落 sources.company（「京东」）。

        「国际事业部」「探索研究院」尤其不能派生——名字不含「京东」二字，派生了反而会把这些岗
        踢出必投清单 %京东% 的覆盖统计。
        """
        jobs = self._parse([
            _row("京东零售", 223409, "商品运营"),
            _row("京东健康", 223410, "医药运营"),
            _row("京东工业", 223411, "工业品采购"),
            _row("京东集团", 223412, "法务"),
            _row("国际事业部", 223413, "海外运营"),
            _row("探索研究院", 223414, "算法研究员"),
            _row("从未见过的新事业群", 223415, "神秘岗位"),
        ])

        self.assertEqual([j.company for j in jobs], [""] * 7)

    def test_missing_or_blank_dept_field_falls_back(self):
        """字段缺失 / 空串 / 纯空白都不能炸，一律回落。"""
        blank = _row("", 223416, "无部门岗")
        whitespace = _row("  ", 223417, "空白部门岗")
        missing = _row("京东科技", 223418, "缺字段岗")
        del missing["positionDeptName"]

        jobs = self._parse([blank, whitespace, missing])

        self.assertEqual([j.company for j in jobs], ["", "", ""])

    def test_dept_name_with_surrounding_whitespace_still_matches(self):
        jobs = self._parse([_row(" 京东物流 ", 223419, "运输规划")])

        self.assertEqual(jobs[0].company, "京东物流")

    def test_derivation_keeps_other_fields_intact(self):
        """派生 company 不得影响 jd_url / title / job_type 等既有字段。"""
        jobs = self._parse([_row("京东科技", 223407, "保险履约运营")])
        job = jobs[0]

        self.assertEqual(job.company, "京东科技")
        self.assertEqual(job.title, "保险履约运营")
        self.assertEqual(
            job.jd_url,
            "https://zhaopin.jd.com/web/job-info-detail?requementId=223407",
        )
        self.assertEqual(job.apply_url, job.jd_url)
        self.assertEqual(job.location, "北京市")
        self.assertEqual(job.job_type, "社招")
        self.assertEqual(job.posted_at, "2026-08-27")
        self.assertIn("本科及以上", job.summary)

    def test_mapping_targets_are_verbatim_must_apply_names(self):
        """映射目标必须逐字命中 lib/must-apply-list.json 里真实存在的公司名。

        防两类回归：① 手滑写成清单里没有的名字（派生了也换不来覆盖）；
        ② 误派生到「京东方」(BOE)——那是毫不相干的另一家公司。
        """
        from pathlib import Path

        list_path = Path(__file__).resolve().parents[1] / "lib" / "must-apply-list.json"
        with list_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        names = {
            row["name"]
            for industry, rows in data.items()
            if not industry.startswith("_") and isinstance(rows, list)
            for row in rows
            if isinstance(row, dict) and row.get("name")
        }

        for derived in _DEPT_TO_COMPANY.values():
            self.assertIn(derived, names, f"{derived} 不在必投清单里，派生它换不来覆盖")
            # 派生名必须含「京东」，否则会被踢出母公司 %京东% 的覆盖统计
            self.assertIn("京东", derived)
            self.assertNotIn("京东方", derived)


if __name__ == "__main__":
    unittest.main()
