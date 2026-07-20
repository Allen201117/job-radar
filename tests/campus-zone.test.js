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
