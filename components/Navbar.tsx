import { getRequestUser } from "@/lib/auth";
import NavbarClient from "@/components/NavbarClient";

/**
 * 顶栏服务端外壳：从 middleware 注入的请求头零网络取当前用户，透传给客户端导航栏。
 *
 * 为什么要这层：改造前 NavbarClient 挂载后自己调 supabase.auth.getUser()，那是**浏览器直连
 * Supabase 所在区域（悉尼）**的一次跨洋往返，每次换页都跑一遍；而登录态几乎决定了顶栏所有
 * 显隐（求职范围切换、账号菜单、/me 入口）。改由服务端透传后零网络，首帧即正确登录态。
 *
 * 组件名与用法保持不变，因此 20 个引用点（各 page.tsx / loading.tsx，全部是服务端组件）
 * 都不需要改动。
 */
export default async function Navbar() {
  const user = await getRequestUser();
  return <NavbarClient initialEmail={user?.email ?? null} />;
}
