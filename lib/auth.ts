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

export async function getUser() {
  const supabase = await createServerSupabase();
  const { data } = await supabase.auth.getUser();
  return data.user;
}

export async function requireUser() {
  const user = await getUser();
  if (!user) throw new Error("Unauthorized");
  return user;
}

export async function getProfile() {
  const user = await getUser();
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
