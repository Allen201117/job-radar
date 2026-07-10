// v3 动态分区（04 spec §7 / 05 §4 §6）：按 primary signal × 强度落点；关键提醒置顶不截断；
// active 显拓展、passive 不显且门槛高；一岗只出现一次。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadOpp } = require("./_load-ts");

const { groupOpportunities, resolveNoveltySince } = loadOpp("grouping");

let counter = 0;
// 构造一个已派生 signals 的 opportunity。signal 决定落点。
function opp(o = {}) {
  counter += 1;
  const sigType = o.signal ?? "STILL_OPEN";
  const isCritical = o.critical ?? false;
  return {
    job: {
      id: o.id || `j${counter}`,
      company: o.company === undefined ? "C" : o.company,
      title: o.title === undefined ? "T" : o.title,
      location: o.location === undefined ? null : o.location,
      jd_url: `u${counter}`,
      status: "active",
    },
    score: o.score ?? 80,
    tier: o.tier ?? "high",
    reasons: [],
    freshness: o.freshness ?? "verified",
    firstSeenAt: o.firstSeenAt ?? "2026-05-01T00:00:00Z",
    lastSeenAt: "2026-06-23T00:00:00Z",
    userAction: null,
    viewed: false,
    isNew: false,
    exploreEligible: o.exploreEligible ?? false,
    signals: [{ type: sigType, label: "x", priority: 3, isCritical, evidence: {} }],
    intensity: "active",
    lastCheckedAt: null,
    officialPostedAt: null,
    deadlineAt: null,
  };
}

test("STILL_OPEN 高分进 main", () => {
  const { sections } = groupOpportunities([opp({ score: 80 })], { dailyLimit: 20, intensity: "active" });
  assert.equal(sections.main.length, 1);
  assert.equal(sections.critical.length, 0);
});

test("回归：firstSeenAt 为 Date 对象（node-pg 时间列）不打挂排序（2026-06-26 事故）", () => {
  // 生产 node-pg 把 timestamptz 解析成 Date 对象 → 旧 cmpFirstSeenDesc 直接 .localeCompare 抛 TypeError。
  // 现统一转 epoch millis（+ client.ts type parser 根治）→ 同分按真实时间倒序，不抛。
  const opps = [
    opp({ id: "old", score: 80, firstSeenAt: new Date("2026-05-01T00:00:00Z") }),
    opp({ id: "new", score: 80, firstSeenAt: new Date("2026-06-20T00:00:00Z") }),
  ];
  let sections;
  assert.doesNotThrow(() => {
    ({ sections } = groupOpportunities(opps, { dailyLimit: 20, intensity: "active" }));
  });
  // 同分 → firstSeenAt 倒序：新的在前
  assert.equal(sections.main[0].job.id, "new");
  assert.equal(sections.main[1].job.id, "old");
});

test("Date 对象按时间毫秒排序，不受 weekday 字符串字典序影响", () => {
  const oldSunday = opp({ id: "old-sunday", score: 80, firstSeenAt: new Date("2026-06-28T00:00:00Z") });
  const newMonday = opp({ id: "new-monday", score: 80, firstSeenAt: new Date("2026-06-29T00:00:00Z") });
  const { sections } = groupOpportunities([oldSunday, newMonday], { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.main.map((item) => item.job.id), ["new-monday", "old-sunday"]);
});

test("分数与 firstSeenAt 完全相同时用 job.id 稳定破同分", () => {
  const sameTime = "2026-06-29T00:00:00Z";
  const { sections } = groupOpportunities(
    [
      opp({ id: "job-b", score: 80, firstSeenAt: sameTime }),
      opp({ id: "job-a", score: 80, firstSeenAt: sameTime }),
    ],
    { dailyLimit: 20, intensity: "active" },
  );
  assert.deepEqual(sections.main.map((item) => item.job.id), ["job-a", "job-b"]);
});

test("关键提醒：isCritical 进 critical 区，不被 main 截断、置顶", () => {
  const crits = Array.from({ length: 12 }, () =>
    opp({ signal: "CLOSED_OR_STALE", critical: true, score: 100 })
  );
  const { sections, counts } = groupOpportunities(crits, { dailyLimit: 5, intensity: "active" });
  assert.equal(sections.critical.length, 12); // 不被 dailyLimit 截断
  assert.equal(counts.critical, 12);
});

test("CLOSED_OR_STALE 非关键进 waiting，封顶 8", () => {
  const stale = Array.from({ length: 15 }, () => opp({ signal: "CLOSED_OR_STALE", critical: false }));
  const { sections } = groupOpportunities(stale, { dailyLimit: 30, intensity: "active" });
  assert.equal(sections.main.length, 0);
  assert.equal(sections.waiting.length, 8);
});

test("OPEN_UNVERIFIED 高分进 main，不进 waiting", () => {
  const { sections, counts } = groupOpportunities([opp({ signal: "OPEN_UNVERIFIED", score: 80 })], {
    dailyLimit: 20,
    intensity: "active",
  });
  assert.equal(sections.main.length, 1);
  assert.equal(sections.waiting.length, 0);
  assert.equal(counts.by_signal.OPEN_UNVERIFIED, 1);
});

test("OPEN_UNVERIFIED 分数 30–门槛 + exploreEligible → explore", () => {
  const { sections } = groupOpportunities(
    [opp({ signal: "OPEN_UNVERIFIED", score: 40, exploreEligible: true })],
    { dailyLimit: 20, intensity: "active" },
  );
  assert.equal(sections.main.length, 0);
  assert.equal(sections.explore.length, 1);
});

test("active：score 30–门槛 + exploreEligible → explore（最多 5）", () => {
  const ex = Array.from({ length: 8 }, () => opp({ score: 40, exploreEligible: true }));
  const { sections } = groupOpportunities(ex, { dailyLimit: 20, intensity: "active" });
  assert.equal(sections.explore.length, 5);
  assert.equal(sections.main.length, 0); // 40 < active 门槛 45
});

test("passive：不显拓展、门槛抬到 70、量收窄", () => {
  const opps = [
    ...Array.from({ length: 3 }, () => opp({ score: 80 })), // ≥70 进 main
    ...Array.from({ length: 5 }, () => opp({ score: 50, exploreEligible: true })), // 50<70 且 passive 无 explore → 丢弃
  ];
  const { sections } = groupOpportunities(opps, { dailyLimit: 20, intensity: "passive" });
  assert.equal(sections.main.length, 3);
  assert.equal(sections.explore.length, 0);
});

test("passive daily_limit 收窄到 ≤10", () => {
  const opps = Array.from({ length: 20 }, () => opp({ score: 90 }));
  const { sections } = groupOpportunities(opps, { dailyLimit: 30, intensity: "passive" });
  assert.equal(sections.main.length, 10);
});

test("一岗只出现一次（critical 优先于 main）", () => {
  const shared = opp({ id: "dup", signal: "DEADLINE_SOON", critical: true, score: 90 });
  const { sections } = groupOpportunities([shared], { dailyLimit: 20, intensity: "active" });
  const ids = [...sections.critical, ...sections.main, ...sections.explore, ...sections.waiting].map((o) => o.job.id);
  assert.equal(ids.length, new Set(ids).size);
  assert.equal(sections.critical.length, 1);
  assert.equal(sections.main.length, 0);
});

test("不同 id 的同公司标题地点岗位只出现一次，保留排序更优者", () => {
  const better = opp({
    id: "better",
    company: "字节跳动",
    title: "AI 产品经理",
    location: "上海",
    score: 90,
  });
  const duplicate = opp({
    id: "duplicate",
    company: " 字节跳动 ",
    title: "ai-产品经理",
    location: "上海市",
    score: 80,
  });
  const { sections } = groupOpportunities([duplicate, better], { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.main.map((item) => item.job.id), ["better"]);
});

test("同语义的不同 id 候选中 critical 必须胜过更高分的普通 main", () => {
  const highMain = opp({
    id: "high-main",
    company: "Acme",
    title: "AI Product Manager",
    location: "Shanghai",
    score: 100,
  });
  const lowCritical = opp({
    id: "low-critical",
    company: " acme ",
    title: "ai-product manager",
    location: "Shanghai",
    score: 20,
    signal: "CLOSED_OR_STALE",
    critical: true,
  });
  const { sections } = groupOpportunities([highMain, lowCritical], { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.critical.map((item) => item.job.id), ["low-critical"]);
  assert.equal(sections.main.length, 0);
});

test("同语义的非 critical 候选先按分区价值取舍，main 胜过更高分 waiting", () => {
  const lowMain = opp({
    id: "low-main",
    company: "Acme",
    title: "Designer",
    location: "Beijing",
    score: 45,
  });
  const highWaiting = opp({
    id: "high-waiting",
    company: "acme",
    title: "designer",
    location: "Beijing",
    score: 100,
    signal: "CLOSED_OR_STALE",
  });
  const { sections } = groupOpportunities([highWaiting, lowMain], { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.main.map((item) => item.job.id), ["low-main"]);
  assert.equal(sections.waiting.length, 0);
});

test("passive 下低于实际 main 门槛的主信号不得淘汰可展示 waiting", () => {
  const hiddenMainSignal = opp({
    id: "passive-hidden",
    company: "Acme",
    title: "Designer",
    location: "Beijing",
    score: 50,
  });
  const waiting = opp({
    id: "passive-waiting",
    company: "acme",
    title: "designer",
    location: "Beijing",
    score: 100,
    signal: "CLOSED_OR_STALE",
  });
  const { sections } = groupOpportunities([hiddenMainSignal, waiting], { dailyLimit: 20, intensity: "passive" });
  assert.deepEqual(sections.waiting.map((item) => item.job.id), ["passive-waiting"]);
});

test("active 下低于 main 门槛且不可 explore 的主信号不得淘汰 waiting", () => {
  const hiddenMainSignal = opp({
    id: "active-hidden",
    company: "Acme",
    title: "Designer",
    location: "Beijing",
    score: 44,
    exploreEligible: false,
  });
  const waiting = opp({
    id: "active-waiting",
    company: "acme",
    title: "designer",
    location: "Beijing",
    score: 100,
    signal: "CLOSED_OR_STALE",
  });
  const { sections } = groupOpportunities([hiddenMainSignal, waiting], { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.waiting.map((item) => item.job.id), ["active-waiting"]);
});

test("语义键任一字段缺失时回退 job.id，不误合并信息不足的岗位", () => {
  const incomplete = [
    opp({ id: "missing-company-a", company: null, title: "T", location: "L", score: 90 }),
    opp({ id: "missing-company-b", company: null, title: "T", location: "L", score: 80 }),
    opp({ id: "missing-title-a", company: "A", title: "", location: "L", score: 90 }),
    opp({ id: "missing-title-b", company: "A", title: "", location: "L", score: 80 }),
    opp({ id: "missing-a", company: "A", title: "T", location: null, score: 90 }),
    opp({ id: "missing-b", company: "A", title: "T", location: null, score: 80 }),
  ];
  const { sections } = groupOpportunities(incomplete, { dailyLimit: 20, intensity: "active" });
  assert.deepEqual(sections.main.map((item) => item.job.id), [
    "missing-a",
    "missing-company-a",
    "missing-title-a",
    "missing-b",
    "missing-company-b",
    "missing-title-b",
  ]);
});

test("main 候选充足时优先公司多样性", () => {
  const dominant = Array.from({ length: 8 }, (_, i) =>
    opp({ id: `a${i}`, company: "A", title: `T${i}`, location: "L", score: 100 - i })
  );
  const alternatives = ["B", "C", "D", "E", "F", "G", "H"].map((company, i) =>
    opp({ id: `x${i}`, company, title: `X${i}`, location: "L", score: 70 - i })
  );
  const { sections } = groupOpportunities([...dominant, ...alternatives], {
    dailyLimit: 10,
    intensity: "active",
  });
  assert.equal(sections.main.length, 10);
  assert.ok(sections.main.filter((item) => item.job.company === "A").length <= 3);
});

test("main 只有一家公司时回填溢出候选，不制造空位", () => {
  const only = Array.from({ length: 10 }, (_, i) =>
    opp({ id: `only-a${i}`, company: "A", title: `T${i}`, location: "L" })
  );
  const { sections } = groupOpportunities(only, { dailyLimit: 10, intensity: "active" });
  assert.equal(sections.main.length, 10);
});

test("explore 也应用软性公司多样性，且保持原上限 5", () => {
  const dominant = Array.from({ length: 4 }, (_, i) =>
    opp({ id: `explore-a${i}`, company: "A", title: `T${i}`, location: "L", score: 40 - i, exploreEligible: true })
  );
  const alternatives = ["B", "C", "D"].map((company, i) =>
    opp({ id: `explore-x${i}`, company, title: `X${i}`, location: "L", score: 35 - i, exploreEligible: true })
  );
  const { sections } = groupOpportunities([...dominant, ...alternatives], {
    dailyLimit: 20,
    intensity: "active",
  });
  assert.equal(sections.explore.length, 5);
  assert.equal(sections.explore.filter((item) => item.job.company === "A").length, 2);
});

test("waiting 不应用公司多样性，保留原排序和上限 8", () => {
  const dominant = Array.from({ length: 6 }, (_, i) =>
    opp({ id: `waiting-a${i}`, company: "A", title: `T${i}`, location: "L", score: 100 - i, signal: "CLOSED_OR_STALE" })
  );
  const alternatives = Array.from({ length: 6 }, (_, i) =>
    opp({ id: `waiting-x${i}`, company: `X${i}`, title: `X${i}`, location: "L", score: 70 - i, signal: "CLOSED_OR_STALE" })
  );
  const { sections } = groupOpportunities([...dominant, ...alternatives], {
    dailyLimit: 20,
    intensity: "active",
  });
  assert.equal(sections.waiting.length, 8);
  assert.equal(sections.waiting.filter((item) => item.job.company === "A").length, 6);
});

test("momentum 恒空（job_events 前不上）", () => {
  const { sections } = groupOpportunities([opp({ score: 80 })], { dailyLimit: 20, intensity: "active" });
  assert.equal(sections.momentum.length, 0);
});

test("counts.by_signal 按 primary signal 计数", () => {
  const opps = [opp({ score: 80 }), opp({ score: 80 }), opp({ signal: "CLOSED_OR_STALE", critical: false })];
  const { counts } = groupOpportunities(opps, { dailyLimit: 20, intensity: "active" });
  assert.equal(counts.by_signal.STILL_OPEN, 2);
  assert.equal(counts.by_signal.CLOSED_OR_STALE, 1);
});

test("resolveNoveltySince：无上次访问 → now-72h；有则原样", () => {
  const now = new Date("2026-06-23T12:00:00.000Z");
  assert.equal(resolveNoveltySince(null, now), new Date(now.getTime() - 72 * 3600 * 1000).toISOString());
  assert.equal(resolveNoveltySince("2026-06-22T00:00:00.000Z", now), "2026-06-22T00:00:00.000Z");
});
