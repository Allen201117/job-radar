const NONE = [
  /\bdo(?:es)? not sponsor\b/i,
  /\bno (?:visa )?sponsorship\b/i,
  /\bunable to (?:provide|offer) (?:visa )?sponsorship\b/i,
  /without (?:visa )?sponsorship\b/i,
  /must be authorized to work in the u\.?s/i,
  /u\.?s\.? citizens? only/i,
  /security clearance/i,
  /not (?:able|eligible) to sponsor\b/i,
];

const AVAILABLE = [
  /\b(?:visa )?sponsorship (?:is )?available\b/i,
  /\bwill sponsor\b/i,
  /\bwe sponsor\b/i,
  /\bh-?1b sponsorship\b/i,
  /sponsorship (?:is )?(?:provided|offered)\b/i,
  /relocation and visa (?:support )?(?:provided|available)?\b/i,
];

function sponsorshipSignal(text) {
  const t = String(text || "");
  if (!t.trim()) return "unknown";
  if (NONE.some((r) => r.test(t))) return "none";
  if (AVAILABLE.some((r) => r.test(t))) return "available";
  return "unknown";
}

module.exports = { sponsorshipSignal };
