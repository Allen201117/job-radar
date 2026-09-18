import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class MainCrashRecordsFailedLedgerTest(unittest.TestCase):
    """main() 中途崩溃必须留痕：此前只有 SyncValidationError 会补台账，别的未捕获异常
    （网络库炸了、解析崩了…）一行都不写——跟本次要治的「静默」问题一模一样。"""

    def test_unexpected_exception_writes_failed_crash_and_reraises(self):
        with patch.object(sync, "sync_tenant_snapshots", side_effect=RuntimeError("boom")), \
             patch.object(sync, "_record_ops_run") as rec:
            with self.assertRaises(RuntimeError):
                sync.main(["--apply"])
            rec.assert_called_once()
            args, kwargs = rec.call_args
            self.assertEqual(args[0], "failed")
            self.assertEqual(args[1], {"crash": "RuntimeError"})

    def test_supabase_unavailable_inside_record_helper_does_not_raise(self):
        # _record_ops_run 自己已经把「拿不到 Supabase client」这一路吞掉了，
        # 主流程的退出码只由 sync_tenant_snapshots 的结果决定，不受台账写入影响。
        with patch.object(sync, "sync_tenant_snapshots", side_effect=RuntimeError("boom")), \
             patch("db.get_supabase", side_effect=ConnectionError("no db")):
            with self.assertRaises(RuntimeError):
                sync.main(["--apply"])


if __name__ == "__main__":
    unittest.main()
