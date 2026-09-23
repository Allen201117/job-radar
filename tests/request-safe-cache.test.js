const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

// 回归：unstable_cache 在动态请求里把「解码后的请求网址」拼进条目名 fetchUrl，Vercel 缓存服务把它放进请求头；
// 网址带中文 → 读写都在发出前抛错 → 永远不命中（vercel/next.js#76286，15.5 线未修）。
// 这里复刻那个约束：假缓存像真实服务一样把 fetchUrl 放进 Headers，放不进就当失败（Next 会吞掉，表现为 miss）。
const ROOT = path.join(__dirname, "..");
// Next 的服务端运行时启动时把 AsyncLocalStorage 挂到全局（node-environment），单测里手动挂上。
globalThis.AsyncLocalStorage ??= require("node:async_hooks").AsyncLocalStorage;
const { workAsyncStorage } = require("next/dist/server/app-render/work-async-storage.external");
const { workUnitAsyncStorage } = require("next/dist/server/app-render/work-unit-async-storage.external");
const { unstable_cache } = require("next/cache");
const { requestSafeCache } = loadTs(path.join(ROOT, "lib", "request-safe-cache.ts"));

function headerSafeCache() {
  const store = new Map();
  const log = { gets: [], sets: [], rejected: [] };
  const probe = (op, ctx) => {
    try {
      new Headers({ "x-cache-item-name": ctx.fetchUrl || "" });
      return true;
    } catch {
      log.rejected.push({ op, fetchUrl: ctx.fetchUrl });
      return false;
    }
  };
  return {
    log,
    isOnDemandRevalidate: false,
    async generateCacheKey(key) {
      return `k:${key.length}:${key.slice(-60)}`;
    },
    async get(key, ctx) {
      log.gets.push(ctx.fetchUrl);
      if (!probe("get", ctx)) return null; // 真实服务：请求发不出去 = miss
      const v = store.get(key);
      return v ? { value: v, isStale: false } : null;
    },
    async set(key, data, ctx) {
      log.sets.push(ctx.fetchUrl);
      if (!probe("set", ctx)) return; // 真实服务：写失败被 Next 吞成 warn
      store.set(key, data);
    },
  };
}

async function inRequest(url, incrementalCache, fn) {
  const workStore = {
    route: "/api/jobs/search",
    incrementalCache,
    nextFetchId: 1,
    isOnDemandRevalidate: false,
    isDraftMode: false,
    isRevalidate: false,
  };
  const u = new URL(url);
  const unit = { type: "request", url: { pathname: u.pathname, search: u.search }, implicitTags: { tags: ["_N_T_/api/jobs/search"] } };
  return workAsyncStorage.run(workStore, () =>
    workUnitAsyncStorage.run(unit, async () => {
      const r = await fn();
      await Promise.all(Object.values(workStore.pendingRevalidates || {})); // 响应后刷写（waitUntil）
      return r;
    }),
  );
}

const CJK_URL = "https://www.myjobradar.top/api/jobs/search?jobType=%E6%A0%A1%E6%8B%9B&city=%E5%8C%97%E4%BA%AC";

test("对照组：原生 unstable_cache 在中文网址下条目名放不进请求头 → 两次都回源（复现线上缺陷）", async () => {
  const cache = headerSafeCache();
  let calls = 0;
  const cached = unstable_cache(async (n) => ((calls += 1), n * 2), ["probe-raw"], { revalidate: 300 });
  for (let i = 0; i < 2; i++) await inRequest(CJK_URL, cache, () => cached(21));
  assert.equal(calls, 2, "缓存从未生效：每次都回源");
  assert.ok(cache.log.rejected.some((r) => /校招|北京/.test(r.fetchUrl)), JSON.stringify(cache.log.rejected));
});

test("requestSafeCache：同样的中文网址，条目名不带网址、能进请求头 → 第二次命中", async () => {
  const cache = headerSafeCache();
  let calls = 0;
  const cached = requestSafeCache(async (n) => ((calls += 1), n * 2), ["probe-safe"], { revalidate: 300 });
  const a = await inRequest(CJK_URL, cache, () => cached(21));
  const b = await inRequest(CJK_URL, cache, () => cached(21));
  assert.equal(a, 42);
  assert.equal(b, 42);
  assert.equal(calls, 1, "第二次应命中缓存");
  assert.deepEqual(cache.log.rejected, []);
  assert.ok(cache.log.sets.length === 1 && !/[^\x00-\xff]/.test(cache.log.sets[0]), JSON.stringify(cache.log.sets));
});

test("requestSafeCache：缓存键与原生 unstable_cache 相同（上线后已有条目照常命中，不用换 key）", async () => {
  const keys = [];
  const spy = { ...headerSafeCache(), async generateCacheKey(k) { keys.push(k); return k; } };
  const fn = async (n) => n;
  await inRequest("https://x.test/a?q=ascii", spy, () => unstable_cache(fn, ["same-key"], { revalidate: 60 })(1));
  await inRequest(CJK_URL, spy, () => requestSafeCache(fn, ["same-key"], { revalidate: 60 })(1));
  assert.equal(keys.length, 2);
  assert.equal(keys[0], keys[1]);
});

test("不在请求上下文里（单测 / 脚本）行为与原生一致：仍抛 incrementalCache missing，调用方的兜底照旧", async () => {
  const cached = requestSafeCache(async () => 1, ["no-store"], { revalidate: 60 });
  await assert.rejects(() => cached(), /incrementalCache missing/);
});

test("契约：app/ lib/ 下除包装本身外不许直接调用 unstable_cache（新代码会重新踩中文网址的坑）", () => {
  const offenders = [];
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(ts|tsx)$/.test(e.name) && p !== path.join(ROOT, "lib", "request-safe-cache.ts")) {
        const src = fs.readFileSync(p, "utf8");
        if (/\bunstable_cache\s*\(/.test(src) || /import\s*\{[^}]*\bunstable_cache\b[^}]*\}\s*from\s*["']next\/cache["']/.test(src)) {
          offenders.push(path.relative(ROOT, p));
        }
      }
    }
  };
  walk(path.join(ROOT, "app"));
  walk(path.join(ROOT, "lib"));
  assert.deepEqual(offenders, [], `改用 lib/request-safe-cache.ts 的 requestSafeCache：${offenders.join(", ")}`);
});
