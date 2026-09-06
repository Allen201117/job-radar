// 「一键设目标」：/today 热门兜底位上的两步转化（选行业 → 选岗位方向），零表单写进偏好。
//
// 为什么不复用 PUT /api/preferences：那个是**整份替换**（parsePreferencesInput 会把没传的字段
// 归一成空数组），用它来存「一个行业」会把用户简历解析出来的城市/技能一并抹掉。
// 这里只**并集追加**这两个字段，其余一列不碰。
//
// ⚠️ 两个字段都走服务端白名单，不接受任意文本：
//   · industry 必须是必投清单的行业（与 /campus、缺口台账同一份口径）；
//   · roles 必须是 lib/quick-start-roles 里的规范词——桶名之类的词写进去只会让看板更空
//     （实测 keywordMatchTier("研发","后台开发") = null，见该文件注释）。
import { NextResponse } from "next/server";
import { requireUser } from "@/lib/apiAuth";
import { buildRadarProfile, profileReadiness } from "@/lib/opportunities/profile";
import { MUST_APPLY_INDUSTRIES } from "@/lib/must-apply-list";
import { isQuickStartRole, QUICK_START_MAX_ROLES } from "@/lib/quick-start-roles";
import type { CandidateProfile, UserPreferences } from "@/lib/types";

export const runtime = "nodejs";

/** target_roles / target_industries 与 PUT 同口径的上限，避免这条旁路把数组撑爆。 */
const MAX_ITEMS = 30;

function mergeUnique(existing: unknown, incoming: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of [...(Array.isArray(existing) ? existing : []), ...incoming]) {
    if (typeof raw !== "string") continue;
    const value = raw.trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
    if (out.length >= MAX_ITEMS) break;
  }
  return out;
}

export async function POST(request: Request) {
  const auth = await requireUser();
  if (auth.error) return auth.error;
  const { supabase, user } = auth;

  const body = await request.json().catch(() => null);
  const industryRaw = typeof (body as any)?.industry === "string" ? (body as any).industry.trim() : "";
  const rolesRaw = Array.isArray((body as any)?.roles) ? (body as any).roles : [];

  const industry = MUST_APPLY_INDUSTRIES.includes(industryRaw) ? industryRaw : "";
  const roles = rolesRaw
    .filter(isQuickStartRole)
    .map((r: string) => r.trim())
    .slice(0, QUICK_START_MAX_ROLES);

  // 一个都没通过白名单 = 请求本身有问题，别静默写一次空 upsert 然后回 ok。
  if (!industry && roles.length === 0) {
    return NextResponse.json({ ok: false, error: "nothing_to_save" }, { status: 400 });
  }

  const { data: existing, error: readErr } = await supabase
    .from("user_preferences")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();
  if (readErr) {
    console.error("[preferences/quick-start] read failed:", readErr.message);
    return NextResponse.json({ ok: false, error: "preferences_unavailable" }, { status: 503 });
  }

  const patch: Record<string, unknown> = {};
  if (industry) patch.target_industries = mergeUnique(existing?.target_industries, [industry]);
  if (roles.length) patch.target_roles = mergeUnique(existing?.target_roles, roles);

  const { error: upErr } = await supabase
    .from("user_preferences")
    .upsert({ user_id: user.id, ...patch }, { onConflict: "user_id" });
  if (upErr) {
    console.error("[preferences/quick-start] upsert failed:", upErr.message);
    return NextResponse.json({ ok: false, error: "preferences_unavailable" }, { status: 503 });
  }

  // 回读画像就绪与否：前端靠它决定「是否该刷新页面切成精筛结果」。
  // ⚠️ 用合并**之后**的值算，不要用请求体——请求体不含用户原有的关键词/关注公司。
  const { data: cand } = await supabase
    .from("candidate_profiles")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();
  const merged = { ...(existing || {}), user_id: user.id, ...patch } as UserPreferences;
  const readiness = profileReadiness(
    buildRadarProfile(user.id, merged, cand as CandidateProfile | null),
  );

  return NextResponse.json({
    ok: true,
    saved: {
      target_industries: (patch.target_industries as string[]) ?? null,
      target_roles: (patch.target_roles as string[]) ?? null,
    },
    profile_ready: readiness.ready,
  });
}
