import unittest

from adapters.siemens import SiemensAdapter


class SiemensAdapterTests(unittest.TestCase):
    def test_parses_search_result_articles_with_detail_links(self):
        html = """
        <article class="article article--result">
          <h3 class="article__header__text__title">
            <a class="link" href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/505503">
              Fire Test and Approval Engineer
            </a>
          </h3>
          <span class="list-item-location">
            <span class="list-item-jobCity">Prague</span>,
            <span class="list-item-jobCountry">Czech Republic</span>
          </span>
          <span class="list-item-family">Engineering</span>
        </article>
        """

        jobs = SiemensAdapter().parse(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Fire Test and Approval Engineer")
        self.assertEqual(jobs[0].location, "Prague, Czech Republic")
        self.assertEqual(jobs[0].job_type, "Engineering")
        self.assertEqual(
            jobs[0].jd_url,
            "https://jobs.siemens.com/en_US/externaljobs/JobDetail/505503",
        )


if __name__ == "__main__":
    unittest.main()
