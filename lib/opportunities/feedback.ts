// 「不适合」结构化原因（§8.2 文案 → §5.2 reason_code）。单一事实来源：
// JobCard 渲染原因面板用 IGNORE_REASONS；action API 校验用 IGNORE_REASON_CODES。
// ⚠️ 与迁移 162 的 job_actions_reason_code_check 白名单保持一致，改一处两处同改。
export const IGNORE_REASONS = [
  { code: "role_mismatch", label: "岗位方向不对" },
  { code: "location_mismatch", label: "城市不合适" },
  { code: "industry_mismatch", label: "行业不合适" },
  { code: "seniority_mismatch", label: "经验级别不合适" },
  { code: "education_mismatch", label: "学历要求不合适" },
  { code: "compensation_mismatch", label: "薪资不合适" },
  { code: "company_not_interested", label: "对这家公司没兴趣" },
  { code: "already_seen_elsewhere", label: "已在别处看过" },
  { code: "not_job_seeking", label: "暂时不找工作" },
  { code: "other", label: "其他" },
] as const;

export type IgnoreReasonCode = (typeof IGNORE_REASONS)[number]["code"];

export const IGNORE_REASON_CODES: ReadonlySet<string> = new Set(IGNORE_REASONS.map((r) => r.code));
