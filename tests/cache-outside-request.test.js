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

function fakeIncrementalCache() {
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
      return null;
    },
    async set(cacheKey, _data, ctx) {
      sets.push({ cacheKey, fetchUrl: ctx.fetchUrl });
    },
  };
}

/** 模拟「一个带中文查询串的页面请求」里调用缓存函数。 */
async function inRequest(search, fn) {
  const incrementalCache = fakeIncrementalCache();
  const workStore = {
    incrementalCache,
    nextFetchId: 1,
    fetchCache: undefined,
    isOnDemandRevalidate: false,
    isDraftMode: false,
    route: "/insights",
  };
  const requestStore = {
    type: "request",
    url: { pathname: "/insights", search },
    implicitTags: { tags: ["_N_T_/insights"] },
  };
  const result = await workAsyncStorage.run(workStore, () =>
    workUnitAsyncStorage.run(requestStore, fn),
  );
  // 写缓存是挂在 pendingRevalidates 上的（线上由 waitUntil 等），测试里手动等完。
  await Promise.all(Object.values(workStore.pendingRevalidates || {}));
  return { result, incrementalCache };
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
