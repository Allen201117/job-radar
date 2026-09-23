// 跨实例数据缓存的唯一入口：新代码一律用 requestSafeCache，不要直接调 next/cache 的 unstable_cache
// （tests/request-safe-cache.test.js 有契约断言守着）。
//
// ❌ 现象（2026-09-23 线上实锤）：带中文筛选的搜索（校招 / 实习 / 任何城市 / 中文公司名），「真实总数」计数每次都现算
//    （冷 1.3~5s），「不加筛选」那条却稳定命中缓存。同一条计数只在网址后多挂一个无关的 `&zz=中`，尾段就从 6~52ms 变成
//    678~1,738ms——算的是同一个数，差别只在网址。
// ✅ 根因：unstable_cache 在动态请求里把「解码后的请求网址」拼进缓存条目名（fetchUrl），Vercel 的缓存服务把它放进
//    HTTP 请求头；请求头只能是 Latin-1，含中文时读、写都在发出前抛错，被 Next 吞成一行 warn → 永远不命中、每次回源、不报错。
//    Next 官方缺陷 vercel/next.js#76286，修复 PR #96937（encodeHeaderSafe）只进了 16.x（16.3.6 有），
//    15.5 线到 15.5.26 都没有 backport。
// ✅ 这里的绕法：动态请求里让缓存调用脱离当前 work unit（lib/cache-outside-request.ts 的 callOutsideRequestScope，
//    同一天洞察库那条线独立查到同一个根因写的；这里只是把它挪到「定义处」，每次调用都自动走，不靠调用方记得包），
//    条目名退回不带网址的形式。
//    · 缓存键不变（= 函数源码 + keyParts + 参数的哈希，与网址无关）→ 已有条目照常命中，不用换 key。
//    · workAsyncStorage 仍在：incrementalCache 与待写入的 pendingRevalidates（响应后 waitUntil 刷写）照常工作。
//    · 代价：条目不再挂页面路径的隐式标签，revalidatePath 失效不到它们——本仓库没有任何 revalidatePath，
//      显式 tags（revalidateTag）照常生效。
//    · 只在 type === "request" 时脱离；构建期预渲染（prerender*）条目名本来就是路由模式（纯 ASCII），且要靠
//      work unit 收集 revalidate / tags，保持原样。
// ⚠️ 升到 Next ≥16.3 后这层可以删，改回直接用 unstable_cache（删之前先确认官方修复仍在）。
import { unstable_cache } from "next/cache";
import { callOutsideRequestScope } from "./cache-outside-request";

type AnyAsyncFn = (...args: any[]) => Promise<any>;
type CacheOptions = Parameters<typeof unstable_cache>[2];

export function requestSafeCache<T extends AnyAsyncFn>(cb: T, keyParts?: string[], options?: CacheOptions): T {
  const cached = unstable_cache(cb, keyParts, options);
  const safe = (...args: Parameters<T>) => callOutsideRequestScope(() => cached(...args));
  return safe as T;
}
