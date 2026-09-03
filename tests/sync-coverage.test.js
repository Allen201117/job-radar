// sync-coverage 单测：验证 buildCoverageRows 的纯计算逻辑。
// 对应 PR：将 syncCoverage 的 6 次串行 DB 往返压缩到 3 次（并行读 → 并行写 → 权威读），
// 语义不变：stale 行被删、新行被 upsert、状态继承 researching/unsupported。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");

const { loadTs } = require("./_load-ts");
const { buildCoverageRows } = loadTs(path.join(__dirname, "../lib/sync-coverage.ts"));

// --- 辅助数据 ---
const SOURCE_A = { id: "src-a", company: "字节跳动" };  // norm → "字节跳动"
const SOURCE_B = { id: "src-b", company: "Apple" };     // norm → "apple"
const SOURCE_C = { id: "src-c", company: "Apple" };     // 第二个 Apple 源（同 norm）

test("buildCoverageRows: 有 source 覆盖 → status=covered", () => {
  const { rows, staleIds } = buildCoverageRows(
    ["字节跳动"],
    [SOURCE_A],
    [],
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, "covered");
  assert.deepEqual(rows[0].matched_source_ids, ["src-a"]);
  assert.equal(staleIds.length, 0);
});

test("buildCoverageRows: 无 source 覆盖 → status=queued（默认态）", () => {
  const { rows } = buildCoverageRows(["腾讯"], [SOURCE_A], []);
  assert.equal(rows[0].status, "queued");
  assert.deepEqual(rows[0].matched_source_ids, []);
});

test("buildCoverageRows: 继承 researching 状态而非覆盖成 queued", () => {
  const existing = [{ id: "e1", normalized_company: "腾讯", status: "researching" }];
  const { rows } = buildCoverageRows(["腾讯"], [SOURCE_A], existing);
  assert.equal(rows[0].status, "researching");
});

test("buildCoverageRows: 继承 unsupported 状态", () => {
  const existing = [{ id: "e1", normalized_company: "腾讯", status: "unsupported" }];
  const { rows } = buildCoverageRows(["腾讯"], [SOURCE_A], existing);
  assert.equal(rows[0].status, "unsupported");
});

test("buildCoverageRows: covered 优先于 researching（有 source 就 covered）", () => {
  const existing = [{ id: "e1", normalized_company: "字节跳动", status: "researching" }];
  const { rows } = buildCoverageRows(["字节跳动"], [SOURCE_A], existing);
  assert.equal(rows[0].status, "covered");
});

test("buildCoverageRows: 多 source 都匹配同一 company 时全部收集", () => {
  const { rows } = buildCoverageRows(["Apple"], [SOURCE_B, SOURCE_C], []);
  assert.equal(rows[0].matched_source_ids.length, 2);
  assert.ok(rows[0].matched_source_ids.includes("src-b"));
  assert.ok(rows[0].matched_source_ids.includes("src-c"));
});

test("buildCoverageRows: targetCompanies 去重（同 norm 只保留第一个）", () => {
  const { rows } = buildCoverageRows(["Apple", "APPLE", "apple"], [SOURCE_B], []);
  assert.equal(rows.length, 1);
});

test("buildCoverageRows: staleIds = existing 里不再 target 的行", () => {
  const existing = [
    { id: "e-old-1", normalized_company: "旧公司a", status: "queued" },
    { id: "e-old-2", normalized_company: "旧公司b", status: "covered" },
    { id: "e-keep",  normalized_company: "字节跳动", status: "covered" },
  ];
  const { rows, staleIds } = buildCoverageRows(["字节跳动"], [SOURCE_A], existing);
  // 只保留字节跳动，其余两个是 stale
  assert.equal(rows.length, 1);
  assert.equal(staleIds.length, 2);
  assert.ok(staleIds.includes("e-old-1"));
  assert.ok(staleIds.includes("e-old-2"));
  assert.ok(!staleIds.includes("e-keep"));
});

test("buildCoverageRows: targetCompanies 为空时全量清空（所有 existing 均为 stale）", () => {
  const existing = [
    { id: "e1", normalized_company: "字节跳动", status: "covered" },
    { id: "e2", normalized_company: "腾讯", status: "queued" },
  ];
  const { rows, staleIds } = buildCoverageRows([], [SOURCE_A], existing);
  assert.equal(rows.length, 0);
  assert.equal(staleIds.length, 2);
});

test("buildCoverageRows: company 归一化后结果存在 normalized_company 字段", () => {
  const { rows } = buildCoverageRows(["字节跳动 ByteDance"], [SOURCE_A], []);
  // normalizeCompany 会处理，norm 不为空
  assert.ok(rows[0].normalized_company.length > 0);
  // company（原始展示名）原样保留
  assert.equal(rows[0].company, "字节跳动 ByteDance");
});
