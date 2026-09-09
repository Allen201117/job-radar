// I3 回归：/api/insights/admin 的 attachSources 单条来源写入失败时，
// POST 处理器不许仍然返回 ok:true。
//
// 旧实现里 attachSources 遇到 insert 失败只 console.error 然后 continue，调用方
// 无论失败多少条都原样返回 {ok:true}——admin 表单看到「保存成功」，实际有来源
// 悄悄没写进去，且没有任何信号提示需要重试。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadRoute } = require("./route-test-utils");

const ADMIN = { id: "admin-1", email: "admin@example.com" };

function chainable(result) {
  const chain = {
    select() {
      return chain;
    },
    eq() {
      return chain;
    },
    in() {
      return chain;
    },
    upsert() {
      return chain;
    },
    insert(payload) {
      chain._payload = payload;
      return chain;
    },
    update(payload) {
      chain._payload = payload;
      return chain;
    },
    delete() {
      return chain;
    },
    single: async () => result,
    then(resolve, reject) {
      return Promise.resolve(result).then(resolve, reject);
    },
  };
  return chain;
}

function makeService({ sourceInsertShouldFail = false } = {}) {
  const calls = [];
  return {
    calls,
    from(table) {
      if (table === "company_profiles") {
        return chainable({ data: { id: "company-1" }, error: null });
      }
      if (table === "insight_items") {
        return chainable({ data: { id: "item-1" }, error: null });
      }
      if (table === "insight_sources") {
        calls.push(["insert", "insight_sources"]);
        return sourceInsertShouldFail
          ? chainable({ data: null, error: { message: "insert failed" } })
          : chainable({ data: { id: "src-1" }, error: null });
      }
      if (table === "insight_item_sources") {
        calls.push(["insert", "insight_item_sources"]);
        return chainable({ data: null, error: null });
      }
      throw new Error(`unexpected table ${table}`);
    },
  };
}

function loadAdminRoute(service) {
  return loadRoute("app/api/insights/admin/route.ts", {
    "@/lib/apiAuth": { requireAdmin: async () => ({ user: ADMIN }) },
    "@/lib/supabaseService": { createServiceClient: () => service },
    "@/lib/insight-verification": {
      evaluateInsight: () => ({ displayable: true, failure_reason: null }),
      passesDeidentifiedGate: () => true,
      passesGradeGate: () => true,
      passesAssertionLint: () => true,
      hasTimeWindow: () => true,
    },
    "@/lib/insight-bundle": {
      INSIGHT_DIMENSIONS: ["culture"],
      ITEM_COLUMNS: "id",
      flattenSources: () => [],
    },
    "@/lib/industries": { normalizeIndustry: () => null },
  });
}

function request(body) {
  return { json: async () => body };
}

function newItemPayload(overrides = {}) {
  return {
    company: "测试公司",
    dimension: "culture",
    grade: "experience",
    content: "测试正文内容",
    // status=retired 不需要过校验门（只有落成 active 才必须过门），
    // 让这个用例只聚焦 attachSources 的失败传播，不掺进验证门逻辑。
    status: "retired",
    sources: [{ url: "https://a.example/1" }],
    ...overrides,
  };
}

test("一条来源写入失败时，POST 不得返回 ok:true", async () => {
  const service = makeService({ sourceInsertShouldFail: true });
  const route = loadAdminRoute(service);

  const res = await route.POST(request(newItemPayload()));
  const body = await res.json();

  assert.notEqual(body.ok, true, "有来源没写进去就不能说 ok:true");
  assert.equal(body.failed_sources, 1);
  assert.equal(body.item_id, "item-1", "条目本身已经存了，item_id 仍应带出来供调用方定位");
});

test("来源全部写入成功时仍返回 ok:true", async () => {
  const service = makeService({ sourceInsertShouldFail: false });
  const route = loadAdminRoute(service);

  const res = await route.POST(request(newItemPayload()));
  const body = await res.json();

  assert.equal(body.ok, true);
  assert.equal(body.item_id, "item-1");
});

test("编辑已有条目（body.id 存在）时来源写入失败同样不能静默", async () => {
  const service = makeService({ sourceInsertShouldFail: true });
  const route = loadAdminRoute(service);

  const res = await route.POST(request(newItemPayload({ id: "existing-item" })));
  const body = await res.json();

  assert.notEqual(body.ok, true);
  assert.equal(body.failed_sources, 1);
});
