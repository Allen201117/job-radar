const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// scripts/check-migrations.sh 的第 ③ 条：新迁移不得写带招聘渠道后缀的公司名。
// 背景：岗位公司名直接抄源名，「TCL 校招」会跟着出现在岗位卡和公司筛选里（迁移 320 把存量 55 条改回来了）。
// 这条检查跑在 migrate.yml 的 apply 之前，所以它错放 / 错拦都直接影响上线，两个方向都要钉住。

const SCRIPT = path.join(__dirname, "..", "scripts", "check-migrations.sh");

// 基线编号从脚本里读：只查前缀大于它的文件。夹具的文件名跟着它算，免得基线一动测试就测不到东西。
const BASELINE = Number(/^CHANNEL_SUFFIX_BASELINE=(\d+)$/m.exec(fs.readFileSync(SCRIPT, "utf8"))[1]);
const NEXT = String(BASELINE + 1);

function runOn(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mig-check-"));
  try {
    for (const [name, body] of Object.entries(files)) fs.writeFileSync(path.join(dir, name), body, "utf8");
    // Windows 上脚本路径带盘符反斜杠，bash 认正斜杠写法。
    const r = spawnSync("bash", [SCRIPT.replace(/\\/g, "/"), dir.replace(/\\/g, "/")], { encoding: "utf8" });
    return { code: r.status, out: `${r.stdout}${r.stderr}` };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test("新迁移往 sources 写「X 校招 / X 实习 / X 社招」→ 拦下并点名文件与行", () => {
  for (const suffix of ["校招", "实习", "社招"]) {
    const r = runOn({
      [`${NEXT}_seed_bad.sql`]: `insert into sources (company, source_url)\nvalues ('TCL ${suffix}', 'https://x.example/a');\n`,
    });
    assert.equal(r.code, 1, r.out);
    assert.ok(r.out.includes(`${NEXT}_seed_bad.sql`), r.out);
    assert.match(r.out, new RegExp(`TCL ${suffix}`));
  }
});

test("不该拦的：历史文件、注释行、带豁免标记的行、名字本身含这两个字但不是后缀", () => {
  const r = runOn({
    // 基线及以前的文件不查（改名的那份迁移自己就要写出旧名）
    [`${BASELINE}_old.sql`]: "update sources set company = 'TCL' where company = 'TCL 校招';\n",
    [`${NEXT}_seed_ok.sql`]: [
      "-- 说明里提到 'TCL 校招' 不算",
      "   -- 缩进的注释 'TCL 实习' 也不算",
      "insert into sources (company) values ('实习僧'), ('某某校招网'), ('好公司');",
      "select '校招 岗位很多' as note, '2027 届校招' as title2;", // 后缀前没有空白 / 后缀不在末尾
      "update company_profiles set aliases = array_remove(aliases, 'TCL 校招'); -- allow-channel-suffix",
      "",
    ].join("\n"),
  });
  assert.equal(r.code, 0, r.out);
});

// 仓库里真实的迁移目录不在这里跑：脚本逐文件起子进程，Windows 上整目录要半分钟；
// migrate.yml 每次 apply 前都会拿真实目录跑它，那里红了迁移就不会应用。
