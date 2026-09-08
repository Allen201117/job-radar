// I4a 回归：/api/insights/dispute/resolve 必须先下架被申诉条目、成功后才落申诉终态。
//
// 旧实现顺序反过来：先把 insight_disputes.status 写成 upheld，再下架条目。若下架
// 那一步失败，路由返回 500，但申诉状态已经提交成功——admin 的 GET 只拉
// status='open' 的申诉列表，这条申诉已经从队列里消失，留下「申诉已成立、条目仍
// active」的不一致态，且没有任何补偿或重试入口。
//
// 这里用可控失败的 fake service 校验：任一步失败都不能让申诉状态被错误地提前提交。
const assert = require("node:assert/strict");
const test = require("node:test");
const { loadRoute } = require("./route-test-utils");

const ADMIN = { id: "admin-1", email: "admin@example.com" };

function makeService({ dispute, itemUpdateError = null, disputeUpdateError = null }) {
  const calls = [];
  const service = {
    calls,
    from(table) {
      if (table === "insight_disputes") {
        const chain = {
          _mode: null,
          select() {
            chain._mode = "select";
            return chain;
          },
          update(payload) {
            chain._mode = "update";
            chain._payload = payload;
            return chain;
          },
          eq(col, val) {
            chain._id = val;
            return chain;
          },
          single: async () => {
            calls.push(["select", "insight_disputes", chain._id]);
            return { data: dispute, error: null };
          },
          then(resolve, reject) {
            calls.push(["update", "insight_disputes", chain._payload]);
            return Promise.resolve({ error: disputeUpdateError }).then(resolve, reject);
          },
        };
        return chain;
      }
      if (table === "insight_items") {
        const chain = {
          _payload: null,
          update(payload) {
            chain._payload = payload;
            return chain;
          },
          eq(col, val) {
            chain._id = val;
            return chain;
          },
          then(resolve, reject) {
            calls.push(["update", "insight_items", chain._id, chain._payload]);
            return Promise.resolve({ error: itemUpdateError }).then(resolve, reject);
          },
        };
        return chain;
      }
      throw new Error(`unexpected table ${table}`);
    },
  };
  return service;
}

function loadResolveRoute(service) {
  return loadRoute("app/api/insights/dispute/resolve/route.ts", {
    "@/lib/apiAuth": {
      requireAdmin: async () => ({ user: ADMIN }),
    },
    "@/lib/supabaseService": {
      createServiceClient: () => service,
    },
  });
}

function request(body) {
  return { json: async () => body };
}

test("upheld resolution retires the item before marking the dispute upheld", async () => {
  const service = makeService({ dispute: { id: "d1", item_id: "item-1", status: "open" } });
  const route = loadResolveRoute(service);

  const res = await route.POST(request({ dispute_id: "d1", resolution: "upheld" }));
  const body = await res.json();

  assert.equal(res.status, 200);
  assert.equal(body.ok, true);
  // 顺序断言：insight_items 的 update 必须先于 insight_disputes 的 update 提交。
  const itemsIdx = service.calls.findIndex((c) => c[0] === "update" && c[1] === "insight_items");
  const disputeUpdateIdx = service.calls.findIndex((c) => c[0] === "update" && c[1] === "insight_disputes");
  assert.ok(itemsIdx >= 0 && disputeUpdateIdx >= 0, "两步 update 都应发生");
  assert.ok(itemsIdx < disputeUpdateIdx, `条目下架必须先于申诉终态提交，实际顺序：${JSON.stringify(service.calls)}`);
  assert.equal(service.calls[disputeUpdateIdx][2].status, "upheld");
});

test("I4 回归：条目下架失败时，申诉状态绝不能被提前写成 upheld", async () => {
  const service = makeService({
    dispute: { id: "d2", item_id: "item-2", status: "open" },
    itemUpdateError: { message: "db down" },
  });
  const route = loadResolveRoute(service);

  const res = await route.POST(request({ dispute_id: "d2", resolution: "upheld" }));
  const body = await res.json();

  assert.equal(res.status, 500);
  assert.equal(body.ok, false);
  // 关键断言：insight_disputes 的 update 从未被提交——旧实现会在这里先把
  // 申诉写成 upheld，导致它从 admin 的 open 队列消失、但条目仍是 active。
  const disputeUpdateCalls = service.calls.filter((c) => c[0] === "update" && c[1] === "insight_disputes");
  assert.equal(disputeUpdateCalls.length, 0, "条目下架失败时不能提交任何申诉状态更新");
});

test("条目下架成功但申诉终态提交失败时仍返回失败（可安全重试）", async () => {
  const service = makeService({
    dispute: { id: "d3", item_id: "item-3", status: "open" },
    disputeUpdateError: { message: "conflict" },
  });
  const route = loadResolveRoute(service);

  const res = await route.POST(request({ dispute_id: "d3", resolution: "upheld" }));
  const body = await res.json();

  assert.equal(res.status, 500);
  assert.equal(body.ok, false);
  // 条目已经正确下架（这是安全的中间态：重试会把 dispute 也补上，且重复下架是幂等的）。
  const itemUpdate = service.calls.find((c) => c[0] === "update" && c[1] === "insight_items");
  assert.ok(itemUpdate, "条目下架这一步应已提交成功");
});

test("rejected resolution never touches insight_items", async () => {
  const service = makeService({ dispute: { id: "d4", item_id: "item-4", status: "open" } });
  const route = loadResolveRoute(service);

  const res = await route.POST(request({ dispute_id: "d4", resolution: "rejected" }));
  const body = await res.json();

  assert.equal(res.status, 200);
  assert.equal(body.ok, true);
  const itemCalls = service.calls.filter((c) => c[1] === "insight_items");
  assert.equal(itemCalls.length, 0, "驳回申诉不该改动 insight_items");
  const disputeUpdate = service.calls.find((c) => c[0] === "update" && c[1] === "insight_disputes");
  assert.equal(disputeUpdate[2].status, "rejected");
});
