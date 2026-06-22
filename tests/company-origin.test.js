const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const ts = require("typescript");
const { loadTsModule } = require("./route-test-utils");
const { isDomesticAdapter } = require("../lib/domestic-adapters");

// company-origin.ts 现在 import 了 source-adapters.ts（.ts 依赖）。node --test 每个测试文件独立进程，
// 这里注册一个仅作用于本进程的 .ts require 钩子，让 loadTsModule 能解析 .ts → .ts 依赖链。
if (!require.extensions[".ts"]) {
  require.extensions[".ts"] = (module, filename) => {
    const out = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
        esModuleInterop: true,
      },
    }).outputText;
    module._compile(out, filename);
  };
}

const { classifyCompanyOrigin, classifyCompanyOriginWithSource } =
  loadTsModule("lib/company-origin.ts");
const { isForeignAtsAdapter } = loadTsModule("lib/source-adapters.ts");

test("classifyCompanyOrigin: 名单内精确命中具体国别", () => {
  assert.equal(classifyCompanyOrigin("字节跳动"), "中国");
  assert.equal(classifyCompanyOrigin("Apple"), "美企");
  assert.equal(classifyCompanyOrigin("Siemens"), "德企");
  assert.equal(classifyCompanyOrigin("Sony"), "日企");
});

test("classifyCompanyOrigin: 名单外 / 空 → 其它", () => {
  assert.equal(classifyCompanyOrigin("上汽集团"), "其它");
  assert.equal(classifyCompanyOrigin(""), "其它");
  assert.equal(classifyCompanyOrigin(null), "其它");
});

// 核心 bug 修复：库里绝大多数中国公司不在 50 家死名单内 → 旧逻辑判「其它」→「外企」筛选放行 → 混入中国公司。
// 新判定：名单外的非外企源公司一律默认「中国」，「外企」筛选才能正确踢掉它们（含名单/本土名单都没收录的）。
test("classifyCompanyOriginWithSource: 名单外的本土公司 → 中国（修复外企筛选漏网）", () => {
  assert.equal(classifyCompanyOriginWithSource("上汽集团", "moka"), "中国");
  assert.equal(classifyCompanyOriginWithSource("广汽埃安", "beisen"), "中国");
  // 关键：这些本土大厂 adapter 不在任何「本土名单」里，但因不是外企源 → 默认中国（治本名单不全的漏判）
  assert.equal(classifyCompanyOriginWithSource("哔哩哔哩", "bilibili"), "中国");
  assert.equal(classifyCompanyOriginWithSource("拼多多", "pinduoduo"), "中国");
  assert.equal(classifyCompanyOriginWithSource("顺丰", "sf_express"), "中国");
});

test("classifyCompanyOriginWithSource: 外企 ATS / 自建源的公司 → 外企（名单未细分国别时）", () => {
  assert.equal(classifyCompanyOriginWithSource("Acme Robotics", "greenhouse"), "外企");
  assert.equal(classifyCompanyOriginWithSource("Globex", "workday"), "外企");
  assert.equal(classifyCompanyOriginWithSource("Initech", "lever"), "外企");
  assert.equal(classifyCompanyOriginWithSource("Foo Corp", "amazon"), "外企");
});

test("classifyCompanyOriginWithSource: 名单优先于来源（细分国别不被来源覆盖）", () => {
  assert.equal(classifyCompanyOriginWithSource("Apple", "moka"), "美企"); // 名单赢
  // 中国公司的海外岗即便走 greenhouse，名单仍判中国，不被外企源覆盖
  assert.equal(classifyCompanyOriginWithSource("字节跳动", "greenhouse"), "中国");
});

test("classifyCompanyOriginWithSource: 来源未知/缺失时，未识别公司默认中国（库以本土为主）", () => {
  assert.equal(classifyCompanyOriginWithSource("某不知名公司", null), "中国");
  assert.equal(classifyCompanyOriginWithSource("某不知名公司", undefined), "中国");
  assert.equal(classifyCompanyOriginWithSource("某本土大厂", "meituan"), "中国"); // meituan 非外企源 → 中国
  assert.equal(classifyCompanyOriginWithSource("字节跳动", undefined), "中国"); // 名单
});

test("isForeignAtsAdapter / isDomesticAdapter 判定", () => {
  assert.equal(isForeignAtsAdapter("greenhouse"), true);
  assert.equal(isForeignAtsAdapter("workday"), true);
  assert.equal(isForeignAtsAdapter("google"), true);
  assert.equal(isForeignAtsAdapter("moka"), false);
  assert.equal(isForeignAtsAdapter("meituan"), false);
  assert.equal(isForeignAtsAdapter(null), false);
  assert.equal(isDomesticAdapter("moka"), true);
  assert.equal(isDomesticAdapter("greenhouse"), false);
});
