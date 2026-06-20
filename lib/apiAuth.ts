import type { User } from "@supabase/supabase-js";
import { NextResponse } from "next/server";
import { createServerSupabase } from "./auth";

type ServerSupabase = Awaited<ReturnType<typeof createServerSupabase>>;

export type ApiAuthResult =
  | { user: User; supabase: ServerSupabase; error?: never }
  | { user?: never; supabase?: never; error: NextResponse };

export async function requireUser(): Promise<ApiAuthResult> {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return {
      error: NextResponse.json(
        { ok: false, error: "Unauthorized" },
        { status: 401 },
      ),
    };
  }
  return { user, supabase };
}

export async function requireAdmin(): Promise<ApiAuthResult> {
  const auth = await requireUser();
  if (auth.error) return auth;

  const { data: profileRow } = await auth.supabase
    .from("profiles")
    .select("role")
    .eq("id", auth.user.id)
    .maybeSingle();
  if (profileRow?.role !== "admin") {
    return {
      error: NextResponse.json(
        { ok: false, error: "forbidden" },
        { status: 403 },
      ),
    };
  }
  return auth;
}

export function assertOwnership(
  row: Record<string, unknown> | null | undefined,
  userId: string,
  ownerKey = "user_id",
): NextResponse | null {
  if (row?.[ownerKey] === userId) return null;
  return NextResponse.json(
    { ok: false, error: "forbidden" },
    { status: 403 },
  );
}
