import { createServiceClient } from "@/lib/supabaseService";

export type CampusSourceInfo = { hasAnySource: boolean; hasCampusSource: boolean };

const CAMPUS_URL_RE = /campus|xiaozhao|校招|校园|campus_apply|\/campus/i;

// 判一条源是否是"校招板块"源：URL 命中 campus 特征，或 notes/source_url 标注校招。
function isCampusSource(url: string, notes: string): boolean {
  return CAMPUS_URL_RE.test(url) || CAMPUS_URL_RE.test(notes);
}

type SourceRow = { company: string | null; source_url: string | null; notes: string | null; enabled: boolean };

// ⚠️ sources 表已越过 1000 行（2026-07-20 实测 1121）：PostgREST 单次 select 默认封顶 1000 行会截断，
// 残缺集会漏掉尾部（往往是最新入库的源）→ 覆盖率判断失真。必须 .range() 分页拉全，
// 与 crawler/auto_discover.py 的 existing_source_keys() 同一分页写法对齐。
// 若后续行数回落到 1000 以下，这段分页仍然安全（第一页拿满整表即跳出循环，不会多打一次请求）。
async function fetchAllSources(): Promise<SourceRow[]> {
  const client = createServiceClient();
  const all: SourceRow[] = [];
  const step = 1000;
  let offset = 0;
  while (true) {
    const { data, error } = await client
      .from("sources")
      .select("company, source_url, notes, enabled")
      .range(offset, offset + step - 1);
    if (error) throw new Error(error.message);
    const rows = (data || []) as SourceRow[];
    all.push(...rows);
    if (rows.length < step) break;
    offset += step;
  }
  return all;
}

export async function getCampusSourceCoverage(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, CampusSourceInfo>> {
  const sources = await fetchAllSources();
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
