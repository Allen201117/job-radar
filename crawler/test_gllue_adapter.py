import json
import unittest

from adapters.gllue import GllueAdapter


class GllueAdapterTest(unittest.TestCase):
    def test_parse_keeps_card_url_location_and_detail_summary(self):
        adapter = GllueAdapter()
        card = """
        <a class="block" href="./jobs/%E9%A1%B9%E7%9B%AE%E6%88%90%E6%9C%AC%E7%BB%8F%E7%90%86-84539">
          <h3>项目成本经理</h3><svg class="lucide-map-pin"></svg><span title="上海">上海</span>
        </a>
        """
        rows = adapter._list_rows(card, "https://longfor.career.gllue.com/jobs?page=1")
        payload = json.dumps({"jobs": [{**rows[0], "summary": "职位描述：负责成本控制"}]}, ensure_ascii=False)
        jobs = adapter.parse(payload)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].location, "上海")
        self.assertEqual(jobs[0].summary, "职位描述：负责成本控制")
        self.assertEqual(jobs[0].jd_url, "https://longfor.career.gllue.com/jobs/%E9%A1%B9%E7%9B%AE%E6%88%90%E6%9C%AC%E7%BB%8F%E7%90%86-84539")

    def test_detail_summary_reads_ssr_description_container(self):
        html = '<div><div><h4>职位描述</h4><div class="whitespace-pre-wrap">岗位职责\n任职要求</div></div></div>'
        self.assertEqual(GllueAdapter._detail_summary(html), "岗位职责 任职要求")

    def test_domestic_gllue_does_not_apply_foreign_region_filter(self):
        payload = json.dumps({"jobs": [{
            "title": "海外租户示例岗位", "location": "Paris",
            "jd_url": "https://example.career.gllue.com/jobs/example-1",
        }]}, ensure_ascii=False)
        jobs = GllueAdapter().parse(payload)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(GllueAdapter._DETAIL_CAP, 400)


if __name__ == "__main__":
    unittest.main()
