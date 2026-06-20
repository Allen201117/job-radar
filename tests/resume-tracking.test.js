const assert = require("node:assert/strict");
const test = require("node:test");
const { loadRoute, loadTsModule } = require("./route-test-utils");

const USER = { id: "resume-user-1", email: "private@example.com" };
const trackModule = loadTsModule("lib/track.ts");

function createSupabase({ eventError = null } = {}) {
  const eventRows = [];
  const resumeRows = [];
  const profileRows = [];
  const preferenceRows = [];

  return {
    eventRows,
    resumeRows,
    profileRows,
    preferenceRows,
    auth: {
      getUser: async () => ({ data: { user: USER } }),
    },
    from(table) {
      if (table === "events") {
        return {
          insert: async (row) => {
            eventRows.push(row);
            return { error: eventError };
          },
        };
      }

      if (table === "resume_uploads") {
        return {
          insert(row) {
            resumeRows.push(row);
            return this;
          },
          select() {
            return this;
          },
          single: async () => ({ data: { id: "resume-1" }, error: null }),
        };
      }

      if (table === "candidate_profiles") {
        let saved = null;
        return {
          upsert(row) {
            saved = row;
            profileRows.push(row);
            return this;
          },
          select() {
            return this;
          },
          single: async () => ({ data: saved, error: null }),
        };
      }

      if (table === "user_preferences") {
        return {
          select() {
            return this;
          },
          eq() {
            return this;
          },
          maybeSingle: async () => ({ data: null, error: null }),
          upsert: async (row) => {
            preferenceRows.push(row);
            return { error: null };
          },
        };
      }

      throw new Error(`unexpected table: ${table}`);
    },
  };
}

function loadResumeRoute(supabase, chatJSON) {
  return loadRoute("app/api/resume/route.ts", {
    "@/lib/auth": {
      createServerSupabase: async () => supabase,
    },
    "@/lib/llm": {
      __esModule: true,
      default: {
        chatJSON,
        llmConfig: () => ({
          configured: true,
          model: "test/resume-model",
        }),
      },
    },
    "@/lib/track": trackModule,
  });
}

function jsonRequest(body) {
  return new Request("http://localhost/api/resume", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function assertSafeDiagnostics(eventRows) {
  const serialized = JSON.stringify(eventRows);
  for (const sensitive of [
    "张三",
    "private@example.com",
    "13800138000",
    "raw_text",
    "basic_info",
    "name",
    "contact",
    "phone",
    "email",
  ]) {
    assert.equal(serialized.includes(sensitive), false, `diagnostics leaked ${sensitive}`);
  }

  for (const row of eventRows) {
    assert.deepEqual(Object.keys(row.payload), ["diagnostics"]);
    assert.deepEqual(
      Object.keys(row.payload.diagnostics).sort(),
      ["error_code", "extracted_field_count", "latency_bucket", "model", "source"],
    );
  }
}

test("resume parse emits started then succeeded with safe LLM diagnostics", async () => {
  const supabase = createSupabase();
  const route = loadResumeRoute(supabase, async () => ({
    headline: "数据分析实习生",
    basic_info: {
      name: "张三",
      city: "上海",
      contact: "private@example.com 13800138000",
    },
    target_roles: ["数据分析"],
    target_locations: ["上海"],
    skills: ["SQL", "Python"],
    industries: ["互联网"],
    experience_stage: "实习",
    education: [{ school: "某大学", degree: "本科", major: "统计学" }],
    internships: [],
    projects: [],
  }));

  const response = await route.POST(jsonRequest({
    intent: "parse",
    fileName: "private-resume.txt",
    resumeText: "张三 private@example.com 13800138000 数据分析 SQL Python",
  }));

  assert.equal(response.status, 200);
  assert.equal((await response.json()).source, "llm");
  assert.deepEqual(
    supabase.eventRows.map((row) => row.event),
    ["resume_parse_started", "resume_parse_succeeded"],
  );
  assert.equal(supabase.eventRows[0].payload.diagnostics.source, "llm");
  assert.equal(supabase.eventRows[0].payload.diagnostics.model, "test/resume-model");
  assert.equal(supabase.eventRows[0].payload.diagnostics.extracted_field_count, 0);
  assert.equal(supabase.eventRows[1].payload.diagnostics.source, "llm");
  assert.equal(supabase.eventRows[1].payload.diagnostics.error_code, null);
  assert.ok(supabase.eventRows[1].payload.diagnostics.extracted_field_count > 0);
  assertSafeDiagnostics(supabase.eventRows);
});

test("resume fallback emits started, fallback_rule, then succeeded with normalized error", async () => {
  const supabase = createSupabase();
  const error = Object.assign(new Error("provider rejected request"), {
    code: "llm_http_error",
    status: 402,
    detail: "余额不足 private@example.com",
  });
  const route = loadResumeRoute(supabase, async () => {
    throw error;
  });

  const errors = [];
  const originalError = console.error;
  console.error = (...args) => errors.push(args.join(" "));
  let response;
  try {
    response = await route.POST(jsonRequest({
      intent: "parse",
      resumeText: "张三 求职意向：数据分析实习生 上海 技能 SQL Python 13800138000",
    }));
  } finally {
    console.error = originalError;
  }

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.source, "rule");
  assert.deepEqual(
    supabase.eventRows.map((row) => row.event),
    ["resume_parse_started", "resume_parse_fallback_rule", "resume_parse_succeeded"],
  );
  for (const row of supabase.eventRows.slice(1)) {
    assert.equal(row.payload.diagnostics.source, "rule");
    assert.equal(row.payload.diagnostics.model, "rule-v1");
    assert.equal(row.payload.diagnostics.error_code, "llm_insufficient_balance");
  }
  assert.ok(errors.some((line) => line.includes("llm_http_error:402")));
  assert.equal(errors.some((line) => line.includes("private@example.com")), false);
  assertSafeDiagnostics(supabase.eventRows);
});

test("confirmed profile save emits saved then preferences applied with propagated parse source", async () => {
  const supabase = createSupabase();
  const route = loadResumeRoute(supabase, async () => ({}));
  const profile = {
    headline: "数据分析实习生",
    basic_info: {
      name: "张三",
      city: "上海",
      contact: "private@example.com",
    },
    target_roles: ["数据分析"],
    target_locations: ["上海"],
    skills: ["SQL"],
    industries: [],
    experience_stage: "实习",
    education: [],
    internships: [],
    projects: [],
  };

  const response = await route.POST(jsonRequest({
    intent: "save",
    resumeId: "resume-1",
    profile,
    applyToPreferences: true,
    parseDiagnostics: {
      source: "rule",
      model: "rule-v1",
      error_code: "llm_bad_json",
    },
  }));

  assert.equal(response.status, 200);
  assert.equal((await response.json()).preferences_applied, true);
  assert.deepEqual(
    supabase.eventRows.map((row) => row.event),
    ["resume_profile_saved", "resume_preferences_applied"],
  );
  for (const row of supabase.eventRows) {
    assert.equal(row.payload.diagnostics.source, "rule");
    assert.equal(row.payload.diagnostics.model, "rule-v1");
    assert.equal(row.payload.diagnostics.error_code, "llm_bad_json");
    assert.ok(row.payload.diagnostics.extracted_field_count > 0);
  }
  assertSafeDiagnostics(supabase.eventRows);
});

test("event insert failure is logged and does not fail resume parsing", async () => {
  const supabase = createSupabase({ eventError: { message: "events unavailable" } });
  const route = loadResumeRoute(supabase, async () => ({
    headline: "数据分析",
    target_roles: ["数据分析"],
  }));
  const warnings = [];
  const originalWarn = console.warn;
  console.warn = (...args) => warnings.push(args.join(" "));
  try {
    const response = await route.POST(jsonRequest({
      intent: "parse",
      resumeText: "数据分析 SQL",
    }));
    assert.equal(response.status, 200);
    assert.equal((await response.json()).ok, true);
  } finally {
    console.warn = originalWarn;
  }

  assert.deepEqual(
    supabase.eventRows.map((row) => row.event),
    ["resume_parse_started", "resume_parse_succeeded"],
  );
  assert.ok(warnings.some((line) => line.includes("[events] insert failed")));
});
