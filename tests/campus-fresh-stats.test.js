const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { aggregateCampusFreshStats } = loadTs(
  path.join(__dirname, "..", "lib", "campus-stats.ts"),
);

// getCampusFreshStats 的折叠逻辑：绕开可能冻住的重快照、用轻查询现算「计数 + 新鲜度」。
// 归属规则必须与 getCampusZone / getCampusCompanyJobs / 分面计数一致，这里把它钉死。

test("按 pattern 归属并累加 campus/intern 计数、取最新 last_seen", () => {
  const list = [
    { name: "字节跳动", pattern: "%字节%" },
    { name: "腾讯", pattern: "%腾讯%" },
  ];
  const rows = [
    { company: "字节跳动", campus_total: 100, intern_total: 20, last_seen: "2026-09-15T00:00:00Z" },
    { company: "字节跳动（深圳）", campus_total: 5, intern_total: 1, last_seen: "2026-09-14T00:00:00Z" },
    { company: "腾讯科技", campus_total: 40, intern_total: 10, last_seen: "2026-09-13T00:00:00Z" },
  ];
  const out = aggregateCampusFreshStats(rows, list);
  assert.equal(out.get("%字节%").campusTotal, 105);
  assert.equal(out.get("%字节%").internTotal, 21);
  // 取最新一条（09-15 而非 09-14）
  assert.equal(out.get("%字节%").lastSeenAtMs, Date.parse("2026-09-15T00:00:00Z"));
  assert.equal(out.get("%腾讯%").campusTotal, 40);
});

test("第一个命中的 pattern 得（%腾讯音乐% 必须排在 %腾讯% 前）", () => {
  const list = [
    { name: "腾讯音乐 TME", pattern: "%腾讯音乐%" },
    { name: "腾讯", pattern: "%腾讯%" },
  ];
  const rows = [
    { company: "腾讯音乐娱乐科技", campus_total: 7, intern_total: 0, last_seen: null },
    { company: "腾讯科技", campus_total: 3, intern_total: 0, last_seen: null },
  ];
  const out = aggregateCampusFreshStats(rows, list);
  assert.equal(out.get("%腾讯音乐%").campusTotal, 7, "腾讯音乐 归 %腾讯音乐%");
  assert.equal(out.get("%腾讯%").campusTotal, 3, "腾讯科技 归 %腾讯%，不被音乐吞掉");
});

test("清单里每个 pattern 都有条目，没抓到就是 0 / null（不缺键）", () => {
  const list = [{ name: "空公司", pattern: "%空公司%" }];
  const out = aggregateCampusFreshStats([], list);
  assert.deepEqual(out.get("%空公司%"), { campusTotal: 0, internTotal: 0, lastSeenAtMs: null });
});

test("字符串型计数与空 company 不炸", () => {
  const list = [{ name: "美团", pattern: "%美团%" }];
  const rows = [
    { company: "美团", campus_total: "12", intern_total: "3", last_seen: "2026-09-15T00:00:00Z" },
    { company: null, campus_total: 999, intern_total: 999, last_seen: "2026-09-15T00:00:00Z" },
    { company: "无关公司", campus_total: 5, intern_total: 5, last_seen: null },
  ];
  const out = aggregateCampusFreshStats(rows, list);
  assert.equal(out.get("%美团%").campusTotal, 12);
  assert.equal(out.get("%美团%").internTotal, 3);
});
