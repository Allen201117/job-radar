// 个人机会雷达的「用户上下文」读取口径（2026-09-08 立，修 F10）。
//
// 缺陷原貌：/today 页与 /api/opportunities 都用 `Promise.all` 并行读四张小表，然后**只取 .data、
// 不看 .error**。于是「查询失败」和「这个用户确实没填」在代码里长得一模一样，后果是静默放宽用户条件：
//   · user_preferences 挂了   → excludeKeywords 变空 → 用户明确排除的岗重新出现在推荐里；
//   · job_actions 挂了        → actions 变空 → already_actioned 硬门失效 → 已忽略/已投递的岗重新推给他；
//   · prefs + profile 都挂了  → profileReadiness 判 not-ready → **老用户被当成新用户**，退回填表引导页。
// 三者都不报错、页面照常渲染，用户只会觉得「这产品乱推、还把我资料弄丢了」。
//
// 口径：**四张表分两类，按「失败会不会改变筛选条件」区分，不是按重要性拍脑袋。**
//   · 硬上下文（preferences / candidate_profiles / job_actions）：失败一律抛错。
//     宁可明确显示「暂时无法更新，请稍后重试」，也不给一个看着正常、实则违背用户条件的队列。
//   · 软上下文（user_radar_state）：只影响「距上次打开的新增」这类强度提示，**不参与任何筛选**，
//     失败按 null 降级并记一条 warn 即可 —— 为它把整页打成错误页是过度反应。
//
// ⚠️ 注意这四张表的读法：maybeSingle() 在「零行」时返回 {data:null,error:null}，
//    所以这里出现的 error 一定是**真失败**（超时/权限/网络），不是「用户没填」。
//    别把这个判据改成看 data 是否为空——那正是原来的 bug。
import type { UserPreferences, CandidateProfile, JobAction } from "@/lib/types";

type SupabaseLike = { from: (table: string) => any };

/** 硬上下文读取失败。调用方应显示可重试的降级状态，**绝不可**当作「用户没有偏好」继续。 */
export class RadarContextError extends Error {
  constructor(public readonly table: string, cause: string) {
    super(`radar context unavailable: ${table}: ${cause}`);
    this.name = "RadarContextError";
  }
}

export type RadarContext = {
  preferences: UserPreferences | null;
  candidate: CandidateProfile | null;
  actions: JobAction[];
  radarState: { last_opened_at: string | null } | null;
};

export async function loadRadarContext(
  supabase: SupabaseLike,
  userId: string,
): Promise<RadarContext> {
  const [prefsRes, candRes, actsRes, stateRes] = await Promise.all([
    supabase.from("user_preferences").select("*").eq("user_id", userId).maybeSingle(),
    supabase.from("candidate_profiles").select("*").eq("user_id", userId).maybeSingle(),
    supabase.from("job_actions").select("*").eq("user_id", userId),
    supabase.from("user_radar_state").select("last_opened_at").eq("user_id", userId).maybeSingle(),
  ]);

  // 硬上下文：失败即抛，绝不降级成空值。
  for (const [table, res] of [
    ["user_preferences", prefsRes],
    ["candidate_profiles", candRes],
    ["job_actions", actsRes],
  ] as const) {
    if (res?.error) throw new RadarContextError(table, res.error.message || "unknown error");
  }

  // 软上下文：不参与筛选，失败按 null 走，但必须留痕（静默降级是这次修的病根本身）。
  if (stateRes?.error) {
    console.warn("[radar-context] user_radar_state 读取失败，按未打开过降级：", stateRes.error.message);
  }

  return {
    preferences: (prefsRes?.data as UserPreferences | null) ?? null,
    candidate: (candRes?.data as CandidateProfile | null) ?? null,
    actions: (actsRes?.data as JobAction[]) || [],
    radarState: stateRes?.error
      ? null
      : ((stateRes?.data as { last_opened_at: string | null } | null) ?? null),
  };
}
