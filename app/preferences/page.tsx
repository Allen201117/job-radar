import { redirect } from "next/navigation";

// 2026-09-03：「关注与偏好」与「个人主页」功能重复（两处各挂一份简历画像面板），
// 按创始人要求统一为「个人主页」。这里保留路由做重定向，避免旧链接、书签与外部引用 404。
export default function PreferencesPage() {
  redirect("/me");
}
