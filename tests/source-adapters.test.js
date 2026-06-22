const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const compiled = ts.transpileModule(fs.readFileSync(sourcePath, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    module.exports,
    require,
    module,
    sourcePath,
    path.dirname(sourcePath),
  );
  return module.exports;
}

const S = loadTsModule(path.join("lib", "source-adapters.ts"));

test("adapter 白名单覆盖 crawler ADAPTERS 全部值（含通用 ATS）", () => {
  for (const v of [
    "apple", "apple_cn", "baidu", "jd", "haier", "siemens", "tencent",
    "bytedance", "bytedance_campus", "nio_feishu", "xpeng_feishu", "horizon_feishu",
    "xiaomi_feishu", "greenhouse", "lever", "ashby", "smartrecruiters", "workday",
    "moka", "beisen", "company_spa", "feishu", "hotjob", "eightfold", "oracle", "amazon", "phenom", "microsoft", "google",
  ]) {
    assert.equal(S.isValidAdapter(v), true, `${v} 应在白名单`);
  }
  assert.equal(S.isValidAdapter("不存在的adapter"), false);
  assert.equal(S.isValidAdapter(""), false);
  assert.equal(S.isValidAdapter(null), false);
});

test("crawl_method 仅接受 http / playwright / manual", () => {
  assert.equal(S.isValidCrawlMethod("http"), true);
  assert.equal(S.isValidCrawlMethod("playwright"), true);
  assert.equal(S.isValidCrawlMethod("manual"), true);
  assert.equal(S.isValidCrawlMethod("selenium"), false);
});

test("validateSourceInput: 合法输入归一化通过", () => {
  const r = S.validateSourceInput({
    company: "  Stripe ",
    source_url: "https://boards.greenhouse.io/stripe",
    adapter_name: "greenhouse",
    crawl_method: "http",
    notes: "  外企 ATS  ",
    enabled: true,
  });
  assert.equal(r.ok, true);
  assert.deepEqual(r.value, {
    company: "Stripe",
    source_url: "https://boards.greenhouse.io/stripe",
    adapter_name: "greenhouse",
    crawl_method: "http",
    notes: "外企 ATS",
    enabled: true,
  });
});

test("validateSourceInput: 缺公司 / 非法地址 / 非法 adapter 报错", () => {
  const r = S.validateSourceInput({
    company: "",
    source_url: "boards.greenhouse.io/x",
    adapter_name: "nope",
    crawl_method: "http",
  });
  assert.equal(r.ok, false);
  assert.ok(r.errors.company);
  assert.ok(r.errors.source_url); // 缺 http 前缀
  assert.ok(r.errors.adapter_name);
});

test("validateSourceInput: enabled 默认 true，显式 false 保留；notes 空转 null", () => {
  const r = S.validateSourceInput({
    company: "Acme",
    source_url: "http://acme.example/jobs",
    adapter_name: "lever",
    crawl_method: "manual",
    enabled: false,
  });
  assert.equal(r.ok, true);
  assert.equal(r.value.enabled, false);
  assert.equal(r.value.notes, null);

  const r2 = S.validateSourceInput({
    company: "Acme",
    source_url: "http://acme.example/jobs",
    adapter_name: "lever",
  });
  assert.equal(r2.value.enabled, true); // 默认启用
  assert.equal(r2.value.crawl_method, "http"); // 默认 http
});

test("每个 adapter 必标 origin（外企/本土），FOREIGN_ATS_ADAPTERS 由此自动派生", () => {
  for (const a of S.SOURCE_ADAPTERS) {
    assert.ok(
      a.origin === "foreign" || a.origin === "domestic",
      `${a.value} 缺少合法 origin（foreign/domestic）`,
    );
  }
  // 外企判定名单 = 标 foreign 的 adapter 自动派生；与已知外企集合比对，改 origin 标注 → 此处需同步（drift 可见）。
  assert.deepEqual(
    [...S.FOREIGN_ATS_ADAPTERS].sort(),
    [
      "amazon", "apple", "apple_cn", "ashby", "eightfold", "google", "greenhouse",
      "lever", "microsoft", "oracle", "phenom", "siemens", "smartrecruiters", "workday",
    ].sort(),
  );
  assert.equal(S.isForeignAtsAdapter("greenhouse"), true);
  assert.equal(S.isForeignAtsAdapter("moka"), false);
  assert.equal(S.isForeignAtsAdapter(null), false);
});
