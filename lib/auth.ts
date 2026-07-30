import { createServerClient } from "@supabase/ssr";
import { cookies, headers } from "next/headers";

export async function createServerSupabase() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: Record<string, unknown> }[]) {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        },
      },
    },
  );
}

// 读取「中间件已验证」的当前用户（零网络）。middleware 用 getUser() 验证后把 id/email 注入请求头，
// 受保护页面直接读，省掉每次导航重复的 getUser 网络往返。
// 仅在 middleware 覆盖的「页面路由」可用——/api/* 不经 middleware，仍需自行 getUser()/requireUser()。
// 安全性：伪造的同名请求头在 middleware 入口被删除、只由验证结果回填；DB 侧 RLS 用已验证 JWT 二次兜底。
export async function getRequestUser(): Promise<{ id: string; email: string | undefined } | null> {
  const h = await headers();
  const id = h.get("x-user-id");
  if (!id) return null;
  return { id, email: h.get("x-user-email") ?? undefined };
}

export async function getSession() {
  const supabase = await createServerSupabase();
  const { data } = await supabase.auth.getSession();
  return data.session;
}

/** ⚠️ 走网络到 Supabase 所在区域（悉尼）。**只在确实需要 Auth 服务器上权威最新用户记录时用**
 * （如刚改过邮箱、要看封禁状态）。判断「当前是谁」一律用 getRequestUser()（页面）或
 * lib/apiAuth.requireUser()（API），它们走本地 JWT 验签、零网络。详见 lib/auth-claims.ts。 */
export async function getUser() {
  const supabase = await createServerSupabase();
  const { data } = await supabase.auth.getUser();
  return data.user;
}

export async function getProfile() {
  // 取 id 用零网络的请求头，不再为此跑一次跨洋 getUser()——isAdmin() 经由本函数，
  // 而它是 /sources、/admin/insights、/admin/health 三个页面的入口门。
  const user = await getRequestUser();
  if (!user) return null;
  const supabase = await createServerSupabase();
  const { data } = await supabase
    .from("profiles")
    .select("*")
    .eq("id", user.id)
    .single();
  return data;
}

export async function isAdmin() {
  const profile = await getProfile();
  return profile?.role === "admin";
}
