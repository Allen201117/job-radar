import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  // setAll 刷新出来的会话 cookie：① 回写浏览器（Set-Cookie）；② 并入转发给页面的请求 cookie 头，
  // 确保「本次请求刚好触发 token 刷新」时，页面在同一请求内就能用上新会话（不丢一拍、不会用到过期 token）。
  const cookiesToApply: { name: string; value: string; options: Record<string, unknown> }[] = [];

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: Record<string, unknown> }[]) {
          cookiesToSet.forEach(({ name, value }) => {
            request.cookies.set(name, value);
          });
          cookiesToApply.push(...cookiesToSet);
        },
      },
    },
  );

  // 全站唯一一次安全级验证（同时按需刷新会话）。受保护页面不再重复调用 getUser。
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // 转发给页面的请求头：注入「已验证」的 user id/email——页面零网络读取（见 lib/auth.getRequestUser），
  // 省掉每次导航在页面里重复一次 getUser() 网络往返（冷启动下这是最大的串行阻塞之一）。
  // 信任边界只在此处：先删外部可能伪造的同名头，再仅用本次验证结果回填。
  // 注意这些是「请求头」，仅服务端渲染可见，不会出现在给浏览器的响应里，不泄露。
  const requestHeaders = new Headers(request.headers);
  requestHeaders.delete("x-user-id");
  requestHeaders.delete("x-user-email");
  // 用 setAll 刷新后的完整 cookie 集重写 cookie 头（request.cookies 已被上面的 setAll 更新过）。
  const cookieHeader = request.cookies
    .getAll()
    .map(({ name, value }) => `${name}=${value}`)
    .join("; ");
  if (cookieHeader) requestHeaders.set("cookie", cookieHeader);
  if (user) {
    requestHeaders.set("x-user-id", user.id);
    if (user.email) requestHeaders.set("x-user-email", user.email);
  }

  // 会话刷新出来的 cookie 统一回写到真正返回的 response（含 redirect 分支，避免刷新丢失）。
  const withCookies = (res: NextResponse) => {
    cookiesToApply.forEach(({ name, value, options }) => res.cookies.set(name, value, options));
    return res;
  };

  const isLoginPage = request.nextUrl.pathname === "/login";
  const isAuthCallback = request.nextUrl.pathname.startsWith("/auth");
  // 宣传页 `/` 对未登录访客公开，作为首次访问入口。
  const isLanding = request.nextUrl.pathname === "/";

  if (!user && !isLoginPage && !isAuthCallback && !isLanding) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return withCookies(NextResponse.redirect(url));
  }

  if (user && isLoginPage) {
    const url = request.nextUrl.clone();
    url.pathname = "/today";
    return withCookies(NextResponse.redirect(url));
  }

  return withCookies(NextResponse.next({ request: { headers: requestHeaders } }));
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
