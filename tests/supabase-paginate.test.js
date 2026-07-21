// sources「拉全表」分页助手：PostgREST 单次 select 静默截断 1000 行，越过 1000 的表必须分页拉。
// 关键护栏：① 翻到底（不是只拿第一页）② 每页都带稳定排序键 id（无 ORDER BY 会重复取行+漏行）
// ③ enabledOnly 时过滤条件每页都带 ④ 出错抛出、不静默返回半截数据。
const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { loadTs } = require("./_load-ts");

const { fetchAllPages, fetchAllSources, PAGE_SIZE } = loadTs(
  path.join(__dirname, "..", "lib", "supabase-paginate.ts"),
);

// 记录每次 select 的完整链式调用，便于断言 order/eq/range 都带上了。
function fakeClient(rows, { error = null } = {}) {
  const calls = [];
  return {
    calls,
    from(table) {
      const call = { table, columns: null, eq: null, order: null, range: null };
      const builder = {
        select(columns) {
          call.columns = columns;
          calls.push(call);
          return builder;
        },
        eq(column, value) {
          call.eq = [column, value];
          return builder;
        },
        order(column, opts) {
          call.order = [column, opts];
          return builder;
        },
        range(from, to) {
          call.range = [from, to];
          if (error) return Promise.resolve({ data: null, error });
          const page = rows.filter((r) => (call.eq ? r[call.eq[0]] === call.eq[1] : true)).slice(from, to + 1);
          return Promise.resolve({ data: page, error: null });
        },
      };
      return builder;
    },
  };
}

test("fetchAllPages 翻到底：末页不满 step 才停", async () => {
  const seen = [];
  const rows = Array.from({ length: 5 }, (_, i) => ({ id: i }));
  const out = await fetchAllPages((from, to) => {
    seen.push([from, to]);
    return Promise.resolve({ data: rows.slice(from, to + 1), error: null });
  }, 2);
  assert.deepEqual(out, rows);
  assert.deepEqual(seen, [[0, 1], [2, 3], [4, 5]]);
});

test("fetchAllPages 满页整除时会多取一页空页再停（不漏行）", async () => {
  const rows = Array.from({ length: 4 }, (_, i) => ({ id: i }));
  const seen = [];
  const out = await fetchAllPages((from, to) => {
    seen.push(from);
    return Promise.resolve({ data: rows.slice(from, to + 1), error: null });
  }, 2);
  assert.equal(out.length, 4);
  assert.deepEqual(seen, [0, 2, 4]);
});

test("fetchAllPages 出错抛出，不静默返回半截数据", async () => {
  await assert.rejects(
    () => fetchAllPages(() => Promise.resolve({ data: null, error: { message: "boom" } })),
    /boom/,
  );
});

test("fetchAllSources 越过 1000 行时拿到全量（不被截断到第一页）", async () => {
  const rows = Array.from({ length: 1121 }, (_, i) => ({ id: `s${i}`, company: `c${i}`, enabled: true }));
  const client = fakeClient(rows);
  const out = await fetchAllSources(client, "id, company");
  assert.equal(out.length, 1121);
  assert.equal(out[1120].company, "c1120");
  assert.equal(client.calls.length, 2);
  assert.deepEqual(client.calls[0].range, [0, PAGE_SIZE - 1]);
  assert.deepEqual(client.calls[1].range, [PAGE_SIZE, PAGE_SIZE * 2 - 1]);
});

test("fetchAllSources 每页都带稳定排序键 id 升序", async () => {
  const rows = Array.from({ length: 1500 }, (_, i) => ({ id: `s${i}`, enabled: true }));
  const client = fakeClient(rows);
  await fetchAllSources(client, "id");
  assert.ok(client.calls.length >= 2);
  for (const call of client.calls) {
    assert.deepEqual(call.order, ["id", { ascending: true }]);
  }
});

test("fetchAllSources enabledOnly 每页都带 enabled 过滤，只回 enabled 行", async () => {
  const rows = Array.from({ length: 1200 }, (_, i) => ({ id: `s${i}`, enabled: i % 2 === 0 }));
  const client = fakeClient(rows);
  const out = await fetchAllSources(client, "id, company", { enabledOnly: true });
  assert.equal(out.length, 600);
  assert.ok(out.every((r) => r.enabled));
  for (const call of client.calls) {
    assert.deepEqual(call.eq, ["enabled", true]);
    assert.equal(call.table, "sources");
  }
});

test("fetchAllSources 出错抛出（调用方各自决定容错）", async () => {
  const client = fakeClient([], { error: { message: "sources_lookup_failed" } });
  await assert.rejects(() => fetchAllSources(client, "id"), /sources_lookup_failed/);
});
