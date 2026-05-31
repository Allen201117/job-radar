import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class DbEnvironmentTests(unittest.TestCase):
    def test_load_environment_reads_root_env_local_when_values_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env.local"
            env_file.write_text(
                "SUPABASE_URL=https://example.supabase.co\n"
                "SUPABASE_SERVICE_ROLE_KEY=service-key\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                db.load_environment(project_root=Path(tmp))

                self.assertEqual(
                    os.environ["SUPABASE_URL"],
                    "https://example.supabase.co",
                )
                self.assertEqual(os.environ["SUPABASE_SERVICE_ROLE_KEY"], "service-key")


if __name__ == "__main__":
    unittest.main()
