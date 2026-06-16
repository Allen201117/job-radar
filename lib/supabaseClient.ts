import { createBrowserClient as createSupabaseBrowserClient } from "@supabase/ssr";

// 浏览器端单例：每张 JobCard 渲染时都会调用本工厂。重复 new 客户端会各自创建 auth 监听 /
// storage 访问，在「岗位库」一次展示几百张卡片时累积成可观的内存 + CPU 负担（也是页面卡顿
// 诱因之一）。复用同一实例即可——supabase-js 浏览器客户端本就设计为单例使用。
let browserClient: ReturnType<typeof createSupabaseBrowserClient> | null = null;

export function createBrowserClient() {
  if (browserClient) return browserClient;
  browserClient = createSupabaseBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
  return browserClient;
}
