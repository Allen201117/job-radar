const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const { relativeTimeLabel, formatDateLabel } = loadTs(path.join(__dirname, "..", "lib", "relative-time.ts"));
const now = new Date("2026-07-13T12:00:00.000Z");

test("relativeTimeLabel handles same-day and recent day boundaries", () => {
  assert.equal(relativeTimeLabel("2026-07-13T00:00:00.000Z", now), "今天");
  assert.equal(relativeTimeLabel("2026-07-12T12:00:00.000Z", now), "昨天");
  assert.equal(relativeTimeLabel("2026-07-07T12:00:00.000Z", now), "6天前");
});

test("relativeTimeLabel handles week, month, and year boundaries", () => {
  assert.equal(relativeTimeLabel("2026-07-06T12:00:00.000Z", now), "1周前");
  assert.equal(relativeTimeLabel("2026-06-14T12:00:00.000Z", now), "4周前");
  assert.equal(relativeTimeLabel("2026-06-13T12:00:00.000Z", now), "1个月前");
  assert.equal(relativeTimeLabel("2025-07-14T12:00:00.000Z", now), "12个月前");
  assert.equal(relativeTimeLabel("2025-07-13T12:00:00.000Z", now), "1年前");
});

test("relativeTimeLabel handles future, empty, and invalid input", () => {
  assert.equal(relativeTimeLabel("2026-07-14T12:00:00.000Z", now), "今天");
  assert.equal(relativeTimeLabel(null, now), null);
  assert.equal(relativeTimeLabel("not a date", now), null);
});

// —— 绝对日期文案：必须与运行时时区无关 ——
// 回归 React #418：Vercel 函数跑 UTC、浏览器跑用户本地时区（国内 UTC+8），
// 裸 toLocaleDateString 会让 SSR 与 hydration 差一天 → /today /jobs /campus 每次加载必现水合报错。
const TZ_SENSITIVE_ISO = "2026-08-30T18:00:00.000Z"; // UTC 是 8/30，北京时间已是 8/31

function underTz(tz, fn) {
  const prev = process.env.TZ;
  process.env.TZ = tz;
  try {
    return fn();
  } finally {
    if (prev === undefined) delete process.env.TZ;
    else process.env.TZ = prev;
  }
}

test("formatDateLabel 在任何运行时时区下都输出同一个北京时间日期", () => {
  const expected = "2026/8/31";
  for (const tz of ["UTC", "Asia/Shanghai", "America/New_York"]) {
    assert.equal(underTz(tz, () => formatDateLabel(TZ_SENSITIVE_ISO)), expected, `TZ=${tz}`);
  }
});

test("formatDateLabel 处理空值与非法输入", () => {
  assert.equal(formatDateLabel(null), null);
  assert.equal(formatDateLabel(undefined), null);
  assert.equal(formatDateLabel(""), null);
  assert.equal(formatDateLabel("not a date"), null);
});

test("formatDateLabel 接受 Date 对象、可选毫秒时间戳", () => {
  assert.equal(formatDateLabel(new Date(TZ_SENSITIVE_ISO)), "2026/8/31");
  assert.equal(formatDateLabel(Date.parse(TZ_SENSITIVE_ISO)), "2026/8/31");
});

test("formatDateLabel 传 Intl 选项时仍钉死北京时间", () => {
  for (const tz of ["UTC", "Asia/Shanghai", "America/New_York"]) {
    assert.equal(
      underTz(tz, () => formatDateLabel(TZ_SENSITIVE_ISO, { month: "long", day: "numeric" })),
      "8月31日",
      `TZ=${tz}`,
    );
  }
});
