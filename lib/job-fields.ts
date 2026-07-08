export function extractExperience(text?: string | null): string {
  if (!text) return "未知";
  const t = text.replace(/\s+/g, "");
  if (/应届|无经验要求|经验不限|不限经验|noexperience|entrylevel/i.test(t)) return "应届/不限";
  let m = t.match(/(\d+)[-~至到](\d+)年/) || t.match(/(\d+)年(?:以上)?(?:工作)?经验/);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  // 英文：3-5 years / 5+ years / 3 years experience（空格已去除）
  m = t.match(/(\d+)[-~to]+(\d+)years?/i) || t.match(/(\d+)\+?years?(?:ofexperience)?/i);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  return "未知";
}

export function extractEducation(text?: string | null): string {
  if (!text) return "未知";
  if (/博士|ph\.?d|doctora/i.test(text)) return "博士";
  if (/硕士|研究生|master/i.test(text)) return "硕士";
  if (/本科|学士|bachelor|undergrad/i.test(text)) return "本科";
  if (/大专|专科/.test(text)) return "大专";
  if (/学历不限|不限学历/.test(text)) return "不限";
  return "未知";
}

export function extractDeadline(text?: string | null): string {
  if (!text) return "未知";
  if (/长期有效|长期招聘|long[\s-]?term|rolling|until filled/i.test(text)) return "长期有效";
  const m = text.match(
    /(?:截止|截至|申请截止|投递截止|deadline)[^0-9]{0,8}(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2})/i,
  );
  if (m) return m[1].replace(/[年月]/g, "-").replace(/[./]/g, "-").replace(/-+$/, "");
  return "未知";
}

const MISSING_DISPLAY_VALUES = new Set([
  "未知",
  "官网未披露",
  "未披露",
  "暂未披露",
  "暂无",
  "无",
  "n/a",
  "na",
  "null",
  "undefined",
  "-",
  "--",
]);

export function jobFieldDisplayValue(value?: string | null): string | null {
  const text = value?.trim();
  if (!text) return null;
  if (MISSING_DISPLAY_VALUES.has(text.toLowerCase())) return null;
  return text;
}

export function hasJobFieldValue(value?: string | null): boolean {
  return jobFieldDisplayValue(value) !== null;
}
