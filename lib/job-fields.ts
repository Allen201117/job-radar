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

/**
 * 「截止」标签只放行**近未来的真实日期**，其余一律不显（返回 null）。
 *
 * 为什么需要（2026-09-15 创始人质疑「这截止时间可靠吗」后查实）：`jobs.deadline` 是**自由文本**列，
 * live 全库带值的 10 万个 active 岗里塞着大量占位/垃圾——「长期有效」45,229 个、「3000-01-01」15,066 个、
 * 「2079-11-30」「2030-12-31」这类远未来占位，还有约 1,248 个**已过期却仍 active**。此前卡面直接把原文
 * 塞进「截止 X」标签 → 会渲染出「截止 3000-01-01」「截止 长期有效」「截止 <已过去的日期>」这种不可信内容。
 * 这里与公司级的 `lib/recruitment-cycle.cleanCampusDeadlineMs` 同口径（那条给公司卡、这条给单岗展示）：
 *   · 必须是 YYYY-MM-DD（容忍带时间后缀，如 "2027-08-31 23:59:59"）；
 *   · 落在 [今天, 今天+550 天] 内——滤掉已过期 + 远未来占位。
 * 命中即返回归一后的 YYYY-MM-DD；否则 null（「长期有效」等非日期一律不作为「截止日期」展示）。
 */
export function cleanDeadlineText(raw?: string | null, now: Date = new Date()): string | null {
  const t = raw?.trim();
  if (!t) return null;
  const m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const iso = `${m[1]}-${m[2]}-${m[3]}`;
  const ms = Date.parse(iso + "T00:00:00Z");
  if (Number.isNaN(ms)) return null;
  const nowMs = now.getTime();
  if (ms < nowMs - 24 * 3600 * 1000) return null; // 已过期（留一天缓冲，避开时区/边界）
  if (ms > nowMs + 550 * 24 * 3600 * 1000) return null; // 远未来占位（3000-01-01 / 2079… ）
  return iso;
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
