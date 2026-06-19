import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import enrichClient from "@/lib/enrich-client";
import { jobsStoreEnabled, jobsByUrls } from "@/lib/jobs-store/read";
import { updateJobSummaryById } from "@/lib/jobs-store/write";

const { enrichOneClient, enrichClientClass } = enrichClient as {
  enrichOneClient: (adapter: string, input: { jd_url: string; source_url: string }) => Promise<string | null>;
  enrichClientClass: (adapter: string) => "httpx" | null;
};

// POST /api/enrich — on-demand 富化（P3）：给用户当下看到的薄卡即时补 summary。
// body { jd_urls: string[] }（封顶 30）。只补**简单 httpx 源**（workday/hotjob）的 active 空 summary 行；
// 浏览器源(moka)/复杂源不在此，靠后台 drain。失败静默降级（卡片保持薄，不报错）。
const MAX_URLS = 30;
const CONCURRENCY = 8;

export async function POST(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const jdUrls: string[] = Array.isArray(body?.jd_urls)
    ? body.jd_urls.filter((u: any) => typeof u === "string" && u).slice(0, MAX_URLS)
    : [];
  if (!jdUrls.length) {
    return NextResponse.json({ ok: true, filled: {} });
  }

  const service = createServiceClient();
  const useStore = jobsStoreEnabled();
  // jobs 已迁自建香港 PG：薄卡(空 summary)回查 + 富化结果写回都 gated 走 jobs-store；异常落回 Supabase 兜底。
  let jobs: any[] | null = null;
  if (useStore) {
    try {
      jobs = await jobsByUrls(jdUrls, true);
    } catch {
      jobs = null; // 香港库异常 → 走 Supabase 兜底
    }
  }
  if (jobs === null) {
    const res = await service
      .from("jobs")
      .select("id, jd_url, source_id, summary, status")
      .in("jd_url", jdUrls)
      .eq("status", "active")
      .is("summary", null);
    jobs = res.data || [];
  }
  const rows = (jobs || []).filter((j: any) => !j.summary);
  if (!rows.length) {
    return NextResponse.json({ ok: true, filled: {} });
  }

  const srcIds = Array.from(new Set(rows.map((r: any) => r.source_id).filter(Boolean)));
  const { data: srcs } = await service
    .from("sources")
    .select("id, adapter_name, source_url")
    .in("id", srcIds);
  const smap = new Map((srcs || []).map((s: any) => [s.id, s]));

  // 只处理 TS 反推器支持的简单 httpx 源（其余留给后台 drain）
  const targets = rows
    .map((r: any) => {
      const src = smap.get(r.source_id);
      const adapter = src?.adapter_name || "";
      if (!src || enrichClientClass(adapter) !== "httpx") return null;
      return { row: r, adapter, source_url: src.source_url as string };
    })
    .filter(Boolean) as Array<{ row: any; adapter: string; source_url: string }>;

  const filled: Record<string, string> = {};
  let idx = 0;
  async function worker() {
    while (idx < targets.length) {
      const t = targets[idx++];
      const summary = await enrichOneClient(t.adapter, {
        jd_url: t.row.jd_url,
        source_url: t.source_url,
      });
      if (!summary) continue;
      try {
        if (useStore) {
          await updateJobSummaryById(t.row.id, summary);
        } else {
          await service
            .from("jobs")
            .update({ summary, enrich_checked_at: new Date().toISOString() })
            .eq("id", t.row.id);
        }
        filled[t.row.jd_url] = summary;
      } catch {
        // 写库失败静默：后台 drain 会兜
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, targets.length) }, () => worker()),
  );

  return NextResponse.json({ ok: true, filled });
}
