// 走真实链路：lib/resume-extract.buildResumeMessages → lib/llm.chatJSON → normalizeResumeProfile
// → lib/resume-parser.buildPreferencesFromResumeProfile（= 真实写进 user_preferences 的东西）
const fs = require("fs"), path = require("path");
const ROOT = process.env.EVAL_ROOT || path.join(__dirname, "..", "..");
const { buildResumeMessages, normalizeResumeProfile } = require(path.join(ROOT, "lib/resume-extract.js"));
const { chatJSON, llmConfig } = require(path.join(ROOT, "lib/llm.js"));
const { buildPreferencesFromResumeProfile } = require(path.join(ROOT, "lib/resume-parser.js"));

(async () => {
  console.error("llm config:", JSON.stringify({ ...llmConfig(), apiKey: undefined }));
  const dir = path.join(__dirname, "resumes");
  const out = [];
  for (const f of fs.readdirSync(dir).sort()) {
    const text = fs.readFileSync(path.join(dir, f), "utf8");
    const t0 = Date.now();
    let raw, err = null;
    try {
      raw = await chatJSON(buildResumeMessages(text), { tag: "resume-eval" });
    } catch (e) { err = e.message || String(e); raw = {}; }
    const profile = normalizeResumeProfile(raw);
    const prefs = buildPreferencesFromResumeProfile(profile);
    console.error(`[${f}] ${Date.now() - t0}ms err=${err || "-"}`);
    out.push({ file: f, profile, prefs, err });
  }
  fs.writeFileSync(path.join(__dirname, process.env.OUT_NAME || "parsed-profiles.json"), JSON.stringify(out, null, 2));
  for (const r of out) {
    console.log("=== " + r.file + " ===");
    console.log("headline      :", r.profile.headline);
    console.log("target_roles  :", JSON.stringify(r.prefs.target_roles));
    console.log("skills        :", JSON.stringify(r.prefs.skills));
    console.log("industries    :", JSON.stringify(r.prefs.industries));
    console.log("locations     :", JSON.stringify(r.prefs.target_locations));
    console.log("stage         :", r.profile.experience_stage);
  }
})();
