const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relPath) {
  const sourcePath = path.join(__dirname, "..", relPath);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;
  const module = { exports: {} };
  const fn = new Function(
    "exports",
    "require",
    "module",
    "__filename",
    "__dirname",
    compiled,
  );
  fn(module.exports, require, module, sourcePath, path.dirname(sourcePath));
  return module.exports;
}

const V = loadTsModule(path.join("lib", "insight-verification.ts"));

const NOW = new Date("2026-06-02T00:00:00.000Z");

function makeSource(over = {}) {
  return {
    id: "s-1",
    url: "https://example.com/filing",
    publisher: "公开财报",
    source_kind: "official_filing",
    excerpt: null,
    collected_at: "2026-05-01T00:00:00.000Z",
    deidentified: true,
    created_at: "2026-05-01T00:00:00.000Z",
    ...over,
  };
}

function makeItem(over = {}) {
  return {
    id: "i-1",
    company_id: "c-1",
    dimension: "timing",
    grade: "fact",
    title: "财年与 HC 节奏",
    content: "根据公开财报，财年于 6 月底结束。",
    sample_size: null,
    payload: {},
    time_window: "每年 5–7 月",
    valid_from: null,
    valid_until: null,
    last_verified_at: "2026-05-01T00:00:00.000Z",
    deidentified: true,
    status: "active",
    created_at: "2026-05-01T00:00:00.000Z",
    updated_at: "2026-05-01T00:00:00.000Z",
    ...over,
  };
}

test("grade 门: fact 需 >=1 有效来源", () => {
  assert.equal(V.passesGradeGate({ grade: "fact" }, [makeSource()]), true);
  assert.equal(V.passesGradeGate({ grade: "fact" }, []), false);
  // 来源未去标识不算有效
  assert.equal(
    V.passesGradeGate({ grade: "fact" }, [makeSource({ deidentified: false })]),
    false,
  );
});

test("grade 门: experience 需样本达标且 >=2 个不同 publisher", () => {
  const twoPub = [
    makeSource({ id: "a", publisher: "脉脉聚合" }),
    makeSource({ id: "b", publisher: "职友集" }),
  ];
  assert.equal(
    V.passesGradeGate({ grade: "experience", sample_size: 6 }, twoPub),
    true,
  );
  // 样本不足
  assert.equal(
    V.passesGradeGate({ grade: "experience", sample_size: 3 }, twoPub),
    false,
  );
  // 仅 1 个 publisher
  assert.equal(
    V.passesGradeGate({ grade: "experience", sample_size: 9 }, [
      makeSource({ id: "a", publisher: "脉脉聚合" }),
      makeSource({ id: "b", publisher: "脉脉聚合" }),
    ]),
    false,
  );
});

test("grade 门: rumor 永远拦截", () => {
  assert.equal(V.passesGradeGate({ grade: "rumor", sample_size: 100 }, [
    makeSource({ id: "a", publisher: "x" }),
    makeSource({ id: "b", publisher: "y" }),
  ]), false);
});

test("去标识门: item 或任一来源未去标识则失败", () => {
  assert.equal(V.passesDeidentifiedGate({ deidentified: true }, [makeSource()]), true);
  assert.equal(V.passesDeidentifiedGate({ deidentified: false }, [makeSource()]), false);
  assert.equal(
    V.passesDeidentifiedGate({ deidentified: true }, [makeSource({ deidentified: false })]),
    false,
  );
});

test("时效门: time_window 或 valid_* 至少其一", () => {
  assert.equal(V.hasTimeWindow({ time_window: "每年 5–7 月" }), true);
  assert.equal(V.hasTimeWindow({ valid_until: "2026-12-31" }), true);
  assert.equal(V.hasTimeWindow({ time_window: "  ", valid_from: null, valid_until: null }), false);
});

test("过时判定: valid_until 过当日为过时；time_window-only 不过时", () => {
  assert.equal(V.isOutdated({ valid_until: "2026-05-01" }, NOW), true);
  assert.equal(V.isOutdated({ valid_until: "2026-12-31" }, NOW), false);
  assert.equal(V.isOutdated({ valid_until: null }, NOW), false);
});

test("归因 lint: 产品断言被拦截", () => {
  assert.equal(
    V.passesAssertionLint({ grade: "fact", content: "我们认定该公司最累。" }),
    false,
  );
  assert.equal(
    V.passesAssertionLint({ grade: "fact", content: "根据公开财报，财年 6 月底结束。" }),
    true,
  );
});

test("归因 lint: experience 必须带归因口径", () => {
  assert.equal(
    V.passesAssertionLint({ grade: "experience", content: "工作强度很大。" }),
    false,
  );
  assert.equal(
    V.passesAssertionLint({
      grade: "experience",
      content: "据 12 位从业者反馈，工作强度偏大。",
    }),
    true,
  );
});

test("evaluateInsight: 全门通过 → 可展示且不过时", () => {
  const ev = V.evaluateInsight(makeItem(), [makeSource()], NOW);
  assert.equal(ev.displayable, true);
  assert.equal(ev.outdated, false);
  assert.equal(ev.failure_reason, null);
});

test("evaluateInsight: valid_until 过期 → 可展示但标过时", () => {
  const ev = V.evaluateInsight(
    makeItem({ time_window: null, valid_until: "2026-05-01" }),
    [makeSource()],
    NOW,
  );
  assert.equal(ev.displayable, true);
  assert.equal(ev.outdated, true);
  assert.equal(ev.failure_reason, "insight_outdated");
});

test("evaluateInsight: 非 active / 未过门 → 不可展示", () => {
  assert.equal(
    V.evaluateInsight(makeItem({ status: "retired" }), [makeSource()], NOW).displayable,
    false,
  );
  assert.equal(
    V.evaluateInsight(makeItem({ grade: "fact" }), [], NOW).failure_reason,
    "insight_unverified",
  );
});

test("resolveInsightFailure: bundle 级决策", () => {
  assert.equal(V.resolveInsightFailure([]), "insight_unverified");
  assert.equal(
    V.resolveInsightFailure([{ displayable: false, outdated: false, failure_reason: "insight_unverified" }]),
    "insight_unverified",
  );
  assert.equal(
    V.resolveInsightFailure([{ displayable: true, outdated: true, failure_reason: "insight_outdated" }]),
    "insight_outdated",
  );
  assert.equal(
    V.resolveInsightFailure([
      { displayable: true, outdated: true, failure_reason: "insight_outdated" },
      { displayable: true, outdated: false, failure_reason: null },
    ]),
    null,
  );
});

test("freshnessFromVerifiedAt: 按核实时间相对分级（任务 4.2）", () => {
  assert.equal(V.freshnessFromVerifiedAt("2026-05-01T00:00:00.000Z", NOW).level, "fresh"); // ~32 天
  assert.equal(V.freshnessFromVerifiedAt("2026-01-01T00:00:00.000Z", NOW).level, "recent"); // ~153 天
  assert.equal(V.freshnessFromVerifiedAt("2025-06-01T00:00:00.000Z", NOW).level, "aging"); // ~366 天
  assert.equal(V.freshnessFromVerifiedAt("2024-06-01T00:00:00.000Z", NOW).level, "stale"); // ~731 天
  assert.equal(V.freshnessFromVerifiedAt("2026-05-01T00:00:00.000Z", NOW).text, "近期核实");
  assert.equal(V.freshnessFromVerifiedAt(null, NOW), null);
  assert.equal(V.freshnessFromVerifiedAt("not-a-date", NOW), null);
});
