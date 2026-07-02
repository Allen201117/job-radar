import unittest

from adapters.base import RawJob
import normalizer
from sponsorship import sponsorship_signal


class SponsorshipSignalTest(unittest.TestCase):
    def test_none(self):
        self.assertEqual(sponsorship_signal("We are unable to provide visa sponsorship"), "none")
        self.assertEqual(sponsorship_signal("Must be authorized to work in the US without sponsorship"), "none")
        self.assertEqual(sponsorship_signal("US citizens only; security clearance required"), "none")
        self.assertEqual(sponsorship_signal("No sponsorship available for this position"), "none")

    def test_available(self):
        self.assertEqual(sponsorship_signal("Visa sponsorship available"), "available")
        self.assertEqual(sponsorship_signal("We will sponsor H-1B for qualified candidates"), "available")
        self.assertEqual(sponsorship_signal("Relocation and visa support provided"), "available")

    def test_unknown(self):
        self.assertEqual(sponsorship_signal("Great team, fast growth"), "unknown")
        self.assertEqual(sponsorship_signal(""), "unknown")
        self.assertEqual(sponsorship_signal(None), "unknown")

    def test_normalize_writes_sponsorship_signal(self):
        job = normalizer.normalize(
            RawJob(
                company="Acme",
                title="Software Engineer",
                location="New York, NY",
                summary="Visa sponsorship available for qualified candidates.",
                jd_url="https://example.com/jobs/1",
            ),
            source_id="src1",
            company="Acme",
        )
        self.assertEqual(job["sponsorship_signal"], "available")


if __name__ == "__main__":
    unittest.main()
