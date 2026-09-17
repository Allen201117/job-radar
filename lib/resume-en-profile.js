const MAX_ITEMS = 30;
const MAX_LEN = 80;

function cleanStrings(value, maxItems = MAX_ITEMS) {
  const list = Array.isArray(value) ? value : value ? [value] : [];
  const out = [];
  const seen = new Set();
  for (const raw of list) {
    const clean = String(raw || "").replace(/\s+/g, " ").trim().slice(0, MAX_LEN);
    if (!clean) continue;
    const key = clean.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(clean);
    if (out.length >= maxItems) break;
  }
  return out;
}

function mapResumeProfileToEnglishProfile(profile) {
  const p = profile && typeof profile === "object" ? profile : {};
  return {
    en_target_roles: cleanStrings(p.target_roles),
    en_skills: cleanStrings(p.skills),
    // ⚠️ 不再把技能复制进 en_target_keywords（2026-09-17 修）。中文侧 2026-09-02 就定了「技能与方向分家、
    // target_keywords 归用户自己填」（lib/resume-parser.js / upsertMergedPreferences），英文侧漏了：
    // 用户没填英文目标岗位时，lib/scoring.ts 会把关键词当方向信号（keywordsCountAsDirection），
    // 于是 en_skills=["Python","SQL"] 的用户会被推「Python DBA」——技能是「会什么」，判不了「想做什么」。
    en_target_keywords: [],
    has_en_resume: true,
  };
}

module.exports = {
  cleanStrings,
  mapResumeProfileToEnglishProfile,
};
