const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { scoreJob, scoringSignalGroups } = loadTs(path.join(__dirname, "..", "lib", "scoring.ts"));

// scoringSignalGroups 决定「候选窗口装不下时，谁优先进窗口」。它必须覆盖 scoreJob 里**每一类**
// 会加分的偏好字段：漏一类，那类高分岗就会被截断在窗口外，「按匹配度」的第一页会缺人，
// 而这种缺失在页面上完全看不出来。这里拿 scoreJob 的真实得分反过来对拍。
// 分组是刻意的：调用方要按「这一维在本次候选集里还有没有区分度」逐组取舍。

const allTerms = (groups) => [...groups.direction, ...groups.companies, ...groups.locations];

const FRESHNESS_ONLY = 10; // 近 7 天新增，唯一一项与偏好无关的加分

const baseJob = {
  id: "j1",
  title: "后端工程师",
  company: "某公司",
  location: "深圳",
  summary: "",
  first_seen_at: "2000-01-01T00:00:00Z", // 刻意放旧：把新鲜度加分排除掉
};

const emptyPrefs = {
  target_roles: [],
  target_keywords: [],
  skills: [],
  target_companies: [],
  target_locations: [],
  exclude_keywords: [],
};

test("每一类会加分的偏好字段都被 scoringSignalTerms 收进来", () => {
  // 每个用例：只填一类偏好 + 一个刚好命中它的岗位 → scoreJob 必须给分。
  const cases = [
    { field: "target_roles", value: "后端工程师", group: "direction" },
    { field: "target_keywords", value: "后端", group: "direction" },
    { field: "skills", value: "后端", group: "direction" },
    { field: "target_companies", value: "某公司", group: "companies" },
    { field: "target_locations", value: "深圳", group: "locations" },
  ];
  for (const { field, value, group } of cases) {
    const prefs = { ...emptyPrefs, [field]: [value] };
    const score = scoreJob(baseJob, prefs, []).score;
    assert.ok(score > 0, `${field} 本应给岗位加分，实际 ${score}——用例失效了，先修用例`);
    const groups = scoringSignalGroups(prefs);
    assert.ok(
      allTerms(groups).includes(value),
      `${field} 会加分却没进 scoringSignalGroups：这类高分岗会被截断在候选窗口外`,
    );
    assert.ok(groups[group].includes(value), `${field} 应归到 ${group} 组`);
  }
});

test("窗口外的岗位最多只剩「近 7 天 +10」——这是按新鲜度补位的依据", () => {
  const prefs = {
    ...emptyPrefs,
    target_roles: ["产品经理"],
    target_locations: ["北京"],
    target_companies: ["腾讯"],
  };
  // 一个哪条偏好都不沾边的岗位：只可能拿到新鲜度分。
  const stranger = { ...baseJob, title: "车间操作工", company: "无关厂", location: "银川" };
  assert.equal(scoreJob(stranger, prefs, []).score, 0);
  assert.equal(
    scoreJob({ ...stranger, first_seen_at: new Date().toISOString() }, prefs, []).score,
    FRESHNESS_ONLY,
  );
});

test("无偏好 = 没有任何词可优先，此时按新鲜度排就是正确排序", () => {
  assert.deepEqual(allTerms(scoringSignalGroups(null)), []);
  assert.deepEqual(allTerms(scoringSignalGroups(emptyPrefs)), []);
  assert.equal(scoreJob(baseJob, emptyPrefs, []).score, 0);
});

test("海外画像才带上英文侧偏好词", () => {
  const prefs = { ...emptyPrefs, target_roles: ["产品经理"], en_target_roles: ["Product Manager"] };
  assert.deepEqual(scoringSignalGroups(prefs).direction, ["产品经理"]);
  assert.deepEqual(scoringSignalGroups(prefs, { overseasProfile: true }).direction, [
    "Product Manager",
    "产品经理",
  ]);
});

test("去重且忽略空白项，别让空串污染 tsquery", () => {
  const prefs = {
    ...emptyPrefs,
    target_roles: ["后端", " 后端 ", ""],
    target_keywords: ["  ", "Go"],
  };
  assert.deepEqual(scoringSignalGroups(prefs).direction, ["后端", "Go"]);
});
