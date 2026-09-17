// getUserCampusScope：行业「偏好优先、简历兜底」，且简历那一档读的列必须是 candidate_profiles.industries。
// 背景：3a0fa0f~b7ff590 期间 select 的是不存在的 `target_industries`，PostgREST 报错 → 简历档从未生效。
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { loadTs } = require("./_load-ts.js");

const mod = loadTs(path.resolve(__dirname, "../lib/campus-user-industries.ts"));

/** 伪 Supabase：按表返回一行；select 里点了表里没有的列就像 PostgREST 一样报错、data=null。 */
function fakeSupabase(rows) {
  const columns = {
    candidate_profiles: ["industries", "target_roles", "target_locations"],
    user_preferences: ["target_industries", "target_roles", "target_locations"],
  };
  const selected = {};
  return {
    selected,
    from(table) {
      return {
        select(cols) {
          selected[table] = cols;
          const bad = cols.split(",").map((c) => c.trim()).filter((c) => !columns[table].includes(c));
          return {
            eq() {
              return {
                async maybeSingle() {
                  if (bad.length) return { data: null, error: { message: `column ${bad[0]} does not exist` } };
                  return { data: rows[table] ?? null, error: null };
                },
              };
            },
          };
        },
      };
    },
  };
}

test("偏好为空、简历有行业 → 用简历行业（此前这一档从未生效）", async () => {
  const sb = fakeSupabase({
    candidate_profiles: { industries: ["能源/化工"], target_roles: [], target_locations: [] },
    user_preferences: { target_industries: [], target_roles: [], target_locations: [] },
  });
  const r = await mod.getUserCampusScope(sb, "u1");
  assert.deepEqual(r.rawIndustries, ["能源/化工"]);
  assert.deepEqual(r.industries, ["能源/化工"]);
  assert.ok(r.companies.length > 0);
});

test("偏好已填 → 偏好优先，简历不覆盖手填", async () => {
  const sb = fakeSupabase({
    candidate_profiles: { industries: ["互联网/科技", "医疗/医药"] },
    user_preferences: { target_industries: ["互联网"] },
  });
  const r = await mod.getUserCampusScope(sb, "u2");
  assert.deepEqual(r.rawIndustries, ["互联网"]);
  assert.deepEqual(r.industries, ["互联网/科技"]);
});

test("没有偏好行、只有简历 → 用简历", async () => {
  const sb = fakeSupabase({ candidate_profiles: { industries: ["制造/工业"] } });
  const r = await mod.getUserCampusScope(sb, "u3");
  assert.deepEqual(r.industries, ["制造/工业"]);
});

test("两边都空 → 兜底互联网/科技，rawIndustries 为空（页面据此显示「未填行业」）", async () => {
  const r = await mod.getUserCampusScope(fakeSupabase({}), "u4");
  assert.deepEqual(r.rawIndustries, []);
  assert.deepEqual(r.industries, ["互联网/科技"]);
});

test("简历表 select 的列名必须是 industries（不是 target_industries），否则整条查询报错", async () => {
  const sb = fakeSupabase({ candidate_profiles: { industries: ["金融"] } });
  await mod.getUserCampusScope(sb, "u5");
  const cols = sb.selected.candidate_profiles.split(",").map((c) => c.trim());
  assert.ok(cols.includes("industries"), cols.join(","));
  assert.ok(!cols.includes("target_industries"), cols.join(","));
});
