import { createServiceClient } from "@/lib/supabaseService";
import { fetchAllSources } from "@/lib/supabase-paginate";

export type CampusSourceInfo = { hasAnySource: boolean; hasCampusSource: boolean };

const CAMPUS_URL_RE = /campus|xiaozhao|校招|校园|campus_apply|\/campus/i;

// 判一条源是否是"校招板块"源：URL 命中 campus 特征，或 notes/source_url 标注校招。
function isCampusSource(url: string, notes: string): boolean {
  return CAMPUS_URL_RE.test(url) || CAMPUS_URL_RE.test(notes);
}

type SourceRow = { company: string | null; source_url: string | null; notes: string | null; enabled: boolean };

export async function getCampusSourceCoverage(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, CampusSourceInfo>> {
  // ⚠️ 必须分页拉全量（sources 已越过 PostgREST 单次 1000 行上限，2026-07-20 实测 1121）：
  // 残缺集会漏掉尾部（往往是最新入库的源）→ 覆盖率判断失真。分页语义见 lib/supabase-paginate.ts。
  const sources = await fetchAllSources<SourceRow>(
    createServiceClient(),
    "company, source_url, notes, enabled",
  );
  const out = new Map<string, CampusSourceInfo>();
  for (const c of list) {
    const needle = c.pattern.replace(/%/g, "").toLowerCase();
    const matched = sources.filter((s) => (s.company || "").toLowerCase().includes(needle) && s.enabled);
    const hasAnySource = matched.length > 0;
    const hasCampusSource = matched.some((s) => isCampusSource(s.source_url || "", s.notes || ""));
    out.set(c.pattern, { hasAnySource, hasCampusSource });
  }
  return out;
}
