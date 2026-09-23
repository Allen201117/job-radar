// /today 召回快照（2026-09-23）的口径护栏。
//
// 召回挪出请求路径后，请求时跑的是「限定重算」：同一条召回 SQL，只是每层额外限定在
// 「快照当时该层选中的 id ∪ 快照之后才首见的岗」里。它与现跑之间唯一允许的差别就是这个限定条件——
// 其余 where / 排序 / 限额 / 参数位置一个字节都不能漂，否则「用快照」就悄悄变成了另一套推荐口径。
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const { loadTs } = require("./_load-ts");
const ROOT = path.join(__dirname, "..");
const O = loadTs(path.join(ROOT, "lib", "jobs-store", "opportunities.ts"));
const { buildRadarProfile } = loadTs(path.join(ROOT, "lib", "opportunities", "profile.ts"));

const SINCE = "2026-09-16T12:00:00.000Z";
const T = "2026-09-23T04:40:00.000Z";

function profile(over = {}) {
  return buildRadarProfile(
    "u1",
    {
      target_roles: ["产品经理", "数据分析"],
      target_keywords: [],
      skills: ["SQL"],
      target_locations: ["上海", "杭州"],
      target_companies: ["字节跳动", "腾讯"],
      exclude_keywords: [],
      job_scope: "domestic",
      experience_stage: "校招",
      ...over,
    },
    null,
  );
}

test("不传限定条件时，SQL 与参数和改造前逐字节相同（没有 recall_pool、没有多出参数）", () => {
  const p = profile();
  const a = O.buildRecallSql(p, SINCE, 1800, ["00000000-0000-0000-0000-000000000001"]);
  const b = O.buildRecallSql(p, SINCE, 1800, ["00000000-0000-0000-0000-000000000001"], {});
  assert.equal(a.sql, b.sql);
  assert.deepEqual(a.params, b.params);
  assert.doesNotMatch(a.sql, /recall_pool/);
});

test("限定重算 = 现跑 SQL + 每层一个限定条件；原有参数位置一个不动", () => {
  const p = profile();
  const live = O.buildRecallSql(p, SINCE, 1800, []);
  const idsByTier = Object.fromEntries(live.tiers.map((t, i) => [t, [`00000000-0000-0000-0000-00000000000${i}`]]));
  const rest = O.buildRecallSql(p, SINCE, 1800, [], { restrict: { idsByTier, newerThan: T } });

  // ① 原有参数原样保留在前面（阶段谓词哨兵测试按位置认参数，见 tests/recall-stage-index-alignment）
  assert.deepEqual(rest.params.slice(0, live.params.length), live.params);
  assert.deepEqual(rest.tiers, live.tiers);
  // ② 新增参数：时间点 + 全部 id 并集 + 每层一份 id
  assert.equal(rest.params.length, live.params.length + 2 + live.tiers.length);
  assert.equal(rest.params[live.params.length], T);

  // ③ 去掉候选池前缀、把池换回 jobs、去掉每层的限定条件 → 必须逐字节回到现跑 SQL
  const newerRef = `\\$${live.params.length + 1}::timestamptz`;
  const stripped = rest.sql
    .replace(/^with recall_pool as materialized \([^\n]*\)\n/, "")
    .replace(/from recall_pool jobs /g, "from jobs ")
    .replace(new RegExp(` and \\(id = any\\(\\$\\d+::uuid\\[\\]\\) or first_seen_at > ${newerRef}\\)`, "g"), "");
  assert.equal(stripped, live.sql);
  // ④ 候选池必须物化，否则规划器会把方向 tsquery 提到池外去扫 GIN（正是要绕开的几万行回表）
  assert.match(rest.sql, /^with recall_pool as materialized \(select \* from jobs where status = 'active' and \(id = any\(/);
});

test("快照某层当时一行没选中 → 该层只看快照之后的新岗（空数组，不是省略条件）", () => {
  const p = profile();
  const live = O.buildRecallSql(p, SINCE, 1800, []);
  const rest = O.buildRecallSql(p, SINCE, 1800, [], { restrict: { idsByTier: {}, newerThan: T } });
  for (let i = 0; i < live.tiers.length; i++) {
    assert.deepEqual(rest.params[live.params.length + 2 + i], []);
  }
  assert.equal((rest.sql.match(/ or first_seen_at > \$/g) || []).length, live.tiers.length + 1);
});

test("快照指纹：不随时间窗 / 已处理岗变，随画像变（改偏好 = 快照自动作废）", () => {
  const k = O.recallSnapshotKey(profile());
  assert.match(k, /^[0-9a-f]{32}$/);
  assert.equal(O.recallSnapshotKey(profile()), k, "同一画像两次算出同一个指纹");
  for (const over of [
    { target_locations: ["上海"] },
    { target_roles: ["产品经理"] },
    { target_companies: [] },
    { experience_stage: "社招" },
    { exclude_keywords: ["外包"] },
    { job_scope: "all", target_regions: ["US"] },
  ]) {
    assert.notEqual(O.recallSnapshotKey(profile(over)), k, `改了 ${Object.keys(over).join(",")} 指纹必须变`);
  }
});

test("快照能不能用：没有 / 指纹不对 / 超 12 小时 / 来自未来 都退回现跑", () => {
  const now = new Date("2026-09-23T10:00:00.000Z");
  const key = "k";
  const at = (h) => new Date(now.getTime() - h * 3_600_000).toISOString();
  const use = (snap, k = key) => O.recallSnapshotUsability(snap, k, now);
  assert.deepEqual(use(null), { usable: false, reason: "none", ageMs: null });
  assert.equal(use({ recallKey: key, computedAt: at(1) }, null).reason, "none");
  assert.equal(use({ recallKey: "other", computedAt: at(1) }).reason, "key_mismatch");
  assert.equal(use({ recallKey: key, computedAt: at(12.5) }).reason, "stale");
  assert.equal(use({ recallKey: key, computedAt: at(-1) }).reason, "future");
  const ok = use({ recallKey: key, computedAt: at(11.9) });
  assert.equal(ok.usable, true);
  assert.equal(ok.reason, "ok");
  assert.equal(Math.round(ok.ageMs / 60_000), 714);
  const prev = process.env.TODAY_RECALL_SNAPSHOT;
  process.env.TODAY_RECALL_SNAPSHOT = "off";
  try {
    assert.equal(use({ recallKey: key, computedAt: at(1) }).reason, "disabled", "运维开关：一关即全部现跑");
  } finally {
    if (prev === undefined) delete process.env.TODAY_RECALL_SNAPSHOT;
    else process.env.TODAY_RECALL_SNAPSHOT = prev;
  }
});

test("页面接线：快照与悉尼查询并行发出；只有本人真实画像那一次构建带快照，写 / 刷新都在响应之后", () => {
  const page = fs.readFileSync(path.join(ROOT, "app", "today", "page.tsx"), "utf8");
  const snapAt = page.indexOf("readRecallSnapshotSafe(userId)");
  const ctxAt = page.indexOf("await loadRadarContext(");
  assert.ok(snapAt > 0 && ctxAt > snapAt, "快照读取必须在等悉尼那 4 条查询之前发出");
  assert.equal((page.match(/recallSnapshot:/g) || []).length, 1, "放宽 / 范围兜底的重算用的是改过的画像，不许带快照、更不许回写");
  assert.match(page, /later\(\(\) =>\s*writeRecallSnapshot\(/);
  assert.match(page, /later\(\(\) =>\s*refreshRecallSnapshot\(/);
  // after() 自身抛错不许冒到 bundle 的 promise 链上（那会把整页打成错误面板）
  assert.match(page, /try \{\n\s*after\(task\);\n\s*\} catch/);
});

test("快照只许由现跑结果写：限定重算的结果不回写（否则子集套子集，偏差一轮轮累积）", () => {
  const src = fs.readFileSync(path.join(ROOT, "lib", "jobs-store", "opportunities.ts"), "utf8");
  assert.match(src, /const tierRows = restrict \? undefined :/);
  assert.match(src, /snapshot: \{ used: true, reason: "ok", ageMs: verdict\.ageMs \},\n\s*\};/);
});

test("保存偏好后在响应之后预算快照；顶栏切范围不挂（前端立刻 refresh，/today 自己会现跑并回写）", () => {
  const route = fs.readFileSync(path.join(ROOT, "app", "api", "preferences", "route.ts"), "utf8");
  const put = route.slice(route.indexOf("export async function PUT"), route.indexOf("export async function PATCH"));
  const patch = route.slice(route.indexOf("export async function PATCH"));
  // 必须挂在「偏好已落库」之后、coverage 同步之前（coverage 失败也照样是新偏好）
  const upsertAt = put.indexOf('.from("user_preferences")');
  const schedAt = put.indexOf('scheduleRecallSnapshotRefresh(user.id, "保存偏好")');
  const coverageAt = put.indexOf("syncCoverage(");
  assert.ok(upsertAt > 0 && schedAt > upsertAt && coverageAt > schedAt);
  assert.doesNotMatch(patch, /scheduleRecallSnapshotRefresh\(/);
  const upkeep = fs.readFileSync(path.join(ROOT, "lib", "opportunities", "recall-snapshot-upkeep.ts"), "utf8");
  assert.match(upkeep, /try \{\n\s*after\(/, "写接口里的快照维护永不抛");
});

test("recallActionedJobIds：只有 saved / ignored / applied 占召回名额，viewed 不算，去重", () => {
  const src = fs.readFileSync(path.join(ROOT, "lib", "opportunities", "recall-snapshot-upkeep.ts"), "utf8");
  const body = src.slice(src.indexOf("export function recallActionedJobIds"), src.indexOf("function snapshotsEnabled"));
  const fn = new Function(
    "actions",
    body
      .replace(/^export function recallActionedJobIds\([^)]*\): string\[\] \{/, "")
      .replace(/\}\s*$/, "")
      .replace(/new Set<string>\(\)/, "new Set()"),
  );
  assert.deepEqual(
    fn([
      { job_id: "a", action: "viewed" },
      { job_id: "b", action: "saved" },
      { job_id: "b", action: "applied" },
      { job_id: "c", action: "ignored" },
    ]).sort(),
    ["b", "c"],
  );
});
