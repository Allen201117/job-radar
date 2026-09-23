// ============================================================
// 让 unstable_cache 的缓存条目名与「当前请求的 URL」脱钩，并且后台重建不挡响应。
//
// ⚠️ 病根一（2026-09-23 线上实测）：Next 15 的 unstable_cache 在请求里被调用时，会把
// 「请求路径 + **解码后**的查询串」拼进缓存条目名（源码里的 fetchUrl，见
// node_modules/next/dist/server/web/spec-extension/unstable-cache.js 的 getFetchUrlPrefix），
// Vercel 的数据缓存再拿它去读写。**查询串里只要有一个非 ASCII 字符（?q=腾讯、?city=北京），
// 读和写都静默失败**：每个请求都现算一遍，不报错、不告警。
//   · /api/insights/library?zz=腾（一个和筛选无关的参数）→ 连续 6 次都重建索引，每次 5.5~7s
//   · /api/insights/library?zz=1                          → 21ms 命中，4 个不同实例拿到同一份
// 缓存键本身（keyParts + 参数）与 URL 无关，所以 ASCII 请求之间能互相命中，唯独中文请求永远落空。
// ✅ 修法：在「请求」这一层工作单元作用域之外调用缓存函数 —— Next 取不到请求上下文时，
// 条目名前缀为空，只剩缓存键。缓存键不变，命中的仍是同一份条目。
// 只对 type='request' 生效：预渲染 / 嵌套缓存作用域里 Next 要靠这层收集 revalidate 与 tags，不能跳。
// 代价：这些条目不再挂页面路径的隐式标签，`revalidatePath` 管不到它们，只认显式 `tags`（本站只用 revalidateTag）。
//
// ⚠️ 病根二（同日实测）：条目过期后，unstable_cache 把后台重建挂在请求的 pendingRevalidates 上。
// 页面渲染会把它交给 waitUntil，不挡响应；**接口路由（Route Handler）却会等它跑完才结束响应** ——
// Next 15.5 的 build/templates/app-route.js 先 `ctx.waitUntil(pending)`、清掉的只是局部变量，
// 又把原 promise 传给 sendResponse，后者等它完成才 res.end()。线上：过期后第一个接口请求
// 取索引只花 56ms，响应却拖到 6.2s（正好等完一次重建）。
// ✅ 修法：调用结束后，把**这次调用**新挂上的后台任务（重建 / 缓存写入）挪给 `after()`——
// 它直接交给 waitUntil，不经过 sendResponse。页面路径同样适用（本来也是 waitUntil）。
// 挪走之后同一请求里再调一次同一个键会再触发一次重建（Next 按这个表去重）；本站每请求只调一次。
//
// ⚠️ 依赖 Next 的内部模块（*.external 是 Next 刻意外置、全进程单例的那一类）与 workStore 的内部字段。
// 字段对不上时两处都退回 Next 原本的行为（最坏是回到修之前），不会出错。
// 升级 Next 时 tests/cache-outside-request.test.js 会用真实的 unstable_cache 复核这两条。
// ============================================================
import { after } from "next/server";
import { workAsyncStorage } from "next/dist/server/app-render/work-async-storage.external";
import { workUnitAsyncStorage } from "next/dist/server/app-render/work-unit-async-storage.external";

type ExitableStorage = {
  getStore?: () => { type?: string } | undefined;
  exit?: <R>(callback: () => R) => R;
};

type PendingStore = { pendingRevalidates?: Record<string, Promise<unknown>> };

export async function callOutsideRequestScope<T>(fn: () => Promise<T>): Promise<T> {
  const storage = workUnitAsyncStorage as unknown as ExitableStorage | undefined;
  if (!storage || typeof storage.exit !== "function" || typeof storage.getStore !== "function") {
    return fn();
  }
  if (storage.getStore()?.type !== "request") return fn();

  const workStore = (workAsyncStorage as { getStore?: () => unknown }).getStore?.() as PendingStore | undefined;
  const alreadyPending = new Set(Object.keys(workStore?.pendingRevalidates ?? {}));
  const result = await storage.exit(fn);
  deferNewPendingWork(workStore, alreadyPending);
  return result;
}

function deferNewPendingWork(workStore: PendingStore | undefined, alreadyPending: Set<string>) {
  const pending = workStore?.pendingRevalidates;
  if (!pending) return;
  const keys = Object.keys(pending).filter((key) => !alreadyPending.has(key));
  if (keys.length === 0) return;
  const tasks = keys.map((key) => pending[key]);
  for (const key of keys) delete pending[key];
  try {
    after(Promise.allSettled(tasks));
  } catch (error: any) {
    // 按理不会发生（已确认在 request 作用域里）；真发生就放回去，退回 Next 原本的处理。
    keys.forEach((key, i) => {
      pending[key] = tasks[i];
    });
    console.warn("[cache-outside-request] after() 不可用，后台缓存任务交回 Next 处理", error?.message || error);
  }
}
