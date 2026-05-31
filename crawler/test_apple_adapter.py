import json
import unittest

from adapters.apple import AppleAdapter


class AppleAdapterTests(unittest.TestCase):
    def test_parses_public_search_page_hydration_data(self):
        hydration = {
            "loaderData": {
                "search": {
                    "searchResults": [
                        {
                            "id": "200664580-3956",
                            "postingTitle": "Technical Product Manager",
                            "transformedPostingTitle": "technical-product-manager",
                            "team": {"teamCode": "CORSV"},
                            "locations": [{"name": "Sunnyvale"}],
                            "jobSummary": "Build official Apple Store Online products.",
                            "postingDate": "May 21, 2026",
                            "type": "REQ",
                        }
                    ]
                }
            }
        }
        html = (
            "<script>window.__staticRouterHydrationData = JSON.parse("
            + json.dumps(json.dumps(hydration))
            + ");</script>"
        )

        jobs = AppleAdapter().parse(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Technical Product Manager")
        self.assertEqual(jobs[0].location, "Sunnyvale")
        self.assertEqual(
            jobs[0].jd_url,
            "https://jobs.apple.com/en-us/details/200664580-3956/technical-product-manager?team=CORSV",
        )


if __name__ == "__main__":
    unittest.main()
