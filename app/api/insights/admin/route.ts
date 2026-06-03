import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import { createServiceClient } from "@/lib/supabaseService";
import {
  evaluateInsight,
  passesDeidentifiedGate,
  passesGradeGate,
  passesAssertionLint,
  hasTimeWindow,
} from "@/lib/insight-verification";
import { INSIGHT_DIMENSIONS, ITEM_COLUMNS, flattenSources } from "@/lib/insight-bundle";
import type { InsightItem, InsightSource } from "@/lib/types";

export const runtime = "nodejs";

const GRADES = ["fact", "experience", "rumor"];
const STATUSES = ["active", "disputed", "retired"];

// 统一 admin 守卫：未登录 401 / 非 admin 403 / 否则放行。
async function requireAdmin() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { error: NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 }) };
  const { data: profileRow } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return { error: NextResponse.json({ ok: false, error: "forbidden" }, { status: 403 }) };
  }
  return { supabase, user };
}

// 把表单里的 sources 数组写成 insight_sources + 关联 insight_item_sources。
async function attachSources(service: any, itemId: string, sources: any[]) {
  for (const s of sources) {
    const url = String(s.url || "").trim();
    if (!url) continue;
    const { data: srcRow, error: srcError } = await service
      .from("insight_sources")
      .insert({
        url,
        publisher: s.publisher ? String(s.publisher).trim() : null,
        source_kind: s.source_kind || null,
        excerpt: s.excerpt ? String(s.excerpt).slice(0, 500) : null,
        collected_at: s.collected_at || new Date().toISOString(),
        deidentified: s.deidentified === true,
      })
      .select("id")
      .single();
    if (srcError) {
      console.error("[insights-admin] 插入 insight_sources 失败", srcError.message);
      continue;
    }
    await service.from("insight_item_sources").insert({ item_id: itemId, source_id: srcRow.id });
  }
}

// 删除某条目现有来源（先删关联再删 source 本身），用于编辑时整体替换。
async function detachSources(service: any, itemId: string) {
  const { data: links } = await service
    .from("insight_item_sources")
    .select("source_id")
    .eq("item_id", itemId);
  const sourceIds = (links || []).map((l: any) => l.source_id);
  await service.from("insight_item_sources").delete().eq("item_id", itemId);
  if (sourceIds.length) {
    await service.from("insight_sources").delete().in("id", sourceIds);
  }
}

// 构造校验用的草稿 item + sources（与 POST /api/insights 一致），用于过校验门。
function buildDraft(body: any, status: string) {
  const draftItem = {
    id: "draft",
    company_id: "draft",
    dimension: body.dimension,
    grade: body.grade,
    title: body.title ?? null,
    content: String(body.content || "").trim(),
    sample_size: body.sample_size ?? null,
    payload: body.payload ?? {},
    time_window: body.time_window ?? null,
    valid_from: body.valid_from ?? null,
    valid_until: body.valid_until ?? null,
    last_verified_at: new Date().toISOString(),
    deidentified: body.deidentified === true,
    status,
    created_at: "",
    updated_at: "",
  } as InsightItem;
  const draftSources: InsightSource[] = (Array.isArray(body.sources) ? body.sources : []).map(
    (s: any, i: number) => ({
      id: `draft-${i}`,
      url: String(s.url || ""),
      publisher: s.publisher ?? null,
      source_kind: s.source_kind ?? null,
      excerpt: s.excerpt ?? null,
      collected_at: s.collected_at ?? null,
      deidentified: s.deidentified === true,
      created_at: "",
    }),
  );
  return { draftItem, draftSources };
}

// 返回第一个未通过的校验门（给 admin 看具体卡在哪），全过则返回 null。
function firstFailingGate(item: InsightItem, sources: InsightSource[]): string | null {
  if (!passesDeidentifiedGate(item, sources)) return "deidentified";
  if (!passesGradeGate(item, sources)) return "grade";
  if (!passesAssertionLint(item)) return "assertion";
  if (!hasTimeWindow(item)) return "time_window";
  return null;
}

// ============================================================
// GET：admin 列出全部公司画像 + 全部条目（含非 active）+ 待处理申诉
// ============================================================
export async function GET() {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  const service = createServiceClient();
  const [{ data: companies, error: cErr }, { data: rawItems, error: iErr }, { data: disputes, error: dErr }] =
    await Promise.all([
      service.from("company_profiles").select("id, company, display_name, aliases").order("company"),
      service
        .from("insight_items")
        .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
        .order("updated_at", { ascending: false }),
      service
        .from("insight_disputes")
        .select("id, item_id, reason, contact, status, created_at")
        .eq("status", "open")
        .order("created_at", { ascending: false }),
    ]);
  if (cErr || iErr || dErr) {
    const message = cErr?.message || iErr?.message || dErr?.message || "load_failed";
    console.error("[insights-admin] 读取失败", message);
    return NextResponse.json({ ok: false, error: message }, { status: 500 });
  }

  const items = (rawItems || []).map((raw: any) => {
    const rest = { ...raw };
    delete rest.insight_item_sources;
    return { ...rest, sources: flattenSources(raw) };
  });

  return NextResponse.json({
    ok: true,
    companies: companies || [],
    items,
    disputes: disputes || [],
  });
}

// ============================================================
// POST：新增 / 编辑条目（body.id 存在则编辑）。status=active 必过校验门。
// ============================================================
export async function POST(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const company = String(body.company || "").trim();
  const content = String(body.content || "").trim();
  if (
    !company ||
    !INSIGHT_DIMENSIONS.includes(body.dimension) ||
    !GRADES.includes(body.grade) ||
    !content
  ) {
    return NextResponse.json({ ok: false, error: "missing_required_fields" }, { status: 400 });
  }

  const status = STATUSES.includes(body.status) ? body.status : "active";

  // 只有要落成 active 才必须过门；存草稿（retired/disputed）可暂不达标。
  if (status === "active") {
    const { draftItem, draftSources } = buildDraft(body, status);
    const gate = firstFailingGate(draftItem, draftSources);
    if (gate) {
      const ev = evaluateInsight(draftItem, draftSources, new Date());
      return NextResponse.json(
        { ok: false, error: "validation_failed", failure_reason: ev.failure_reason, gate },
        { status: 422 },
      );
    }
  }

  const service = createServiceClient();

  const itemFields = {
    dimension: body.dimension,
    grade: body.grade,
    title: body.title ? String(body.title).trim() : null,
    content,
    sample_size: body.sample_size === "" || body.sample_size == null ? null : Number(body.sample_size),
    payload: body.payload && typeof body.payload === "object" ? body.payload : {},
    time_window: body.time_window ? String(body.time_window).trim() : null,
    valid_from: body.valid_from || null,
    valid_until: body.valid_until || null,
    deidentified: body.deidentified === true,
    status,
    last_verified_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const sources = Array.isArray(body.sources) ? body.sources : [];

  if (body.id) {
    // 编辑：更新字段 + 整体替换来源（公司不变）。
    const { error: upErr } = await service
      .from("insight_items")
      .update(itemFields)
      .eq("id", body.id);
    if (upErr) {
      console.error("[insights-admin] 更新条目失败", upErr.message);
      return NextResponse.json({ ok: false, error: upErr.message }, { status: 500 });
    }
    await detachSources(service, body.id);
    await attachSources(service, body.id, sources);
    return NextResponse.json({ ok: true, item_id: body.id });
  }

  // 新增：upsert 公司画像 → 插入条目 → 来源。
  const { data: companyRow, error: companyError } = await service
    .from("company_profiles")
    .upsert({ company }, { onConflict: "company" })
    .select("id")
    .single();
  if (companyError) {
    console.error("[insights-admin] upsert 公司画像失败", companyError.message);
    return NextResponse.json({ ok: false, error: companyError.message }, { status: 500 });
  }

  const { data: itemRow, error: insertError } = await service
    .from("insight_items")
    .insert({ company_id: companyRow.id, ...itemFields })
    .select("id")
    .single();
  if (insertError) {
    console.error("[insights-admin] 插入条目失败", insertError.message);
    return NextResponse.json({ ok: false, error: insertError.message }, { status: 500 });
  }

  await attachSources(service, itemRow.id, sources);
  return NextResponse.json({ ok: true, item_id: itemRow.id });
}

// ============================================================
// PATCH：上架 / 下架（改 status）。改成 active 同样必过校验门。
// ============================================================
export async function PATCH(request: NextRequest) {
  const guard = await requireAdmin();
  if (guard.error) return guard.error;

  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
  }

  const id = String(body.id || "").trim();
  const status = body.status;
  if (!id || !STATUSES.includes(status)) {
    return NextResponse.json({ ok: false, error: "invalid_input" }, { status: 400 });
  }

  const service = createServiceClient();

  if (status === "active") {
    // 重新上架前回放校验门，避免把不合格条目放回展示。
    const { data: raw, error } = await service
      .from("insight_items")
      .select(`${ITEM_COLUMNS}, insight_item_sources(insight_sources(*))`)
      .eq("id", id)
      .single();
    if (error || !raw) {
      return NextResponse.json({ ok: false, error: error?.message || "not_found" }, { status: 404 });
    }
    const ev = evaluateInsight(
      { ...(raw as any), status: "active" } as InsightItem,
      flattenSources(raw),
      new Date(),
    );
    if (!ev.displayable) {
      return NextResponse.json(
        { ok: false, error: "validation_failed", failure_reason: ev.failure_reason },
        { status: 422 },
      );
    }
  }

  const { error: upErr } = await service
    .from("insight_items")
    .update({ status, updated_at: new Date().toISOString() })
    .eq("id", id);
  if (upErr) {
    console.error("[insights-admin] 改状态失败", upErr.message);
    return NextResponse.json({ ok: false, error: upErr.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, id, status });
}
