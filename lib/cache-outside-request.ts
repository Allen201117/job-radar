// ============================================================
// 让 unstable_cache 的缓存条目名与「当前请求的 URL」脱钩。
//
// ⚠️ 病根（2026-09-23 线上实测）：Next 15 的 unstable_cache 在请求里被调用时，会把
// 「请求路径 + **解码后**的查询串」拼进缓存条目名（源码里的 fetchUrl，见
// node_modules/next/dist/server/web/spec-extension/unstable-cache.js 的 getFetchUrlPrefix），
// Vercel 的数据缓存再拿它去读写。**查询串里只要有一个非 ASCII 字符（?q=腾讯、?city=北京），
// 读和写都静默失败**：每个请求都现算一遍，不报错、不告警。
//   · /api/insights/library?zz=腾（一个和筛选无关的参数）→ 连续 6 次都重建索引，每次 5.5~7s
//   · /api/insights/library?zz=1                          → 21ms 命中，4 个不同实例拿到同一份
// 缓存键本身（keyParts + 参数）与 URL 无关，所以 ASCII 请求之间能互相命中，唯独中文请求永远落空。
//
// ✅ 修法：在「请求」这一层工作单元作用域之外调用缓存函数 —— Next 取不到请求上下文时，
// 条目名前缀为空，只剩缓存键。缓存键不变，命中的仍是同一份条目；请求级的
// workStore 仍在，所以后台重验证（stale-while-revalidate）照常挂在 waitUntil 上。
// 只对 type='request' 生效：预渲染 / 嵌套缓存作用域里 Next 要靠这层收集 revalidate 与 tags，不能跳。
//
// ⚠️ 依赖 Next 的内部模块（*.external 是 Next 刻意外置、全进程单例的那一类）。
// 升级 Next 时 tests/cache-outside-request.test.js 会用真实的 unstable_cache 复核一遍：
// 条目名里不许再出现请求的查询串。
// ============================================================
import { workUnitAsyncStorage } from "next/dist/server/app-render/work-unit-async-storage.external";

type ExitableStorage = {
  getStore?: () => { type?: string } | undefined;
  exit?: <R>(callback: () => R) => R;
};

export function callOutsideRequestScope<T>(fn: () => Promise<T>): Promise<T> {
  const storage = workUnitAsyncStorage as unknown as ExitableStorage | undefined;
  if (!storage || typeof storage.exit !== "function" || typeof storage.getStore !== "function") {
    return fn();
  }
  if (storage.getStore()?.type !== "request") return fn();
  return storage.exit(fn);
}
