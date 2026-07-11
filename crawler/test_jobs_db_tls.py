import unittest

import jobs_db


class JobsDatabaseTlsTest(unittest.TestCase):
    def test_ip_endpoint_uses_hostaddr_and_certificate_name(self):
        kwargs = jobs_db.strict_tls_kwargs(
            "postgresql://user:secret@203.0.113.10:5432/jobs?sslmode=require",
            "/tmp/jobs-ca.pem",
            "localhost.localdomain",
        )

        self.assertEqual(kwargs["sslmode"], "verify-full")
        self.assertEqual(kwargs["sslrootcert"], "/tmp/jobs-ca.pem")
        self.assertEqual(kwargs["host"], "localhost.localdomain")
        self.assertEqual(kwargs["hostaddr"], "203.0.113.10")

    def test_mismatched_dns_endpoint_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "DNS host"):
            jobs_db.strict_tls_kwargs(
                "postgresql://user:secret@db.example.com:5432/jobs",
                "/tmp/jobs-ca.pem",
                "other.example.com",
            )


if __name__ == "__main__":
    unittest.main()
