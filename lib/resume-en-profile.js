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
  const enSkills = cleanStrings(p.skills);
  return {
    en_target_roles: cleanStrings(p.target_roles),
    en_skills: enSkills,
    en_target_keywords: enSkills,
    has_en_resume: true,
  };
}

module.exports = {
  cleanStrings,
  mapResumeProfileToEnglishProfile,
};
