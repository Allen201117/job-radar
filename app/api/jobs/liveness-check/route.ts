// 展示时校验（② 层）：看板加载时把当下看到的岗位批量探一下死活，死的当场标 expired 并回给前端隐藏，
// 用户**压根看不到**死岗（点击门是"点了才拦"，这层是"根本不显示"）。复用 lib/liveness-client + 探活写助手。
// 只探有快速撤岗信号的源（wt/hotjob/workday）+ 跳过 24h 内刚探过的；其余放过（交后台 sweep/浏览器审计）。
// 非阻塞：前端异步调，看板先渲染、死的随后消失（镜像 /api/enrich 读时富化）。顺带给在招岗盖探活戳，
// 让"被浏览的热门岗"自然获得 liveness 覆盖、减少后台重复探。
import { NextRequest, NextResponse } from "next/server";
import { hasSessionCookie } from "@/lib/apiAuth";
import { createServiceClient } from "@/lib/supabaseService";
import { jobsStoreEnabled, jobsByIds } from "@/lib/jobs-store/read";
import { markJobExpiredById, touchJobCheckedById } from "@/lib/jobs-store/write";
import liveness from "@/lib/liveness-client";

export const dynamic = "force-dynamic";

const { checkLiveness, livenessSupported } = liveness as {
  checkLiveness: (
    adapter: string,
    input: { jd_url: string; source_url?: string | null },
  ) => Promise<"alive" | "dead" | "unknown">;
  livenessSupported: (adapter: string) => boolean;
};

const MAX_IDS = 30;
const CONCURRENCY = 6;
const FRESH_MS = 24 * 60 * 60 * 1000; // 24h 内探活过 → 跳过

export async function POST(request: NextRequest) {
  // 廉价登录态判断（不联网）：背景批量探活只读 + 标 expired/盖戳，不碰用户数据。匿名→空响应、不探不写。
  if (!hasSessionCookie(request)) return NextResponse.json({ ok: true, dead: [] });

  let body: any;
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const ids: string[] = Array.isArray(body?.ids)
    ? body.ids.filter((x: any) => typeof x === "string" && x).slice(0, MAX_IDS)
    : [];
  if (!ids.length) return NextResponse.json({ ok: true, dead: [] });

  const useStore = jobsStoreEnabled();
  const service = createServiceClient();

  // 1. 取岗位（只关心当前 active 的）
  let jobs: any[] | null = null;
  if (useStore) {
    try {
      jobs = await jobsByIds(ids, true);
    } catch {
      jobs = null; // 香港库异常 → Supabase 兜底
    }
  }
  if (jobs === null) {
    const res = await service
      .from("jobs")
      .select("id, jd_url, source_id, status, enrich_checked_at")
      .in("id", ids)
      .eq("status", "active");
    jobs = res.data || [];
  }
  const active = (jobs || []).filter((j: any) => j.status === "active" && j.jd_url);
  if (!active.length) return NextResponse.json({ ok: true, dead: [] });

  // 2. 源映射（adapter + source_url 在 Supabase）
  const srcIds = Array.from(new Set(active.map((j: any) => j.source_id).filter(Boolean)));
  const { data: srcs } = await service
    .from("sources")
    .select("id, adapter_name, source_url")
    .in("id", srcIds);
  const smap = new Map((srcs || []).map((s: any) => [s.id, s]));

  // 3. 只留"可探 + 非刚探过"的岗
  const now = Date.now();
  const targets = active
    .map((j: any) => {
      const src = smap.get(j.source_id);
      const adapter = src?.adapter_name || "";
      if (!src || !livenessSupported(adapter)) return null;
      const checkedAt = j.enrich_checked_at ? Date.parse(j.enrich_checked_at) : NaN;
      if (Number.isFinite(checkedAt) && now - checkedAt < FRESH_MS) return null;
      return { id: j.id as string, jd_url: j.jd_url as string, adapter, source_url: src.source_url as string };
    })
    .filter(Boolean) as Array<{ id: string; jd_url: string; adapter: string; source_url: string }>;

  // 4. 并发探活：死→标 expired + 回给前端隐藏；活→盖探活戳；拿不准→放过
  const dead: string[] = [];
  let idx = 0;
  async function worker() {
    while (idx < targets.length) {
      const t = targets[idx++];
      const verdict = await checkLiveness(t.adapter, { jd_url: t.jd_url, source_url: t.source_url });
      if (verdict === "dead") {
        dead.push(t.id);
        try {
          if (useStore) await markJobExpiredById(t.id);
          else
            await service
              .from("jobs")
              .update({ status: "expired", enrich_checked_at: new Date().toISOString() })
              .eq("id", t.id)
              .eq("status", "active");
        } catch {
          // 写库失败：前端这次仍会隐藏，后台 sweep 兜
        }
      } else if (verdict === "alive") {
        try {
          if (useStore) await touchJobCheckedById(t.id);
          else await service.from("jobs").update({ enrich_checked_at: new Date().toISOString() }).eq("id", t.id);
        } catch {
          // 盖戳失败无所谓
        }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, targets.length) }, () => worker()));

  return NextResponse.json({ ok: true, dead });
}
