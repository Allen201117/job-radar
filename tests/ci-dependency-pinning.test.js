// CI 的 runner 镜像与 Python 包必须锁定，上游发新版不能自己装进来（2026-10-06 立，来由见 CLAUDE.md 同名碑）。
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const WF_DIR = path.join(ROOT, ".github", "workflows");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");
const workflows = fs
  .readdirSync(WF_DIR)
  .filter((f) => /\.ya?ml$/.test(f))
  .map((f) => ({ name: f, text: fs.readFileSync(path.join(WF_DIR, f), "utf8") }));

// PEP 503 规范名：大小写不敏感，连续的 - _ . 视为同一个。
const normalize = (name) => name.toLowerCase().replace(/[-_.]+/g, "-");

// 去掉注释和空行，只留有效行。
function effectiveLines(text) {
  return text
    .split(/\r?\n/)
    .map((l) => l.replace(/(^|\s)#.*$/, "").trim())
    .filter(Boolean);
}

test("workflow 的 runs-on 不用会自己漂移的 *-latest 标签", () => {
  const offenders = [];
  let seen = 0;
  for (const { name, text } of workflows) {
    for (const m of text.matchAll(/^\s*runs-on:\s*(.+)$/gm)) {
      seen += 1;
      if (/-latest\b/.test(m[1])) offenders.push(`${name}: ${m[1].trim()}`);
    }
  }
  assert.ok(seen >= 30, `只扫到 ${seen} 个 runs-on，扫描口径坏了`);
  assert.deepEqual(offenders, [], "改成具体版本（如 ubuntu-24.04），升级系统要先在新镜像上验过");
});

test("requirements.txt 经 -c constraints.txt 引用锁定文件", () => {
  const lines = effectiveLines(read("crawler/requirements.txt"));
  assert.ok(lines.includes("-c constraints.txt"), "requirements.txt 里缺 `-c constraints.txt`，锁定文件不会生效");
});

test("constraints.txt 每一行都是精确版本 name==version", () => {
  const lines = effectiveLines(read("crawler/constraints.txt"));
  assert.ok(lines.length >= 10, `只读到 ${lines.length} 行，文件不对`);
  const bad = lines.filter((l) => !/^[A-Za-z0-9][A-Za-z0-9._-]*==[^\s;=<>!~]+$/.test(l));
  assert.deepEqual(bad, [], "锁定文件只许写 name==version");
  const names = lines.map((l) => normalize(l.split("==")[0]));
  const dup = names.filter((n, i) => names.indexOf(n) !== i);
  assert.deepEqual(dup, [], "同一个包锁了两次");
});

test("requirements.txt 的每个直接依赖都在 constraints.txt 里锁了版本", () => {
  const pinned = new Set(
    effectiveLines(read("crawler/constraints.txt")).map((l) => normalize(l.split("==")[0])),
  );
  const missing = [];
  for (const line of effectiveLines(read("crawler/requirements.txt"))) {
    if (line.startsWith("-")) continue; // -c / -r 之类的选项行
    // 只在 Windows 装的（tzdata）CI 用不到，不要求锁。
    if (/sys_platform\s*==\s*["']win32["']/.test(line)) continue;
    const name = line.match(/^[A-Za-z0-9][A-Za-z0-9._-]*/)?.[0];
    if (!name || !pinned.has(normalize(name))) missing.push(name ?? line);
  }
  assert.deepEqual(missing, [], "新加的依赖要同时写进 crawler/constraints.txt");
});

test("workflow 里的 pip install 一律走 requirements.txt，不在命令行另装不锁版本的包", () => {
  const offenders = [];
  let seen = 0;
  for (const { name, text } of workflows) {
    for (const line of text.split(/\r?\n/)) {
      if (/^\s*#/.test(line) || !/\bpip3?\s+install\b/.test(line)) continue;
      seen += 1;
      if (!/\bpip3?\s+install\s+-r\s+crawler\/requirements\.txt\s*$/.test(line)) offenders.push(`${name}: ${line.trim()}`);
    }
  }
  assert.ok(seen >= 10, `只扫到 ${seen} 处 pip install，扫描口径坏了`);
  assert.deepEqual(offenders, []);
});
