import { NextResponse, type NextRequest } from "next/server";
import { createServerSupabase } from "./auth";
import { verifyRequestClaims, type VerifiedUser } from "./auth-claims";

/** 廉价登录态判断（**不联网、不验 JWT**）：看有没有 Supabase 会话 cookie（sb-*-auth-token，含分片）。
 * 仅用于「只跳转/只读、不碰用户敏感数据」的热路径（点击校验门 /api/jobs/go、展示校验 /api/jobs/liveness-check），
 * 省掉 getUser() 的网络往返（~0.3s/次）。需要真实 user 身份或授权的接口仍必须用 requireUser()/requireAdmin()。 */
export function hasSessionCookie(request: NextRequest): boolean {
  return request.cookies
    .getAll()
    .some((c) => c.name.startsWith("sb-") && c.name.includes("auth-token"));
}

type ServerSupabase = Awaited<ReturnType<typeof createServerSupabase>>;

/** `user` 只暴露 id / email：全仓库服务端对 user 的使用即 `user.id`（124 处）与 `user.email`（2 处），
 * 没有任何一处需要 getUser() 独有的字段，因此本地验签拿到的 JWT claims 已完全覆盖。 */
export type ApiAuthResult =
  | { user: VerifiedUser; supabase: ServerSupabase; error?: never }
  | { user?: never; supabase?: never; error: NextResponse };

export async function requireUser(): Promise<ApiAuthResult> {
  const supabase = await createServerSupabase();
  // 本地 JWT 验签，零网络。/api/* 不经 middleware，各路由自行调用本函数——
  // 改造前这里是每个 API 各一次跨洋 getUser()，是「页面出来了但一直在转圈」的主因。
  const user = await verifyRequestClaims(supabase);
  if (!user) {
    return {
      error: NextResponse.json(
        { ok: false, error: "Unauthorized" },
        { status: 401 },
      ),
    };
  }
  return { user, supabase };
}

export async function requireAdmin(): Promise<ApiAuthResult> {
  const auth = await requireUser();
  if (auth.error) return auth;

  const { data: profileRow } = await auth.supabase
    .from("profiles")
    .select("role")
    .eq("id", auth.user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return {
      error: NextResponse.json(
        { ok: false, error: "forbidden" },
        { status: 403 },
      ),
    };
  }
  return auth;
}

export function assertOwnership(
  row: Record<string, unknown> | null | undefined,
  userId: string,
  ownerKey = "user_id",
): NextResponse | null {
  if (row?.[ownerKey] === userId) return null;
  return NextResponse.json(
    { ok: false, error: "forbidden" },
    { status: 403 },
  );
}
