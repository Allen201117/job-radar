import unittest

from adapters.baidu import BaiduAdapter


class BaiduAdapterTest(unittest.TestCase):
    def test_parses_initial_data_with_official_detail_urls(self):
        html = """
        <script>
        window.__INITIAL_DATA__ ={"listData":{"recruitType":"SOCIAL","listDetailData":[
          {"postId":"46ad568d-c116-417c-91fa-49146c36bb05","name":"DuMate后端研发（J99773）","workPlace":"北京市","postType":"技术","updateDate":"2026-05-20","workContent":"负责后端研发","serviceCondition":"熟悉 Go","projectType":undefined}
        ]}}; window.prefix="/jobs";undefined
        </script>
        """

        jobs = BaiduAdapter().parse(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "百度")
        self.assertEqual(jobs[0].title, "DuMate后端研发（J99773）")
        self.assertEqual(jobs[0].location, "北京市")
        # recruitType=SOCIAL → 招聘类型"社招"（而非把岗位类别"技术"误当 job_type）
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].summary, "负责后端研发")
        self.assertEqual(jobs[0].posted_at, "2026-05-20")
        self.assertEqual(
            jobs[0].jd_url,
            "https://talent.baidu.com/jobs/detail/SOCIAL/46ad568d-c116-417c-91fa-49146c36bb05",
        )

    def test_recruit_type_maps_campus_and_intern(self):
        html = """
        <script>
        window.__INITIAL_DATA__ ={"listData":{"recruitType":"CAMPUS","listDetailData":[
          {"postId":"c1","name":"2026校招-算法工程师","workPlace":"北京市","postType":"技术","workContent":"算法研发"},
          {"postId":"i1","name":"数据分析实习","workPlace":"上海市","postType":"技术","workContent":"数据分析","recruitType":"INTERN"}
        ]}}; window.prefix="/jobs";
        </script>
        """

        jobs = BaiduAdapter().parse(html)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].job_type, "校招")  # 列表级 recruitType=CAMPUS
        self.assertEqual(jobs[1].job_type, "实习")  # 行级 recruitType=INTERN 覆盖


if __name__ == "__main__":
    unittest.main()
