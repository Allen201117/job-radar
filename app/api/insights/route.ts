import { NextRequest, NextResponse } from "next/server";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { createServerSupabase } from "@/lib/auth";
import { findCompanyProfile } from "@/lib/insight-match";
import { evaluateInsight, resolveInsightFailure } from "@/lib/insight-verification";
import {
  INSIGHT_DIMENSIONS,
  ITEM_COLUMNS,
  emptyDimensions,
  groupGatedInsights,
} from "@/lib/insight-bundle";
import type {
  CompanyProfile,
  InsightDimension,
  InsightItem,
  InsightSource,
} from "@/lib/types";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const company = (request.nextUrl.searchParams.get("company") || "").trim();
  if (!company) {
    return NextResponse.json(
      { ok: false, error: "missing_company" },
      { status: 400 },
    );
  }

  // 1) 取全部公司画像，归一化匹配（苹果↔Apple、字节↔ByteDance）
  const { data: profiles, error: profileError } = await supabase
    .from("company_profiles")
    .select("*");
  if (profileError) {
    console.error("[insights] 读取 company_profiles 失败", profileError.message);
    return NextResponse.json(
      { ok: false, error: profileError.message },
      { status: 500 },
    );
  }

  const profile = findCompanyProfile((profiles || []) as CompanyProfile[], company);
  if (!profile) {
    return NextResponse.json({
      ok: true,
      company: null,
      query: company,
      dimensions: emptyDimensions(),
      failure_reason: "insight_unverified",
    });
  }

  // 2) 取该公司 active 洞察 + 溯源（RLS 已限定 active + deidentified）
  const { data: items, error: itemError } = await supabase
    .from("insight_items")
    .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
    .eq("company_id", profile.id)
    .eq("status", "active");
  if (itemError) {
    console.error("[insights] 读取 insight_items 失败", itemError.message);
    return NextResponse.json(
      { ok: false, error: itemError.message },
      { status: 500 },
    );
  }

  // 3) 过校验门（grade / 去标识 / 归因 / 时效）+ 按维度分组（共享 insight-bundle）
  const { dimensions, evaluations } = groupGatedInsights((items || []) as any[], new Date());

  return NextResponse.json({
    ok: true,
    company: profile,
    query: company,
    dimensions,
    failure_reason: resolveInsightFailure(evaluations),
  });
}

// ============================================================
// admin 录入（走校验门，不过门则拒绝）。日常策展用；首批数据走 seed migration。
// ============================================================
function createServiceClient(): SupabaseClient {
  const supabaseUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    throw new Error("Missing Supabase service credentials");
  }
  return createClient(supabaseUrl, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

export async function POST(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }
  const { data: profileRow } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return NextResponse.json({ ok: false, error: "forbidden" }, { status: 403 });
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const company = String(body.company || "").trim();
  const dimension = body.dimension as InsightDimension;
  const grade = body.grade;
  const content = String(body.content || "").trim();
  const sources = Array.isArray(body.sources) ? body.sources : [];

  if (!company || !INSIGHT_DIMENSIONS.includes(dimension) || !content) {
    return NextResponse.json(
      { ok: false, error: "missing_required_fields" },
      { status: 400 },
    );
  }

  // 用校验门预检（构造一个临时 item + sources 视图）
  const draftItem = {
    id: "draft",
    company_id: "draft",
    dimension,
    grade,
    title: body.title ?? null,
    content,
    sample_size: body.sample_size ?? null,
    payload: body.payload ?? {},
    time_window: body.time_window ?? null,
    valid_from: body.valid_from ?? null,
    valid_until: body.valid_until ?? null,
    last_verified_at: new Date().toISOString(),
    deidentified: body.deidentified === true,
    status: "active",
    created_at: "",
    updated_at: "",
  } as InsightItem;
  const draftSources: InsightSource[] = sources.map((s: any, i: number) => ({
    id: `draft-${i}`,
    url: String(s.url || ""),
    publisher: s.publisher ?? null,
    source_kind: s.source_kind ?? null,
    excerpt: s.excerpt ?? null,
    collected_at: s.collected_at ?? null,
    deidentified: s.deidentified === true,
    created_at: "",
  }));

  const ev = evaluateInsight(draftItem, draftSources, new Date());
  if (!ev.displayable) {
    return NextResponse.json(
      { ok: false, error: "validation_failed", failure_reason: ev.failure_reason },
      { status: 422 },
    );
  }

  const service = createServiceClient();

  // upsert 公司画像
  const { data: companyRow, error: companyError } = await service
    .from("company_profiles")
    .upsert({ company }, { onConflict: "company" })
    .select("id")
    .single();
  if (companyError) {
    console.error("[insights] upsert company_profiles 失败", companyError.message);
    return NextResponse.json({ ok: false, error: companyError.message }, { status: 500 });
  }

  // 插入条目
  const { data: itemRow, error: insertError } = await service
    .from("insight_items")
    .insert({
      company_id: companyRow.id,
      dimension,
      grade,
      title: draftItem.title,
      content,
      sample_size: draftItem.sample_size,
      payload: draftItem.payload,
      time_window: draftItem.time_window,
      valid_from: draftItem.valid_from,
      valid_until: draftItem.valid_until,
      last_verified_at: draftItem.last_verified_at,
      deidentified: draftItem.deidentified,
      status: "active",
    })
    .select("id")
    .single();
  if (insertError) {
    console.error("[insights] 插入 insight_items 失败", insertError.message);
    return NextResponse.json({ ok: false, error: insertError.message }, { status: 500 });
  }

  // 插入来源 + 关联
  for (const s of draftSources) {
    const { data: srcRow, error: srcError } = await service
      .from("insight_sources")
      .insert({
        url: s.url,
        publisher: s.publisher,
        source_kind: s.source_kind,
        excerpt: s.excerpt,
        collected_at: s.collected_at,
        deidentified: s.deidentified,
      })
      .select("id")
      .single();
    if (srcError) {
      console.error("[insights] 插入 insight_sources 失败", srcError.message);
      continue;
    }
    await service
      .from("insight_item_sources")
      .insert({ item_id: itemRow.id, source_id: srcRow.id });
  }

  return NextResponse.json({ ok: true, item_id: itemRow.id });
}
