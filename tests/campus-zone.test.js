const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { loadTs } = require("./_load-ts");
// 一次性 loadTs 加载 campus-zone.ts；后续任务只需在本行解构补上新函数名。
const { campusAdmission, windowStatus, compareCampusJobs, compareCompanyCards, groupCampusJobs } =
  loadTs(path.join(__dirname, "..", "lib", "campus-zone.ts"));

test("campusAdmission: 强校招信号 → campus", () => {
  assert.equal(campusAdmission({ title: "2027届校园招聘-后端工程师", job_type: "校招" }), "campus");
  assert.equal(campusAdmission({ title: "管培生", jd_url: "https://x.com/campus/1" }), "campus");
});

test("campusAdmission: 实习单独成桶，不混校招", () => {
  assert.equal(campusAdmission({ title: "暑期实习-数据分析", job_type: "实习" }), "intern");
});

test("campusAdmission: 社招/弱词/无信号 → reject（精度优先，宁漏勿误）", () => {
  assert.equal(campusAdmission({ title: "高级后端工程师", job_type: "社招" }), "reject");
  assert.equal(campusAdmission({ title: "后端工程师（毕业生优先）" }), "reject"); // 弱词不判校招
  assert.equal(campusAdmission({ title: "资深架构师", summary: "8年经验", job_type: "校招" }), "reject"); // ≥2年经验强制社招
});

const H = 3600 * 1000;

test("windowStatus: 有在招校招岗且新鲜 → hiring", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 12, hasCampusSource: true, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 2 * H }),
    { state: "hiring" }
  );
});

test("windowStatus: 有源但当前无校招岗 → no_campus_now（不等于没开）", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 0, hasCampusSource: true, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 2 * H }),
    { state: "no_campus_now" }
  );
});

test("windowStatus: 无源 → not_ingested + 子原因", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 0, hasCampusSource: false, hasAnySource: false, lastSeenAtMs: null, nowMs: 1000 * H }),
    { state: "not_ingested", subReason: "no_source" }
  );
  assert.deepEqual(
    windowStatus({ campusJobCount: 0, hasCampusSource: false, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H }),
    { state: "not_ingested", subReason: "source_only_social" }
  );
});

test("windowStatus: 有校招岗但源太久没抓 → stale（不冒充 hiring）", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 5, hasCampusSource: true, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 100 * H }),
    { state: "stale" }
  );
});

test("windowStatus: 有校招岗但源URL无campus令牌(job_type识别的) → hiring 不误判待接入", () => {
  assert.deepEqual(
    windowStatus({ campusJobCount: 5, hasCampusSource: false, hasAnySource: true, lastSeenAtMs: 1000 * H, nowMs: 1000 * H + 2 * H }),
    { state: "hiring" }
  );
});

test("compareCampusJobs: 有截止的排前（临近优先），无截止的按新增降序在后", () => {
  const soon = { deadline: "2026-08-01", first_seen_at: "2026-07-01" };
  const later = { deadline: "2026-09-01", first_seen_at: "2026-07-10" };
  const noDeadlineNew = { deadline: null, first_seen_at: "2026-07-18" };
  const noDeadlineOld = { deadline: null, first_seen_at: "2026-07-02" };
  const sorted = [noDeadlineOld, later, noDeadlineNew, soon].sort(compareCampusJobs);
  assert.deepEqual(sorted.map((j) => j.deadline || j.first_seen_at),
    ["2026-08-01", "2026-09-01", "2026-07-18", "2026-07-02"]);
});

// 可复现的洗牌（mulberry32）：模拟同一批行按不同执行计划回来的不同行序。
function seededShuffle(arr, seed) {
  let s = seed >>> 0;
  const rand = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

// 爬虫一批入库几百行 first_seen_at 逐字相同、截止日也常相同；抽屉按 offset 分页、每页一次请求。
// 没有唯一决胜列时，并列块内的顺序跟着 SQL 行序（执行计划）走，两次请求的切片会重复 / 漏岗。
const TIE_BATCH = "2026-09-23 02:00:00.123456+00";
const TIE_ROWS = [
  { id: "c3a1f0e2-0000-4000-8000-000000000001", deadline: "2026-10-15", first_seen_at: "2026-09-20 10:00:00+08" },
  { id: "1b7e44d0-0000-4000-8000-000000000002", deadline: "2026-10-15", first_seen_at: "2026-09-20 10:00:00+08" },
  { id: "e7d2c9b1-0000-4000-8000-000000000003", deadline: "2026-10-31", first_seen_at: TIE_BATCH },
  { id: "04f5a6b7-0000-4000-8000-000000000004", deadline: "2026-10-31", first_seen_at: TIE_BATCH },
  { id: "a9c8e1d3-0000-4000-8000-000000000005", deadline: "2026-10-31", first_seen_at: TIE_BATCH },
  { id: "5d0b3e8f-0000-4000-8000-000000000006", deadline: "2026-10-31", first_seen_at: TIE_BATCH },
  { id: "b2e9d4c1-0000-4000-8000-000000000007", deadline: null, first_seen_at: TIE_BATCH },
  { id: "07a3c5e9-0000-4000-8000-000000000008", deadline: null, first_seen_at: TIE_BATCH },
  { id: "6f1d8b2a-0000-4000-8000-000000000009", deadline: "长期有效", first_seen_at: TIE_BATCH }, // parse 不出 = 无截止
  { id: "3c4e5f60-0000-4000-8000-000000000010", deadline: null, first_seen_at: "2026-09-10 08:00:00+08" },
];
const idHead = (rows) => rows.map((j) => j.id.slice(0, 2));

test("compareCampusJobs: 并列行按 id 升序决胜，任意输入行序都排出同一个序列", () => {
  const expected = ["1b", "c3", "04", "5d", "a9", "e7", "07", "6f", "b2", "3c"];
  for (let seed = 1; seed <= 200; seed++) {
    assert.deepEqual(idHead(seededShuffle(TIE_ROWS, seed).sort(compareCampusJobs)), expected, `seed=${seed}`);
  }
});

test("compareCampusJobs: id 只在并列时生效，截止日 / 首见日两个键的先后不变", () => {
  // id 更小的岗照样排在截止更晚 / 首见更早的位置（04 < 1b，但 10-31 在 10-15 之后；3c < b2，但首见更早）
  const sorted = seededShuffle(TIE_ROWS, 7).sort(compareCampusJobs);
  const pos = (head) => sorted.findIndex((j) => j.id.startsWith(head));
  assert.ok(pos("1b") < pos("04"));
  assert.ok(pos("b2") < pos("3c"));
  assert.ok(pos("e7") < pos("07")); // 有截止的整体在无截止之前
});

test("compareCampusJobs: 按 offset 分页、每页一次请求且行序各不相同，也不重复不漏", () => {
  const limit = 3;
  for (let start = 1; start <= 100; start++) {
    const paged = [];
    for (let offset = 0, seed = start * 10; offset < TIE_ROWS.length; offset += limit, seed++) {
      paged.push(...seededShuffle(TIE_ROWS, seed).sort(compareCampusJobs).slice(offset, offset + limit));
    }
    const ids = paged.map((j) => j.id);
    assert.equal(new Set(ids).size, TIE_ROWS.length, `分页结果有重复（start=${start}）`);
    assert.deepEqual([...ids].sort(), TIE_ROWS.map((j) => j.id).sort(), `分页结果有漏岗（start=${start}）`);
  }
});

test("compareCompanyCards: hiring 在 no_campus_now / not_ingested 之前", () => {
  const hiring = { window: { state: "hiring" }, nearestDeadlineMs: 100 };
  const noCampus = { window: { state: "no_campus_now" }, nearestDeadlineMs: null };
  const notIngested = { window: { state: "not_ingested" }, nearestDeadlineMs: null };
  const sorted = [notIngested, noCampus, hiring].sort(compareCompanyCards);
  assert.deepEqual(sorted.map((c) => c.window.state), ["hiring", "no_campus_now", "not_ingested"]);
});

test("groupCampusJobs: 按城市归组，组内排序，组按岗位数降序", () => {
  const jobs = [
    { title: "A", city: "北京", deadline: "2026-08-10", first_seen_at: "2026-07-01" },
    { title: "B", city: "上海", deadline: null, first_seen_at: "2026-07-05" },
    { title: "C", city: "北京", deadline: "2026-08-01", first_seen_at: "2026-07-02" },
  ];
  const groups = groupCampusJobs(jobs);
  assert.equal(groups[0].label, "北京");
  assert.deepEqual(groups[0].jobs.map((j) => j.title), ["C", "A"]); // 8-01 早于 8-10
  assert.equal(groups[1].label, "上海");
});

test("campusAdmission: 库里已有 recruitment_category 时直接认列，不再靠现算（列与现算同源）", () => {
  // 没有任何文本信号、只有列 → 以列为准
  assert.equal(campusAdmission({ title: "大模型算法工程师", job_type: "研发类", recruitment_category: "实习" }), "intern");
  assert.equal(campusAdmission({ title: "研发工艺工程师", recruitment_category: "校招" }), "campus");
  assert.equal(campusAdmission({ title: "2027届校园招聘-产品", recruitment_category: "社招" }), "reject");
  // 列为空 / 非法值 → 退回现算
  assert.equal(campusAdmission({ title: "2027届校园招聘-产品", recruitment_category: null }), "campus");
  assert.equal(campusAdmission({ title: "产品实习生", recruitment_category: "未知" }), "intern");
});
