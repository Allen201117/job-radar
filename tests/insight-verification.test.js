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

test("grade 门: experience 样本达标（>=5）即过，publisher 数量不再是硬要求", () => {
  const twoPub = [
    makeSource({ id: "a", publisher: "脉脉聚合" }),
    makeSource({ id: "b", publisher: "职友集" }),
  ];
  // sample_size>=5 → 过门
  assert.equal(
    V.passesGradeGate({ grade: "experience", sample_size: 6 }, twoPub),
    true,
  );
  // sample_size>=5，即使只有 1 个注册域名来源也过（sample_size 满足）
  assert.equal(
    V.passesGradeGate({ grade: "experience", sample_size: 9 }, [
      makeSource({ id: "a", url: "https://www.zhihu.com/a/1" }),
      makeSource({ id: "b", url: "https://zhuanlan.zhihu.com/p/2" }),
    ]),
    true,
  );
  // 样本不足且无 confidence → 不过门
  assert.equal(
    V.passesGradeGate({ grade: "experience", sample_size: 3 }, twoPub),
    false,
  );
});

test("grade 门: experience 备用路径：sample_size=null + 2 不同注册域 + confidence>=0.8 → 过", () => {
  const twoDomains = [
    makeSource({ id: "a", url: "https://maimai.cn/article/123" }),
    makeSource({ id: "b", url: "https://www.zhihu.com/answer/456" }),
  ];
  // ① sample_size=null，2 个不同注册域，confidence=0.9 → 过门
  assert.equal(
    V.passesGradeGate(
      { grade: "experience", sample_size: null, payload: { confidence: 0.9 } },
      twoDomains,
    ),
    true,
    "2 不同域 + confidence 0.9 应过门",
  );
  // ② 两个来源同为 zhihu.com 子域 → 只算 1 个 publisher → 不过门
  const sameZhihu = [
    makeSource({ id: "a", url: "https://www.zhihu.com/answer/1" }),
    makeSource({ id: "b", url: "https://zhuanlan.zhihu.com/p/2" }),
  ];
  assert.equal(
    V.passesGradeGate(
      { grade: "experience", sample_size: null, payload: { confidence: 0.9 } },
      sameZhihu,
    ),
    false,
    "同 zhihu.com 子域算 1 publisher，不足 2 → 不过门",
  );
  // ③ confidence 不足 0.8 → 不过门
  assert.equal(
    V.passesGradeGate(
      { grade: "experience", sample_size: null, payload: { confidence: 0.7 } },
      twoDomains,
    ),
    false,
    "confidence 0.7 < 0.8 → 不过门",
  );
});

test("registrableHost 取注册域名（去子域，国家二级域取三段）", () => {
  assert.equal(V.registrableHost("https://www.zhihu.com/article/1"), "zhihu.com");
  assert.equal(V.registrableHost("https://zhuanlan.zhihu.com/p/2"), "zhihu.com");
  assert.equal(V.registrableHost("https://maimai.cn/feed"), "maimai.cn");
  assert.equal(V.registrableHost("https://m.baidu.com.cn/s?q=1"), "baidu.com.cn");
  assert.equal(V.registrableHost("https://www.example.co.uk/page"), "example.co.uk");
  assert.equal(V.registrableHost("https://example.com/path"), "example.com");
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

test("passesGradeGate: 备用路径优先读 verification.confidence（爬虫真正写入的列）", () => {
  const sources = [
    { url: "https://www.zhihu.com/question/1", deidentified: true },
    { url: "https://www.nowcoder.com/discuss/2", deidentified: true },
  ];
  const item = { grade: "experience", sample_size: null, payload: {}, verification: { verdict: "entailment", confidence: 0.9 } };
  assert.equal(V.passesGradeGate(item, sources), true);
  const low = { ...item, verification: { verdict: "entailment", confidence: 0.7 } };
  assert.equal(V.passesGradeGate(low, sources), false);
});

// ============================================================
// v3 新增测试：绝对化措辞禁用词 + assertion 门
// ============================================================

test("containsBannedAssertion: v3 新增禁用词命中", () => {
  // 绝对化措辞应被拦截
  assert.equal(V.containsBannedAssertion("这家公司一定很轻松"), true, "一定（非量化）应命中");
  assert.equal(V.containsBannedAssertion("结果必然如此"), true, "必然应命中");
  assert.equal(V.containsBannedAssertion("这是最好的选择"), true, "最好应命中");
  assert.equal(V.containsBannedAssertion("薪资最差"), true, "最差应命中");
  assert.equal(V.containsBannedAssertion("所有人都是认可的"), true, "都是应命中");
  assert.equal(V.containsBannedAssertion("肯定有年终奖"), true, "肯定应命中");
});

test("containsBannedAssertion: 「一定程度」合法用法不被拦截", () => {
  assert.equal(
    V.containsBannedAssertion("据公开报道，一定程度上反映了整体文化。"),
    false,
    "「一定程度」不应命中",
  );
  assert.equal(
    V.containsBannedAssertion("一定数量的岗位集中在研发方向。"),
    false,
    "「一定数量」不应命中",
  );
});

test("passesClaimGate: 有时间窗 + ≥2 来源域名 → 过门", () => {
  const item = { time_window: "2025", valid_from: null, valid_until: null };
  const sources = [
    makeSource({ id: "a", url: "https://www.zhihu.com/q/1" }),
    makeSource({ id: "b", url: "https://www.nowcoder.com/d/2" }),
  ];
  assert.equal(V.passesClaimGate(item, sources), true);
});

test("passesClaimGate: 缺时间窗 → 不过门", () => {
  const item = { time_window: null, valid_from: null, valid_until: null };
  const sources = [
    makeSource({ id: "a", url: "https://www.zhihu.com/q/1" }),
    makeSource({ id: "b", url: "https://www.nowcoder.com/d/2" }),
  ];
  assert.equal(V.passesClaimGate(item, sources), false);
});

test("passesClaimGate: 只有 1 个注册域名 → 不过门", () => {
  const item = { time_window: "2025", valid_from: null, valid_until: null };
  const sources = [
    makeSource({ id: "a", url: "https://www.zhihu.com/q/1" }),
    makeSource({ id: "b", url: "https://zhuanlan.zhihu.com/p/2" }), // 同一注册域
  ];
  assert.equal(V.passesClaimGate(item, sources), false);
});

test("resolveEffectiveAssertion: fact + public_web 来源 → 降级为 claim", () => {
  const sources = [
    { ...makeSource(), source_kind: "public_web", deidentified: true },
  ];
  assert.equal(V.resolveEffectiveAssertion("fact", sources), "claim");
});

test("resolveEffectiveAssertion: fact + official_filing 来源 → 保持 fact", () => {
  const sources = [
    { ...makeSource(), source_kind: "official_filing", deidentified: true },
  ];
  assert.equal(V.resolveEffectiveAssertion("fact", sources), "fact");
});

test("resolveEffectiveAssertion: null assertion → 返回 null（由调用方回落 grade）", () => {
  assert.equal(V.resolveEffectiveAssertion(null, [makeSource()]), null);
  assert.equal(V.resolveEffectiveAssertion(undefined, [makeSource()]), null);
});

test("resolveEffectiveAssertion: signal / claim assertion → 原样返回", () => {
  assert.equal(V.resolveEffectiveAssertion("signal", []), "signal");
  assert.equal(V.resolveEffectiveAssertion("claim", [makeSource()]), "claim");
});

test("evaluateInsight: assertion=claim 但缺时间窗 → 不展示", () => {
  const item = makeItem({
    assertion: "claim",
    grade: "experience",
    time_window: null,
    valid_until: null,
    valid_from: null,
    sample_size: 10,
  });
  const sources = [
    makeSource({ id: "a", url: "https://www.zhihu.com/q/1" }),
    makeSource({ id: "b", url: "https://www.nowcoder.com/d/2" }),
  ];
  const ev = V.evaluateInsight(item, sources, NOW);
  assert.equal(ev.displayable, false);
  assert.equal(ev.failure_reason, "insight_unverified");
});

test("evaluateInsight: assertion=claim 且只有 1 域名来源 → 不展示", () => {
  const item = makeItem({
    assertion: "claim",
    grade: "experience",
    time_window: "2025",
    sample_size: 10,
  });
  const sources = [
    makeSource({ id: "a", url: "https://www.zhihu.com/q/1" }),
    makeSource({ id: "b", url: "https://zhuanlan.zhihu.com/p/2" }), // 同域
  ];
  const ev = V.evaluateInsight(item, sources, NOW);
  assert.equal(ev.displayable, false);
});

test("evaluateInsight: assertion=claim 满足条件 → 展示", () => {
  const item = makeItem({
    assertion: "claim",
    grade: "experience",
    time_window: "2025",
    sample_size: 10,
  });
  const sources = [
    makeSource({ id: "a", url: "https://www.zhihu.com/q/1" }),
    makeSource({ id: "b", url: "https://www.nowcoder.com/d/2" }),
  ];
  const ev = V.evaluateInsight(item, sources, NOW);
  assert.equal(ev.displayable, true);
});

test("evaluateInsight: assertion=signal → 不受 claim 门限制（signal 无需来源）", () => {
  const item = makeItem({
    assertion: "signal",
    grade: "fact",
    time_window: "截至 2026-09",
    sample_size: 50,
  });
  // signal 类：无来源也可展示（来自自有岗位库，非外部来源）
  const ev = V.evaluateInsight(item, [], NOW);
  // grade=fact 需 >=1 有效来源，但 assertion=signal 的派生条目 grade 也是 fact
  // 派生条目在 derived=true 时跳过来源门（此处测 non-derived 存储型 signal）
  // → 如果 passesGradeGate(fact, []) = false，evaluateInsight 应在 grade 门拦住
  // 确认当前行为：grade=fact 无来源 → insight_unverified（此为预期行为）
  assert.equal(ev.failure_reason, "insight_unverified");
});

// ============================================================
// v3 P0-3：第一方派生 signal 的展示门
// ============================================================

function makeSignal(over = {}) {
  return makeItem({
    dimension: "hiring",
    grade: "fact",
    origin: "derived",
    assertion: "signal",
    content: "近 30 天新挂出并仍在招的岗位 47 个（基于 320 个在招岗）。",
    sample_size: 320,
    time_window: "截至 2026-06-02 的在招岗位",
    ...over,
  });
}

test("signal 门: 第一方派生无需外部来源即可展示（grade 门会把它误杀）", () => {
  // 这正是必须单开一条门的理由：signal 的来源是我们自己的岗位库，没有外部 URL 可挂。
  assert.equal(V.passesGradeGate({ grade: "fact" }, []), false);
  assert.equal(V.evaluateInsight(makeSignal(), [], NOW).displayable, true);
});

test("signal 门: assertion 是声明、origin 是事实——origin 不是 derived 一律不放行", () => {
  assert.equal(V.passesSignalGate({ origin: "derived", sample_size: 20 }), true);
  // 光把 assertion 填成 signal 就想绕过来源要求 → 拒绝
  assert.equal(V.passesSignalGate({ origin: "public_web", sample_size: 999 }), false);
  assert.equal(V.passesSignalGate({ origin: null, sample_size: 999 }), false);
  assert.equal(
    V.evaluateInsight(makeSignal({ origin: "public_web" }), [], NOW).displayable,
    false,
  );
});

test("signal 门: 样本量不足不展示（不给小样本数字）", () => {
  assert.equal(V.passesSignalGate({ origin: "derived", sample_size: 9 }), false);
  assert.equal(V.passesSignalGate({ origin: "derived", sample_size: 10 }), true);
  assert.equal(V.passesSignalGate({ origin: "derived", sample_size: null }), false);
  assert.equal(
    V.evaluateInsight(makeSignal({ sample_size: 3 }), [], NOW).displayable,
    false,
  );
});

test("signal 门: 绝对化措辞仍然拦（signal 不是免检通道）", () => {
  assert.equal(
    V.evaluateInsight(makeSignal({ content: "这条业务线必然在扩张。" }), [], NOW).displayable,
    false,
  );
});

test("signal 门: 过期的派生条目标记为 outdated（派生链停跑即自动止损）", () => {
  const ev = V.evaluateInsight(
    makeSignal({ valid_until: "2026-05-01" }),
    [],
    NOW,
  );
  assert.equal(ev.displayable, true);
  assert.equal(ev.outdated, true);
});

test("ITEM_COLUMNS 必须带 origin，否则 signal 门永远走不到", () => {
  const bundle = fs.readFileSync(
    path.join(__dirname, "..", "lib", "insight-bundle.ts"),
    "utf8",
  );
  const columns = bundle.match(/ITEM_COLUMNS\s*=\s*\n?\s*"([^"]+)"/);
  assert.ok(columns, "找不到 ITEM_COLUMNS");
  const list = columns[1].split(",").map((c) => c.trim());
  for (const col of ["origin", "assertion", "subject_id", "metric_key", "sample_size"]) {
    assert.ok(list.includes(col), `ITEM_COLUMNS 缺列 ${col}`);
  }
});
