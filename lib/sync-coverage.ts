// syncCoverage 的纯计算核心（无 DB 调用，可单测）。
// 从 targetCompanies + enabled sources + 现有 watch_requests 推导出：
//   rows: 要 upsert 的行（不含 user_id / updated_at，由调用方补全）
//   staleIds: 要 delete 的行 id（不再 target 的 normalized_company 对应的行）
import { normalizeCompany } from "@/lib/company-normalize";

export interface EnabledSource {
  id: string;
  company: string | null;
}

export interface ExistingEntry {
  id: string;
  normalized_company: string;
  status: string;
}

export interface CoverageRow {
  company: string;
  normalized_company: string;
  status: string;
  matched_source_ids: string[];
}

export function buildCoverageRows(
  targetCompanies: string[],
  enabledSources: EnabledSource[],
  existingEntries: ExistingEntry[],
): { rows: CoverageRow[]; staleIds: string[] } {
  // source 归一映射：norm → source id 列表
  const sourceMap = new Map<string, string[]>();
  for (const s of enabledSources) {
    const norm = normalizeCompany(s.company);
    if (!norm) continue;
    const arr = sourceMap.get(norm) || [];
    arr.push(s.id);
    sourceMap.set(norm, arr);
  }

  // 现有 watch 状态：normalized_company → status（用于保留 researching / unsupported 状态）
  const existingStatus = new Map<string, string>();
  for (const e of existingEntries) existingStatus.set(e.normalized_company, e.status);

  const keptNorms = new Set<string>();
  const rows: CoverageRow[] = [];
  for (const company of targetCompanies) {
    const norm = normalizeCompany(company);
    if (!norm || keptNorms.has(norm)) continue;
    keptNorms.add(norm);
    const matched = sourceMap.get(norm) || [];
    const prev = existingStatus.get(norm);
    const status = matched.length
      ? "covered"
      : prev === "researching" || prev === "unsupported"
        ? prev
        : "queued";
    rows.push({ company, normalized_company: norm, status, matched_source_ids: matched });
  }

  // 不再 target 的行 → stale，由调用方 delete
  const staleIds = existingEntries
    .filter((e) => !keptNorms.has(e.normalized_company))
    .map((e) => e.id);

  return { rows, staleIds };
}
