import { getRequestUser } from "@/lib/auth";
import LandingClient from "./landing-client";

export const dynamic = "force-dynamic";

export default async function LandingPage() {
  // 只需要「有没有登录」这一个布尔值：读 middleware 注入的请求头即可，零网络。
  // 别在这里 supabase.auth.getUser()——那是落地页每次访问一次跨洋往返（Supabase 在悉尼），
  // 而落地页是新用户的第一印象页。
  const user = await getRequestUser();

  return <LandingClient loggedIn={!!user} />;
}
