import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from adapters.eightfold import EightfoldAdapter


class EightfoldParseTest(unittest.TestCase):
    def _parse(self, positions):
        payload = json.dumps({"_origin": "https://hsbc.eightfold.ai", "positions": positions})
        return EightfoldAdapter().parse(payload)

    def test_uses_canonical_url_and_keeps_china(self):
        jobs = self._parse([
            {"id": 1, "name": "Risk Analyst", "location": "Shanghai, Shanghai, China",
             "canonicalPositionUrl": "https://portal.careers.hsbc.com/careers/job/1"},
        ])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Risk Analyst")
        self.assertEqual(jobs[0].jd_url, "https://portal.careers.hsbc.com/careers/job/1")
        self.assertEqual(jobs[0].location, "Shanghai, Shanghai, China")
        self.assertEqual(jobs[0].company, "")  # 由 sources.company 兜底

    def test_falls_back_to_origin_url_when_no_canonical(self):
        jobs = self._parse([
            {"id": 42, "name": "Engineer", "location": "Beijing, China"},
        ])
        self.assertEqual(jobs[0].jd_url, "https://hsbc.eightfold.ai/careers/job/42")

    def test_drops_non_china_and_titleless(self):
        jobs = self._parse([
            {"id": 3, "name": "US Role", "location": "New York, United States",
             "canonicalPositionUrl": "https://x/careers/job/3"},
            {"id": 4, "name": "", "location": "Shenzhen, China",
             "canonicalPositionUrl": "https://x/careers/job/4"},
        ])
        self.assertEqual(jobs, [])

    def test_dedupes_by_url(self):
        jobs = self._parse([
            {"id": 5, "name": "A", "location": "Shanghai, China", "canonicalPositionUrl": "https://x/job/5"},
            {"id": 6, "name": "B", "location": "Shanghai, China", "canonicalPositionUrl": "https://x/job/5"},
        ])
        self.assertEqual(len(jobs), 1)

    def test_bad_json(self):
        self.assertEqual(EightfoldAdapter().parse("nope"), [])


if __name__ == "__main__":
    unittest.main()
