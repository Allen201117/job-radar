import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_ats_tenants as sync


_OLD = "name,slug,url\n旧租户,old,https://old.zhiye.com/Social\n"
_NEW = (
    "name,slug,url\n"
    "旧租户,old,https://old.zhiye.com/Social\n"
    "新租户,new,https://new.zhiye.com/Social\n"
)
_OLD_MOKA = "name,slug,url\n旧租户,old,https://app.mokahr.com/social-recruitment/old/1\n"
_NEW_MOKA = (
    "name,slug,url\n"
    "旧租户,old,https://app.mokahr.com/social-recruitment/old/1\n"
    "新租户,new,https://app.mokahr.com/social-recruitment/new/1\n"
)


class SyncAtsTenantsTest(unittest.TestCase):
    def _snapshots(self, root):
        for filename in sync.TENANT_FILES:
            text = _OLD_MOKA if filename == "moka.csv" else _OLD
            (root / filename).write_text(text, encoding="utf-8")

    def test_apply_validated_snapshot_reports_new_tenants_and_overwrites(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._snapshots(data_dir)

            results = sync.sync_tenant_snapshots(
                apply=True,
                data_dir=data_dir,
                fetcher=lambda name: (200, _NEW_MOKA if name == "moka" else _NEW),
            )

            self.assertEqual(
                [(row["old_rows"], row["new_rows"], row["new_tenants"]) for row in results],
                [(1, 2, 1), (1, 2, 1), (1, 2, 1)],
            )
            self.assertEqual((data_dir / "moka.csv").read_text(encoding="utf-8"), _NEW_MOKA)

    def test_invalid_or_shrunk_snapshot_keeps_all_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._snapshots(data_dir)

            with self.assertRaises(sync.SyncValidationError):
                sync.sync_tenant_snapshots(
                    apply=True,
                    data_dir=data_dir,
                    fetcher=lambda name: (404, "not found") if name == "beisen" else (200, "name,slug,url\n"),
                )

            self.assertEqual((data_dir / "moka.csv").read_text(encoding="utf-8"), _OLD_MOKA)
            self.assertEqual((data_dir / "beisen.csv").read_text(encoding="utf-8"), _OLD)

    def test_dry_run_validates_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._snapshots(data_dir)

            results = sync.sync_tenant_snapshots(
                apply=False,
                data_dir=data_dir,
                fetcher=lambda name: (200, _NEW_MOKA if name == "moka" else _NEW),
            )

            self.assertTrue(all(not row["applied"] for row in results))
            self.assertEqual((data_dir / "moka.csv").read_text(encoding="utf-8"), _OLD_MOKA)


if __name__ == "__main__":
    unittest.main()
