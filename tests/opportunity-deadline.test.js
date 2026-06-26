// 截止解析（04 spec §6.1 / 05 §6.2）：各格式 + 无法解析不触发 + 推年 + 多日期不判。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { parseDeadline } = loadOpp("deadline");
const NOW = new Date("2026-06-28T00:00:00Z");

test("YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYY年M月D日 → high", () => {
  for (const raw of ["2026-07-01", "2026/7/1", "2026.7.1", "2026年7月1日"]) {
    const r = parseDeadline(raw, NOW);
    assert.ok(r, `${raw} 应解析`);
    assert.equal(r.date, "2026-07-01");
    assert.equal(r.confidence, "high");
  }
});

test("M月D日（无年）按 now 推年 → medium；已过 30 天推下一年", () => {
  const future = parseDeadline("7月1日", NOW); // now=6/28 → 今年7/1
  assert.equal(future.date, "2026-07-01");
  assert.equal(future.confidence, "medium");
  const past = parseDeadline("1月5日", NOW); // 已过 30 天 → 明年
  assert.equal(past.date, "2027-01-05");
});

test("含糊词不解析：长期有效 / 招满即止 / 尽快", () => {
  for (const raw of ["长期有效", "招满即止", "尽快投递", "长期招聘中"]) {
    assert.equal(parseDeadline(raw, NOW), null);
  }
});

test("空 / null / 非日期 → null", () => {
  assert.equal(parseDeadline(null, NOW), null);
  assert.equal(parseDeadline("", NOW), null);
  assert.equal(parseDeadline("详见官网", NOW), null);
});

test("非法日历日（2 月 30 日）→ null", () => {
  assert.equal(parseDeadline("2026-02-30", NOW), null);
});

test("多个不同日期 → 无法判断，返回 null", () => {
  assert.equal(parseDeadline("2026-07-01 至 2026-08-01", NOW), null);
});

test("同一日期重复出现 → 仍可解析（唯一日期）", () => {
  const r = parseDeadline("截止 2026-07-01（2026-07-01 前）", NOW);
  assert.equal(r.date, "2026-07-01");
});
