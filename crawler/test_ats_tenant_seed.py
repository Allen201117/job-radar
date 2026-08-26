import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ats_tenant_seed as seed
import must_apply


class TenantSeedTest(unittest.TestCase):
    def test_parse_tenant_rows_skips_incomplete_rows(self):
        rows = seed.parse_tenant_rows(
            "name,slug,url\n"
            "Trip.com Group,trip/70415,https://app.mokahr.com/social-recruitment/trip/70415\n"
            "缺 URL,missing,\n"
            ",missing,https://app.mokahr.com/social-recruitment/missing/1\n",
            "moka",
        )

        self.assertEqual(rows, [{
            "name": "Trip.com Group",
            "slug": "trip/70415",
            "url": "https://app.mokahr.com/social-recruitment/trip/70415",
            "platform": "moka",
        }])

    def test_tenant_key_reads_moka_and_beisen_tenants(self):
        self.assertEqual(
            seed.tenant_key(
                "moka", "https://app.mokahr.com/social-recruitment/trip/70415"
            ),
            "moka:trip",
        )
        self.assertEqual(
            seed.tenant_key("moka", "https://app.mokahr.com/apply/trip/70415"),
            "moka:trip",
        )
        self.assertEqual(
            seed.tenant_key("beisen", "https://chery.zhiye.com/Social"),
            "beisen:chery",
        )
        self.assertIsNone(seed.tenant_key("moka", "https://example.com/jobs"))
        self.assertIsNone(seed.tenant_key("beisen", "not a url"))

    def test_shared_moka_host_does_not_collapse_distinct_tenants(self):
        """hire-r1.mokahr.com 是多租户共享 host，拿子域当键会把 13 家折叠成一个。

        上游快照里 Tesla APAC / HEYTEA / Klook / Bitget 等 13 家都挂在 hire-r1 下，
        一旦折叠成同一个 moka:hire-r1，filter_new_tenants 去重会静默丢掉其中 12 家。
        """
        tesla = seed.tenant_key(
            "moka", "https://hire-r1.mokahr.com/social-recruitment/tesla/100004142"
        )
        heytea = seed.tenant_key(
            "moka", "https://hire-r1.mokahr.com/social-recruitment/heytea/100000206"
        )
        self.assertEqual(tesla, "moka:tesla")
        self.assertEqual(heytea, "moka:heytea")
        self.assertNotEqual(tesla, heytea)

    def test_must_apply_domain_stems_only_covers_list_companies(self):
        """域名桥接只能取必投清单公司，不能拿 logo_util 全表（545 条覆盖所有库内公司）。

        取全表会让 3SBio、Asymchem 这类非必投公司也被判成必投命中而插队。
        """
        stems = seed.must_apply_domain_stems()
        self.assertTrue(stems, "必投域名桥接不应为空")
        names = set(stems.values())
        listed = {
            str((entry or {}).get("name") or "").strip()
            for companies in must_apply.by_industry().values()
            for entry in companies or []
        }
        self.assertTrue(names.issubset(listed), "桥接里混进了非必投公司")
        # 过短的主体（pg/gm）易撞 slug 张冠李戴，必须被挡在外面。
        self.assertTrue(all(len(stem) >= 4 for stem in stems))

    def test_filter_new_tenants_matches_existing_tenant_not_url_text(self):
        tenants = [{
            "name": "Trip.com Group",
            "slug": "trip/70415",
            "url": "https://app.mokahr.com/social-recruitment/trip/70415",
            "platform": "moka",
        }, {
            "name": "Chery",
            "slug": "chery",
            "url": "https://chery.zhiye.com",
            "platform": "beisen",
        }]

        rows = seed.filter_new_tenants(
            tenants,
            [
                "https://app.mokahr.com/apply/trip/10001",
                "https://chery.zhiye.com/Social",
            ],
        )

        self.assertEqual(rows, [])

    def test_rank_tenants_puts_must_apply_matches_first(self):
        tenants = [{
            "name": "普通公司",
            "slug": "ordinary",
            "url": "https://ordinary.zhiye.com",
            "platform": "beisen",
        }, {
            "name": "齐鲁制药",
            "slug": "qilu",
            "url": "https://qilu.zhiye.com",
            "platform": "beisen",
        }]

        rows = seed.rank_tenants(tenants, ["%齐鲁制药%"])

        self.assertEqual([row["name"] for row in rows], ["齐鲁制药", "普通公司"])


if __name__ == "__main__":
    unittest.main()
