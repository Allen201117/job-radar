const assert = require("node:assert/strict");
const test = require("node:test");
const { loadTsModule } = require("./route-test-utils");

const S = loadTsModule("lib/insight-submission.ts");

function validBody(over = {}) {
  return {
    company: "字节跳动",
    dimension: "culture",
    topic: "culture",
    rating: 4,
    content: "我在这个团队感受到节奏较快，但目标拆解清晰，适合喜欢快速迭代的人。",
    payload: {},
    consent: true,
    ...over,
  };
}

function approvedRow(over = {}) {
  return {
    id: "sub-1",
    company: "字节跳动",
    company_id: "company-1",
    user_id: "user-secret",
    dimension: "culture",
    topic: "culture",
    rating: 4,
    content: "团队节奏较快，但反馈直接。",
    payload: {},
    status: "approved",
    moderation: { reviewer_id: "admin-1" },
    employment_verified: false,
    created_at: "2026-07-02T12:30:00.000Z",
    updated_at: "2026-07-02T12:30:00.000Z",
    ...over,
  };
}

test("validateSubmission accepts a consented, deidentified first-party submission", () => {
  const result = S.validateSubmission(validBody());

  assert.equal(result.ok, true);
  assert.equal(result.value.company, "字节跳动");
  assert.equal(result.value.dimension, "culture");
  assert.equal(result.value.topic, "culture");
  assert.equal(result.value.rating, 4);
  assert.equal(result.value.content.length > 0, true);
});

test("validateSubmission requires informed consent", () => {
  const result = S.validateSubmission(validBody({ consent: false }));

  assert.equal(result.ok, false);
  assert.equal(result.error, "consent_required");
});

test("validateSubmission enforces the 200 character content cap", () => {
  const result = S.validateSubmission(validBody({ content: "a".repeat(201) }));

  assert.equal(result.ok, false);
  assert.equal(result.error, "content_too_long");
});

test("validateSubmission rejects direct identifiers", () => {
  const cases = [
    "可以联系我 13812345678 了解细节。",
    "我同事张三去年在这个组。",
    "身份证 110101199001011234 提交过。",
    "面试官 @alice 问了很多项目细节。",
    "我老板张总特别关照新人。", // 姓 + 称谓 = 指认具体个人
    "王姐带我熟悉业务，很耐心。",
    "李经理面试的时候压力很大。",
  ];

  for (const content of cases) {
    const result = S.validateSubmission(validBody({ content }));
    assert.equal(result.ok, false, content);
    assert.equal(result.error, "pii_detected", content);
  }
});

test("validateSubmission allows on-topic experiences that merely mention roles", () => {
  // 这些正是本功能想收集的内容（聊老板/同事/面试/文化），不得误判为 PII。
  const cases = [
    "同事都很nice，氛围融洽，愿意互相补位。",
    "老板画饼比较多，但业务成长确实快。",
    "经理支持我尝试新方向，容错度不错。",
    "导师带得很细致，入职上手很快。",
    "面试官问得比较深入，整体体验还不错。",
    "leader风格开放，鼓励大家充分讨论。",
    "老板周末也会一起加班赶进度。",
    "经理高度重视这块业务的投入。",
  ];

  for (const content of cases) {
    const result = S.validateSubmission(validBody({ content }));
    assert.equal(result.ok, true, content);
  }
});

test("validateSubmission rejects unknown dimensions, topics, and ratings", () => {
  assert.equal(S.validateSubmission(validBody({ dimension: "timing" })).error, "invalid_dimension");
  assert.equal(S.validateSubmission(validBody({ topic: "stock" })).error, "invalid_topic");
  assert.equal(S.validateSubmission(validBody({ rating: 6 })).error, "invalid_rating");
});

test("aggregateFirstParty hides rows until the company reaches the minimum approved count", () => {
  const result = S.aggregateFirstParty([
    approvedRow({ id: "sub-1" }),
    approvedRow({ id: "sub-2" }),
  ], { minCount: 3 });

  assert.equal(result.visible, false);
  assert.equal(result.summary.count, 2);
  assert.deepEqual(result.items, []);
});

test("aggregateFirstParty anonymizes approved rows and summarizes ratings when threshold is met", () => {
  const rows = [
    approvedRow({ id: "sub-1", rating: 5, created_at: "2026-07-02T12:30:00.000Z" }),
    approvedRow({ id: "sub-2", rating: 3, created_at: "2026-06-15T09:00:00.000Z" }),
    approvedRow({ id: "sub-3", status: "pending", rating: 1 }),
  ];

  const result = S.aggregateFirstParty(rows, { minCount: 2 });

  assert.equal(result.visible, true);
  assert.equal(result.summary.count, 2);
  assert.equal(result.summary.average_rating, 4);
  assert.deepEqual(
    result.items.map((item) => item.created_month),
    ["2026-07", "2026-06"],
  );
  assert.equal("user_id" in result.items[0], false);
  assert.equal("moderation" in result.items[0], false);
});

test("isFirstPartyLocked treats any user contribution as unlocked", () => {
  assert.equal(S.isFirstPartyLocked(0), true);
  assert.equal(S.isFirstPartyLocked(1), false);
});
