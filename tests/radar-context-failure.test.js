// F10 哨兵：小表查询失败绝不能被当成「用户没填」。
//
// 缺陷原貌（2026-09-08 修）：/today 与 /api/opportunities 并行读四张小表后只取 .data 不看 .error。
// 于是超时/权限错误 → 偏好为空 → 排除词失效、已忽略岗重现、老用户被打回填表引导页，
// 且全程不报错，用户只会觉得「这产品乱推」。
//
// 这条测试**逐张表注入失败**，确认硬上下文一律抛错、软上下文才允许降级。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const { loadRadarContext, RadarContextError } = loadTs(
  path.join(__dirname, "..", "lib", "opportunities", "context.ts"),
);

const TABLES = ["user_preferences", "candidate_profiles", "job_actions", "user_radar_state"];

/** 最小 Supabase 桩：failTable 指定哪张表返回 error，其余表正常返回 rows。 */
function fakeSupabase({ failTable = null, rows = {} } = {}) {
  return {
    from(table) {
      const result =
        table === failTable
          ? { data: null, error: { message: "statement timeout" } }
          : { data: rows[table] ?? (table === "job_actions" ? [] : null), error: null };
      const chain = {
        select: () => chain,
        eq: () => chain,
        maybeSingle: async () => result,
        then: (resolve, reject) => Promise.resolve(result).then(resolve, reject),
      };
      return chain;
    },
  };
}

for (const table of ["user_preferences", "candidate_profiles", "job_actions"]) {
  test(`硬上下文 ${table} 查询失败必须抛错，不得降级成空值`, async () => {
    await assert.rejects(
      () => loadRadarContext(fakeSupabase({ failTable: table }), "u1"),
      (e) => {
        assert.ok(e instanceof RadarContextError, `应抛 RadarContextError，实际 ${e.name}`);
        assert.equal(e.table, table);
        return true;
      },
      `${table} 失败被静默吞掉 = 用户条件被悄悄放宽`,
    );
  });
}

test("软上下文 user_radar_state 失败允许降级（它不参与任何筛选）", async () => {
  const ctx = await loadRadarContext(fakeSupabase({ failTable: "user_radar_state" }), "u1");
  assert.equal(ctx.radarState, null);
  assert.deepEqual(ctx.actions, []);
});

test("零行（用户确实没填）不是失败：正常返回空值，不抛错", async () => {
  const ctx = await loadRadarContext(fakeSupabase(), "u1");
  assert.equal(ctx.preferences, null);
  assert.equal(ctx.candidate, null);
  assert.deepEqual(ctx.actions, []);
  assert.equal(ctx.radarState, null);
});

test("正常读到数据时原样返回（排除词与已处理记录不能丢）", async () => {
  const ctx = await loadRadarContext(
    fakeSupabase({
      rows: {
        user_preferences: { user_id: "u1", exclude_keywords: ["外包", "销售"] },
        candidate_profiles: { user_id: "u1", target_roles: ["产品经理"] },
        job_actions: [{ job_id: "j1", action: "ignored" }],
        user_radar_state: { last_opened_at: "2026-09-07T00:00:00Z" },
      },
    }),
    "u1",
  );
  assert.deepEqual(ctx.preferences.exclude_keywords, ["外包", "销售"]);
  assert.equal(ctx.actions.length, 1);
  assert.equal(ctx.radarState.last_opened_at, "2026-09-07T00:00:00Z");
});

test("四张表都覆盖到了（新增上下文表必须显式归类到硬/软）", () => {
  const src = require("node:fs").readFileSync(
    path.join(__dirname, "..", "lib", "opportunities", "context.ts"),
    "utf8",
  );
  for (const t of TABLES) {
    assert.ok(src.includes(`"${t}"`), `context.ts 未覆盖 ${t}`);
  }
});
