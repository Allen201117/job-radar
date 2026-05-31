import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import resumeParser from "@/lib/resume-parser";

const {
  buildPreferencesFromResumeProfile,
  parseResumeText,
  validateResumeUploadInput,
} = resumeParser as any;

export async function GET() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const { data, error } = await supabase
    .from("candidate_profiles")
    .select("*")
    .eq("user_id", user.id)
    .maybeSingle();

  if (error) {
    return NextResponse.json(
      { ok: false, error: error.message },
      { status: 500 },
    );
  }

  return NextResponse.json({ ok: true, profile: data || null });
}

export async function POST(request: NextRequest) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ ok: false, error: "Unauthorized" }, { status: 401 });
  }

  const parsedInput = await readResumeInput(request);
  const validation = validateResumeUploadInput(parsedInput);
  if (!validation.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: validation.reason,
        supported: "当前 MVP 支持 .txt/.md 或粘贴文本；PDF/DOCX 需要后续接入文档抽取依赖。",
      },
      { status: validation.reason === "unsupported_file_type" ? 415 : 400 },
    );
  }

  const parsedProfile = parseResumeText(parsedInput.text);
  const preferences = buildPreferencesFromResumeProfile(parsedProfile);

  const { data: resume, error: resumeError } = await supabase
    .from("resume_uploads")
    .insert({
      user_id: user.id,
      file_name: parsedInput.fileName,
      file_type: parsedInput.fileType,
      file_size: parsedInput.fileSize,
      raw_text: parsedInput.text,
      parsed_profile: parsedProfile,
      parse_status: "parsed",
    })
    .select("id")
    .single();

  if (resumeError) {
    return NextResponse.json(
      { ok: false, error: resumeError.message },
      { status: 500 },
    );
  }

  const { data: candidateProfile, error: profileError } = await supabase
    .from("candidate_profiles")
    .upsert(
      {
        user_id: user.id,
        resume_id: resume.id,
        headline: parsedProfile.headline,
        target_roles: parsedProfile.target_roles,
        target_locations: parsedProfile.target_locations,
        skills: parsedProfile.skills,
        industries: parsedProfile.industries,
        seniority: parsedProfile.seniority,
        experience_stage: parsedProfile.experience_stage,
        education: parsedProfile.education,
        experience: parsedProfile.experience,
        education_summary: parsedProfile.education_summary,
        experience_summary: parsedProfile.experience_summary,
        raw_profile: parsedProfile,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" },
    )
    .select("*")
    .single();

  if (profileError) {
    return NextResponse.json(
      { ok: false, error: profileError.message },
      { status: 500 },
    );
  }

  let preferencesApplied = false;
  if (parsedInput.applyToPreferences && hasPreferenceSignal(preferences)) {
    const { error: prefsError } = await upsertMergedPreferences(
      supabase,
      user.id,
      preferences,
    );
    if (prefsError) {
      return NextResponse.json(
        { ok: false, error: prefsError.message },
        { status: 500 },
      );
    }
    preferencesApplied = true;
  }

  return NextResponse.json({
    ok: true,
    resume_id: resume.id,
    profile: candidateProfile,
    parsed_profile: parsedProfile,
    preferences,
    preferences_applied: preferencesApplied,
  });
}

async function readResumeInput(request: NextRequest) {
  const contentType = request.headers.get("content-type") || "";

  if (contentType.includes("multipart/form-data")) {
    const form = await request.formData();
    const file = form.get("resume");
    const applyToPreferences = form.get("applyToPreferences") === "true";
    if (!(file instanceof File)) {
      return {
        fileName: "pasted-resume.txt",
        fileType: "text/plain",
        fileSize: 0,
        text: String(form.get("resumeText") || ""),
        applyToPreferences,
      };
    }

    const fileMeta = {
      fileName: file.name,
      fileType: file.type || "application/octet-stream",
      fileSize: file.size,
    };
    const metadataValidation = validateResumeUploadInput({
      ...fileMeta,
      text: "resume",
    });
    if (!metadataValidation.ok) {
      return {
        ...fileMeta,
        text: "",
        applyToPreferences,
      };
    }

    return {
      ...fileMeta,
      text: await file.text(),
      applyToPreferences,
    };
  }

  const body = await request.json();
  const text = String(body.resumeText || body.text || "");
  return {
    fileName: body.fileName || "pasted-resume.txt",
    fileType: body.fileType || "text/plain",
    fileSize: Buffer.byteLength(text, "utf8"),
    text,
    applyToPreferences: Boolean(body.applyToPreferences),
  };
}

async function upsertMergedPreferences(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  userId: string,
  parsedPreferences: {
    target_locations: string[];
    target_roles: string[];
    target_keywords: string[];
  },
) {
  const { data: existing, error: readError } = await supabase
    .from("user_preferences")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();

  if (readError) return { error: readError };

  return supabase.from("user_preferences").upsert(
    {
      user_id: userId,
      target_locations: mergeUnique(
        existing?.target_locations,
        parsedPreferences.target_locations,
      ),
      target_roles: mergeUnique(existing?.target_roles, parsedPreferences.target_roles),
      target_keywords: mergeUnique(
        existing?.target_keywords,
        parsedPreferences.target_keywords,
      ),
      exclude_keywords: existing?.exclude_keywords || [],
      target_companies: existing?.target_companies || [],
      daily_limit: existing?.daily_limit || 20,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "user_id" },
  );
}

function mergeUnique(existing: string[] | null | undefined, incoming: string[]) {
  return Array.from(new Set([...(existing || []), ...(incoming || [])].filter(Boolean)));
}

function hasPreferenceSignal(preferences: {
  target_locations: string[];
  target_roles: string[];
  target_keywords: string[];
}) {
  return [
    ...(preferences.target_locations || []),
    ...(preferences.target_roles || []),
    ...(preferences.target_keywords || []),
  ].some(Boolean);
}
