import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";

export const runtime = "nodejs";

const MAX_NAME = 40;
const MAX_BIO = 200;

export async function GET() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const { data, error } = await supabase
    .from("profiles")
    .select("display_name, bio, role")
    .eq("id", user.id)
    .maybeSingle();

  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    ok: true,
    profile: {
      display_name: data?.display_name || "",
      bio: data?.bio || "",
      email: user.email || "",
    },
  });
}

export async function PUT(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json().catch(() => ({}));
  const display_name = String(body.display_name || "").trim().slice(0, MAX_NAME);
  const bio = String(body.bio || "").trim().slice(0, MAX_BIO);

  // upsert 只带 id/display_name/bio：新行 role 取默认 'user'，已有行的 role 不被覆盖。
  const { data, error } = await supabase
    .from("profiles")
    .upsert({ id: user.id, display_name, bio }, { onConflict: "id" })
    .select("display_name, bio")
    .single();

  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, profile: data });
}
