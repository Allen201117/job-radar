// unstable_cache 的缓存条目名不许带请求的查询串（lib/cache-outside-request.ts）。
//
// 2026-09-23 线上实测：Next 把「请求路径 + 解码后的查询串」拼进缓存条目名，Vercel 数据缓存拿它读写，
// 查询串里只要有中文，读写都静默失败 → /insights?q=腾讯 每次重建索引 6.3s。
// 这里直接跑 Next **真实的** unstable_cache，用一个假的 incrementalCache 截下它递给缓存层的条目名，
// 升级 Next 时这组断言会先红：别等线上又静默失去缓存才发现。
const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { AsyncLocalStorage } = require("node:async_hooks");

// Next 的 ALS 实例在模块加载时创建，运行时由 Next 服务端挂上 globalThis.AsyncLocalStorage；
// 测试里没有 Next 服务端，得先手动挂，否则拿到的是永远 getStore()=undefined 的假实现。
globalThis.AsyncLocalStorage = AsyncLocalStorage;

const { unstable_cache } = require("next/dist/server/web/spec-extension/unstable-cache");
const { workAsyncStorage } = require("next/dist/server/app-render/work-async-storage.external");
const { workUnitAsyncStorage } = require("next/dist/server/app-render/work-unit-async-storage.external");
const { loadTs } = require("./_load-ts");

const { callOutsideRequestScope } = loadTs(path.join(__dirname, "..", "lib", "cache-outside-request.ts"));

function fakeIncrementalCache({ staleValue } = {}) {
  const gets = [];
  const sets = [];
  return {
    gets,
    sets,
    isOnDemandRevalidate: false,
    async generateCacheKey(invocationKey) {
      return `key:${invocationKey.length}:${invocationKey.slice(-40)}`;
    },
    async get(cacheKey, ctx) {
      gets.push({ cacheKey, fetchUrl: ctx.fetchUrl });
      if (staleValue === undefined) return null;
      // 已过期的条目：unstable_cache 应当先把旧值还给调用方，再在后台重建。
      return { value: { kind: "FETCH", data: { body: JSON.stringify(staleValue) } }, isStale: true };
    },
    async set(cacheKey, _data, ctx) {
      sets.push({ cacheKey, fetchUrl: ctx.fetchUrl });
    },
  };
}

/** 模拟「一个带中文查询串的请求」里调用缓存函数。afterTasks = 交给 after()（即 waitUntil）的后台任务。 */
async function inRequest(search, fn, { staleValue } = {}) {
  const incrementalCache = fakeIncrementalCache({ staleValue });
  const afterTasks = [];
  const workStore = {
    incrementalCache,
    nextFetchId: 1,
    fetchCache: undefined,
    isOnDemandRevalidate: false,
    isDraftMode: false,
    route: "/insights",
    afterContext: { after: (task) => afterTasks.push(task) },
  };
  const requestStore = {
    type: "request",
    url: { pathname: "/insights", search },
    implicitTags: { tags: ["_N_T_/insights"] },
  };
  const result = await workAsyncStorage.run(workStore, () =>
    workUnitAsyncStorage.run(requestStore, fn),
  );
  // 响应结束前 Next 会等的那一批（接口路由的 sendResponse 就等它）：记下还剩几个。
  const leftForResponse = Object.keys(workStore.pendingRevalidates || {}).length;
  // 两处的后台任务（线上都由 waitUntil 托着）测试里手动等完，好断言写缓存的结果。
  await Promise.all(Object.values(workStore.pendingRevalidates || {}));
  await Promise.all(afterTasks);
  return { result, incrementalCache, afterTasks, leftForResponse };
}

const isAscii = (s) => /^[\x00-\x7f]*$/.test(s);

test("基线：直接调用时，Next 会把中文查询串拼进缓存条目名（这就是线上静默失效的原因）", async () => {
  const cached = unstable_cache(async () => ({ ok: 1 }), ["cache-outside-request-test-a"]);
  const { incrementalCache } = await inRequest("?q=%E8%85%BE%E8%AE%AF", () => cached());
  assert.equal(incrementalCache.gets.length, 1);
  assert.match(incrementalCache.gets[0].fetchUrl, /腾讯/);
  assert.equal(isAscii(incrementalCache.gets[0].fetchUrl), false);
});

test("callOutsideRequestScope：条目名里不再有请求 URL，读写都是纯 ASCII", async () => {
  const cached = unstable_cache(async () => ({ ok: 1 }), ["cache-outside-request-test-b"]);
  const { result, incrementalCache } = await inRequest("?q=%E8%85%BE%E8%AE%AF&city=%E5%8C%97%E4%BA%AC", () =>
    callOutsideRequestScope(() => cached()),
  );
  assert.deepEqual(result, { ok: 1 });
  assert.equal(incrementalCache.gets.length, 1, "仍然先查缓存");
  assert.equal(incrementalCache.sets.length, 1, "未命中时仍然写回缓存");
  for (const call of [...incrementalCache.gets, ...incrementalCache.sets]) {
    assert.ok(isAscii(call.fetchUrl), `条目名必须是 ASCII：${call.fetchUrl}`);
    assert.doesNotMatch(call.fetchUrl, /insights|q=|city=/, "条目名不该再带请求路径和查询串");
  }
});

test("callOutsideRequestScope：不同查询串命中的是同一个缓存键（与 URL 无关）", async () => {
  const cached = unstable_cache(async (bucket) => ({ bucket }), ["cache-outside-request-test-c"]);
  const a = await inRequest("?q=%E8%85%BE", () => callOutsideRequestScope(() => cached(7)));
  const b = await inRequest("", () => callOutsideRequestScope(() => cached(7)));
  assert.equal(a.incrementalCache.gets[0].cacheKey, b.incrementalCache.gets[0].cacheKey);
  assert.equal(a.incrementalCache.gets[0].fetchUrl, b.incrementalCache.gets[0].fetchUrl);
});

test("基线：条目过期时，后台重建挂在请求上，响应结束前要等它（接口路由就这样被拖住）", async () => {
  const cached = unstable_cache(async () => ({ v: "new" }), ["cache-outside-request-test-d"], { revalidate: 600 });
  const { result, leftForResponse } = await inRequest("", () => cached(), { staleValue: { v: "old" } });
  assert.deepEqual(result, { v: "old" }, "过期条目先把旧值还回来");
  assert.equal(leftForResponse, 1, "重建挂在 pendingRevalidates 上 —— Next 15.5 的接口路由会等它");
});

test("callOutsideRequestScope：过期条目照样先回旧值，后台重建挪给 after()，不再挡响应", async () => {
  const cached = unstable_cache(async () => ({ v: "new" }), ["cache-outside-request-test-e"], { revalidate: 600 });
  const { result, incrementalCache, afterTasks, leftForResponse } = await inRequest(
    "?q=%E8%85%BE%E8%AE%AF",
    () => callOutsideRequestScope(() => cached()),
    { staleValue: { v: "old" } },
  );
  assert.deepEqual(result, { v: "old" }, "不等重建，立刻拿旧值");
  assert.equal(leftForResponse, 0, "响应结束前不该再有要等的缓存任务");
  assert.equal(afterTasks.length, 1, "后台重建交给 after()（waitUntil）");
  assert.equal(incrementalCache.sets.length, 1, "后台重建完成后照样写回缓存");
  assert.ok(isAscii(incrementalCache.sets[0].fetchUrl));
});

test("callOutsideRequestScope：只挪本次调用新挂的任务，别人挂的原样留着", async () => {
  const cached = unstable_cache(async () => ({ v: 1 }), ["cache-outside-request-test-f"]);
  const other = Promise.resolve("someone-else");
  const { leftForResponse, afterTasks } = await inRequest("", async () => {
    const { workAsyncStorage: was } = require("next/dist/server/app-render/work-async-storage.external");
    was.getStore().pendingRevalidates = { others: other };
    return callOutsideRequestScope(() => cached());
  });
  assert.equal(leftForResponse, 1, "别人挂的那一个还在");
  assert.equal(afterTasks.length, 1, "本次调用的缓存写入被挪走");
});

test("callOutsideRequestScope：只跳过 request 作用域，预渲染等作用域原样保留", async () => {
  const prerenderStore = { type: "prerender", revalidate: 60, tags: null };
  const seen = await workUnitAsyncStorage.run(prerenderStore, () =>
    callOutsideRequestScope(async () => workUnitAsyncStorage.getStore()),
  );
  assert.equal(seen, prerenderStore, "预渲染时 Next 要靠这层收集 revalidate/tags，不能跳出去");

  const requestStore = { type: "request", url: { pathname: "/x", search: "" } };
  const inside = await workUnitAsyncStorage.run(requestStore, () =>
    callOutsideRequestScope(async () => workUnitAsyncStorage.getStore()),
  );
  assert.equal(inside, undefined);
});

test("callOutsideRequestScope：不在任何请求里时直接调用", async () => {
  assert.equal(await callOutsideRequestScope(async () => 42), 42);
});
