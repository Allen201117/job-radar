import { NextRequest, NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/auth";
import resumeParser from "@/lib/resume-parser";
import llm from "@/lib/llm";
import resumeExtract from "@/lib/resume-extract";

const {
  buildPreferencesFromResumeProfile,
  parseResumeText,
  validateResumeUploadInput,
} = resumeParser as any;
const { chatJSON } = llm as any;
const { buildResumeMessages, normalizeResumeProfile } = resumeExtract as any;

export const runtime = "nodejs";

const MAX_RESUME_FILE_BYTES = 10 * 1024 * 1024;

// 服务端把 PDF / Word(.docx) / 图片 抽成纯文本，再交给 LLM 结构化抽取（失败降级规则解析）。
async function extractResumeText(
  fileName: string,
  fileType: string,
  buf: Buffer,
): Promise<{ ok: boolean; text: string; kind: string }> {
  const name = (fileName || "").toLowerCase();
  try {
    if (name.endsWith(".txt") || name.endsWith(".md") || fileType.startsWith("text/")) {
      return { ok: true, text: buf.toString("utf8"), kind: "text" };
    }
    if (name.endsWith(".pdf") || fileType === "application/pdf") {
      const { getDocumentProxy, extractText }: any = await import("unpdf");
      const pdf = await getDocumentProxy(new Uint8Array(buf));
      const { text } = await extractText(pdf, { mergePages: true });
      return { ok: true, text: String(text || ""), kind: "pdf" };
    }
    if (name.endsWith(".docx") || fileType.includes("wordprocessingml")) {
      const mammoth: any = await import("mammoth");
      const r = await mammoth.extractRawText({ buffer: buf });
      return { ok: true, text: String(r?.value || ""), kind: "docx" };
    }
    if (/\.(png|jpe?g|webp|bmp|gif)$/.test(name) || fileType.startsWith("image/")) {
      const { createWorker }: any = await import("tesseract.js");
      const worker = await createWorker("chi_sim+eng");
      const { data } = await worker.recognize(buf);
      await worker.terminate();
      return { ok: true, text: String(data?.text || ""), kind: "image-ocr" };
    }
  } catch (err) {
    console.error("[resume] 抽取失败", (err as Error).message);
    return { ok: false, text: "", kind: "extract_error" };
  }
  return { ok: false, text: "", kind: "unsupported" };
}

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
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
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

  const input = await readResumeInput(request);

  // 保存：用户在预览界面确认/编辑后落库（不静默入库）。
  if (input.intent === "save") {
    return saveConfirmedProfile(supabase, user.id, input);
  }

  // 解析：抽取 → LLM 结构化（失败降级规则）→ 仅返回供预览编辑，不更新画像。
  return parseResume(supabase, user.id, input);
}

async function parseResume(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  userId: string,
  input: ResumeInput,
) {
  const validation = validateResumeUploadInput(input);
  if (!validation.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: validation.reason,
        supported: "支持 .txt / .md / PDF / Word / 图片，或直接粘贴文本。",
      },
      { status: validation.reason === "unsupported_file_type" ? 415 : 400 },
    );
  }

  let profile: any;
  let source = "llm";
  let llmError: string | null = null;
  try {
    const raw = await chatJSON(buildResumeMessages(input.text), { maxTokens: 2048 });
    profile = normalizeResumeProfile(raw);
    if (!profileHasContent(profile)) throw new Error("llm_empty");
  } catch (err: any) {
    source = "rule";
    llmError = err?.code || err?.message || "llm_failed";
    console.error("[resume] LLM 抽取失败，降级规则解析:", llmError);
    profile = normalizeResumeProfile(ruleToStructured(parseResumeText(input.text)));
  }

  // 记录一次上传（含原文与解析结果），供保存时关联；画像本身等用户确认再写。
  const { data: resume, error: resumeError } = await supabase
    .from("resume_uploads")
    .insert({
      user_id: userId,
      file_name: input.fileName,
      file_type: input.fileType,
      file_size: input.fileSize,
      raw_text: input.text,
      parsed_profile: profile,
      parse_status: "parsed",
    })
    .select("id")
    .single();

  if (resumeError) {
    return NextResponse.json({ ok: false, error: resumeError.message }, { status: 500 });
  }

  return NextResponse.json({
    ok: true,
    resume_id: resume.id,
    profile,
    source,
    llm_error: llmError,
  });
}

async function saveConfirmedProfile(
  supabase: Awaited<ReturnType<typeof createServerSupabase>>,
  userId: string,
  input: ResumeInput,
) {
  if (!input.profile || typeof input.profile !== "object") {
    return NextResponse.json({ ok: false, error: "missing_profile" }, { status: 400 });
  }

  // 再归一化一遍：即使前端被改动，落库前也强制脱敏与裁剪。
  const profile = normalizeResumeProfile(input.profile);

  const { data: saved, error: profileError } = await supabase
    .from("candidate_profiles")
    .upsert(
      {
        user_id: userId,
        resume_id: input.resumeId || null,
        headline: profile.headline,
        target_roles: profile.target_roles,
        target_locations: profile.target_locations,
        skills: profile.skills,
        industries: profile.industries,
        seniority: profile.seniority,
        experience_stage: profile.experience_stage,
        basic_info: profile.basic_info,
        education: profile.education,
        internships: profile.internships,
        projects: profile.projects,
        experience: profile.projects, // 兼容旧字段（display 用）
        education_summary: profile.education_summary,
        experience_summary: profile.experience_summary,
        raw_profile: profile,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" },
    )
    .select("*")
    .single();

  if (profileError) {
    return NextResponse.json({ ok: false, error: profileError.message }, { status: 500 });
  }

  let preferencesApplied = false;
  const preferences = buildPreferencesFromResumeProfile(profile);
  if (input.applyToPreferences && hasPreferenceSignal(preferences)) {
    const { error: prefsError } = await upsertMergedPreferences(supabase, userId, preferences);
    if (prefsError) {
      return NextResponse.json({ ok: false, error: prefsError.message }, { status: 500 });
    }
    preferencesApplied = true;
  }

  return NextResponse.json({
    ok: true,
    profile: saved,
    preferences_applied: preferencesApplied,
  });
}

// 规则解析结果（education/experience 是字符串数组）适配成结构化抽取的入参形状。
function ruleToStructured(p: any) {
  return {
    headline: p?.headline,
    basic_info: {},
    target_roles: p?.target_roles,
    target_locations: p?.target_locations,
    skills: p?.skills,
    industries: p?.industries,
    experience_stage: p?.experience_stage,
    education: (p?.education || []).map((line: string) => ({ school: line })),
    internships: [],
    projects: (p?.experience || []).map((line: string) => ({ name: line })),
  };
}

function profileHasContent(profile: any): boolean {
  return Boolean(
    profile &&
      (profile.headline ||
        (profile.skills || []).length ||
        (profile.education || []).length ||
        (profile.internships || []).length ||
        (profile.projects || []).length ||
        (profile.target_roles || []).length),
  );
}

type ResumeInput = {
  intent: "parse" | "save";
  fileName: string;
  fileType: string;
  fileSize: number;
  text: string;
  applyToPreferences: boolean;
  profile?: any;
  resumeId?: string | null;
};

async function readResumeInput(request: NextRequest): Promise<ResumeInput> {
  const contentType = request.headers.get("content-type") || "";

  if (contentType.includes("multipart/form-data")) {
    const form = await request.formData();
    const file = form.get("resume");
    const applyToPreferences = form.get("applyToPreferences") === "true";
    const intent = (String(form.get("intent") || "parse") as "parse" | "save");
    if (!(file instanceof File)) {
      return {
        intent,
        fileName: "pasted-resume.txt",
        fileType: "text/plain",
        fileSize: 0,
        text: String(form.get("resumeText") || ""),
        applyToPreferences,
      };
    }

    const buf = Buffer.from(await file.arrayBuffer());
    const fileMeta = {
      fileName: file.name,
      fileType: file.type || "application/octet-stream",
      fileSize: buf.length,
    };
    if (buf.length > MAX_RESUME_FILE_BYTES) {
      return { intent, ...fileMeta, text: "", applyToPreferences };
    }
    const extracted = await extractResumeText(file.name, fileMeta.fileType, buf);
    return {
      intent,
      ...fileMeta,
      // 抽取成功 → 标为 text/plain 让下游文本校验通过；不支持/失败 → 保留原类型走 415
      fileType: extracted.ok ? "text/plain" : fileMeta.fileType,
      text: extracted.text,
      applyToPreferences,
    };
  }

  const body = await request.json().catch(() => ({}));
  const text = String(body.resumeText || body.text || "");
  return {
    intent: body.intent === "save" ? "save" : "parse",
    fileName: body.fileName || "pasted-resume.txt",
    fileType: body.fileType || "text/plain",
    fileSize: Buffer.byteLength(text, "utf8"),
    text,
    applyToPreferences: Boolean(body.applyToPreferences),
    profile: body.profile,
    resumeId: body.resumeId || null,
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
      target_locations: mergeUnique(existing?.target_locations, parsedPreferences.target_locations),
      target_roles: mergeUnique(existing?.target_roles, parsedPreferences.target_roles),
      target_keywords: mergeUnique(existing?.target_keywords, parsedPreferences.target_keywords),
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
