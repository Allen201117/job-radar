// /today 召回快照的「响应之后」维护（写库与现跑召回都不进请求路径）。
//
// 快照正确性不靠这里：偏好一改，召回 SQL 指纹就对不上，页面自动退回现跑（lib/jobs-store/opportunities.ts
// recallSnapshotUsability）。这里只管「让改完偏好后的第一次打开也快」——保存偏好 / 切换求职范围的接口
// 在响应之后顺手按新偏好现跑一次召回、写成快照。漏挂某个写入口的代价只是那一次打开退回现跑，不是看到旧推荐。
import "server-only";
import { after } from "next/server";
import { createServiceClient } from "../supabaseService";
import { loadRadarContext } from "./context";
import { buildRadarProfile, profileReadiness } from "./profile";
import { refreshRecallSnapshot } from "../jobs-store/opportunities";
import { jobsStoreEnabled } from "../jobs-store/read";

/** 占召回名额的已处理岗（saved / ignored / applied）；与 buildOpportunityFeed 的 SQL 下推同一口径，viewed 不算。 */
export function recallActionedJobIds(actions: ReadonlyArray<{ job_id: string; action: string }>): string[] {
  const out = new Set<string>();
  for (const a of actions || []) {
    if (a.action === "saved" || a.action === "ignored" || a.action === "applied") out.add(a.job_id);
  }
  return Array.from(out);
}

function snapshotsEnabled(): boolean {
  return jobsStoreEnabled() && String(process.env.TODAY_RECALL_SNAPSHOT || "").toLowerCase() !== "off";
}

/** 按用户**当前**库里的偏好 / 简历 / 已处理岗现跑一次召回并写快照。画像未就绪就什么都不做。 */
export async function refreshRecallSnapshotForUser(userId: string): Promise<void> {
  if (!snapshotsEnabled()) return;
  // 响应之后请求的 cookie 已不可写（会话刷新会失败），读自己的行用 service client 按 user_id 取，与页面同一套读法。
  const ctx = await loadRadarContext(createServiceClient(), userId);
  const profile = buildRadarProfile(userId, ctx.preferences, ctx.candidate);
  if (!profileReadiness(profile).ready) return;
  await refreshRecallSnapshot(userId, profile, new Date(), recallActionedJobIds(ctx.actions), "request");
}

/**
 * 在响应之后刷新该用户的快照。永不抛：after() 不可用 / 刷新失败都只记日志——
 * 调用方是保存偏好这类写接口，快照这个加速层出任何问题都不能让保存本身报错。
 */
export function scheduleRecallSnapshotRefresh(userId: string, trigger: string): void {
  if (!snapshotsEnabled()) return;
  try {
    after(() =>
      refreshRecallSnapshotForUser(userId).catch((e) =>
        console.warn(`[recall-snapshot] ${trigger} 后刷新失败：`, (e as Error).message),
      ),
    );
  } catch (e) {
    console.warn(`[recall-snapshot] ${trigger}：after() 不可用，本次不刷新快照：`, (e as Error).message);
  }
}
