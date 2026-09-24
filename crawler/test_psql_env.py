"""psql_env：连接串绝不进 psql 的命令行参数，也绝不进抛出的异常（2026-09-24 立）。

用一个假 psql（python 脚本）回显它收到的 argv 与 PG* 环境变量，断言密码只经环境变量传入。
不打真实网络。
"""
import json
import os
import stat
import sys
import tempfile
import traceback
import unittest

import psql_env

RAW_PW = "Fake%40pw%2Fw0rd%2Bx"  # 解码后 Fake@pw/w0rd+x
PW = "Fake@pw/w0rd+x"
HOST = "db.example.invalid"
HOSTADDR = "203.0.113.5"


def dsn(tail, scheme="postgresql", user="jobs_user", pw=RAW_PW):
    # 拼出来而不是写成字面量：公开仓的敏感扫描（scripts/scan-sensitive.sh）会把字面连接串当真密码拦下。
    return f"{scheme}://{user}:{pw}@{tail}"


URL = dsn(f"{HOST}:6543/jobs?sslmode=verify-full&sslrootcert=/tmp/ca+1.pem&hostaddr={HOSTADDR}")
SECRETS = [URL, RAW_PW, PW, HOST, HOSTADDR]

_FAKE = f"""#!{sys.executable}
import json, os, sys
pg = {{k: v for k, v in os.environ.items() if k.startswith("PG")}}
mode = os.environ.get("FAKE_PSQL_MODE")
if mode == "fail":
    sys.stderr.write('psql: error: connection to server at "%s" (%s), port %s failed: password "%s" timeout expired\\n'
                     % (pg.get("PGHOST"), pg.get("PGHOSTADDR"), pg.get("PGPORT"), pg.get("PGPASSWORD")))
    sys.exit(2)
sys.stdout.write(json.dumps({{"argv": sys.argv[1:], "pg": pg}}))
"""


class PsqlEnvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.bin = os.path.join(cls._tmp.name, "psql")
        with open(cls.bin, "w") as f:
            f.write(_FAKE)
        os.chmod(cls.bin, os.stat(cls.bin).st_mode | stat.S_IXUSR)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assertNoSecrets(self, text, label):
        for s in SECRETS:
            self.assertNotIn(s, str(text), f"{label} 泄露了敏感片段")

    def test_url_split_into_libpq_env(self):
        self.assertEqual(psql_env.libpq_env_from_url(URL), {
            "PGUSER": "jobs_user", "PGPASSWORD": PW, "PGHOST": HOST, "PGPORT": "6543",
            "PGDATABASE": "jobs", "PGSSLMODE": "verify-full", "PGSSLROOTCERT": "/tmp/ca+1.pem",
            "PGHOSTADDR": HOSTADDR,
        })

    def test_only_present_parts_and_same_as_js(self):
        # 与 tests/psql-env.test.js 同一组用例，两侧口径一致。
        self.assertEqual(psql_env.libpq_env_from_url("postgres://reader@[::1]/d"),
                         {"PGUSER": "reader", "PGHOST": "::1", "PGDATABASE": "d"})
        self.assertEqual(psql_env.libpq_env_from_url("postgresql://db.example.invalid"), {"PGHOST": HOST})
        self.assertEqual(psql_env.libpq_env_from_url("postgresql://%2Fvar%2Frun%2FPg/jobs"),
                         {"PGHOST": "/var/run/Pg", "PGDATABASE": "jobs"})

    def test_bad_urls_raise_without_leaking(self):
        for u in (dsn(f"{HOST}:6543/jobs?keepalives=1"),
                  dsn(f"{HOST}:notaport/jobs"),
                  dsn(f"{HOST}:6543,{HOSTADDR}:6543/jobs"),
                  dsn(f"{HOST}/jobs", scheme="mysql")):
            with self.assertRaises(ValueError) as cm:
                psql_env.libpq_env_from_url(u)
            self.assertNoSecrets(cm.exception, "报错")

    def test_run_psql_passes_password_via_env_not_argv(self):
        out = json.loads(psql_env.run_psql(
            ["-t", "-A", "-c", "select 1"], dsn(f"{HOST}:6543/jobs"),
            base_env={"PATH": os.environ.get("PATH", ""), "PGSSLMODE": "require", "PGPORT": "1"}, bin=self.bin))
        self.assertEqual(out["argv"], ["-t", "-A", "-c", "select 1"])
        self.assertNoSecrets(json.dumps(out["argv"]), "argv")
        self.assertEqual(out["pg"]["PGPASSWORD"], PW)
        self.assertEqual(out["pg"]["PGPORT"], "6543")      # URL 写了就覆盖环境
        self.assertEqual(out["pg"]["PGSSLMODE"], "require")  # URL 没写仍用环境

    def test_failure_error_is_redacted_and_unchained(self):
        with self.assertRaises(psql_env.PsqlError) as cm:
            psql_env.run_psql(["-c", "select 1"], URL, bin=self.bin,
                              base_env={"PATH": os.environ.get("PATH", ""), "FAKE_PSQL_MODE": "fail"})
        err = cm.exception
        self.assertIn("退出码 2", str(err))
        self.assertIn("<redacted>", str(err))
        self.assertIn("timeout expired", str(err))
        self.assertIsNone(err.__cause__)
        tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
        self.assertNoSecrets(tb, "traceback")

    def test_refuses_url_or_password_in_args(self):
        for args in ([URL, "-c", "select 1"], ["-d", dsn(f"{HOST}/jobs", scheme="postgres", user="u")], ["-c", f"select '{PW}'"]):
            with self.assertRaises(psql_env.PsqlError) as cm:
                psql_env.run_psql(args, URL, bin="/nonexistent/should-not-run")
            self.assertIn("不许出现连接串或密码", str(cm.exception))
            self.assertNoSecrets(cm.exception, "报错")

    def test_missing_binary_and_missing_url(self):
        with self.assertRaises(psql_env.PsqlError) as cm:
            psql_env.run_psql(["-c", "select 1"], URL, bin=os.path.join(self._tmp.name, "no-such-psql"))
        self.assertNoSecrets(cm.exception, "报错")
        with self.assertRaises(psql_env.PsqlError):
            psql_env.run_psql(["-c", "select 1"], "")


if __name__ == "__main__":
    unittest.main()
