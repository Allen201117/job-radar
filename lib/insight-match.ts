// ============================================================
// 模块 B — 公司匹配（纯函数）
// 把 jobs.company 的自由写法（苹果 / Apple、字节 / 字节跳动 / ByteDance、
// 微软（中国）/ Microsoft）对齐到 company_profiles 的画像（company + aliases）。
// ============================================================

import type { CompanyProfile } from "./types";

// 归一化：小写、去空白与常见公司后缀/地域装饰，便于宽松比对
const STRIP_PATTERNS: RegExp[] = [
  /（中国）|\(china\)|（大中华区）|中国区|大中华区/gi,
  /有限公司|股份有限公司|科技有限公司|集团|公司|股份|控股/g,
  /\b(inc|ltd|llc|co|corp|corporation|company|technologies|technology|holdings|group)\b/gi,
  /[\s.,，。、_\-—·&'"’]/g,
];

export function normalizeCompany(input: string | null | undefined): string {
  if (!input) return "";
  let s = String(input).toLowerCase().trim();
  for (const re of STRIP_PATTERNS) {
    s = s.replace(re, "");
  }
  return s;
}

// query 是否命中某个画像的 company 或任一 alias
export function companyMatches(
  profile: Pick<CompanyProfile, "company" | "aliases">,
  query: string,
): boolean {
  const q = normalizeCompany(query);
  if (!q) return false;
  const names = [profile.company, ...(profile.aliases || [])]
    .map(normalizeCompany)
    .filter(Boolean);
  return names.some((n) => n === q || n.includes(q) || q.includes(n));
}

// 在画像列表中找最佳匹配：优先归一化全等，其次子串包含
export function findCompanyProfile(
  profiles: CompanyProfile[],
  query: string,
): CompanyProfile | null {
  const q = normalizeCompany(query);
  if (!q) return null;

  let substringHit: CompanyProfile | null = null;
  for (const p of profiles) {
    const names = [p.company, ...(p.aliases || [])].map(normalizeCompany).filter(Boolean);
    if (names.some((n) => n === q)) return p; // 全等优先
    if (!substringHit && names.some((n) => n.includes(q) || q.includes(n))) {
      substringHit = p;
    }
  }
  return substringHit;
}
