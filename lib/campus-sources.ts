import { createServiceClient } from "@/lib/supabaseService";
import { fetchAllSources } from "@/lib/supabase-paginate";
import { boardCoversCampus } from "@/lib/source-board";

export type CampusSourceInfo = { hasAnySource: boolean; hasCampusSource: boolean };

// 「是不是校招源」改读 DB 派生列 sources.board（迁移 187），不再在应用层正则扫 URL。
// 旧实现 `/campus|校招|…/i` 扫 source_url 有两个已实测的错判：
//   · 假阳性：阿里 13 个 BU 的**社招**频道地址字面是 `…/off-campus/position-list`，被裸 campus 正则命中；
//   · 假阴性：beisen 发 Category:[] 一次抓全类别，URL 是 /social 的 113 个源照样产 2094 个校招岗。
// board 由 (adapter_name, source_url) 在 SQL 侧统一派生，判据与 mixed 名单写在迁移 187 注释里，单一权威。
type SourceRow = { company: string | null; board: string | null; enabled: boolean };

export async function getCampusSourceCoverage(
  list: Array<{ name: string; pattern: string }>,
): Promise<Map<string, CampusSourceInfo>> {
  // ⚠️ 必须分页拉全量（sources 已越过 PostgREST 单次 1000 行上限，2026-07-20 实测 1121）：
  // 残缺集会漏掉尾部（往往是最新入库的源）→ 覆盖率判断失真。分页语义见 lib/supabase-paginate.ts。
  const sources = await fetchAllSources<SourceRow>(
    createServiceClient(),
    "company, board, enabled",
  );
  const out = new Map<string, CampusSourceInfo>();
  for (const c of list) {
    const needle = c.pattern.replace(/%/g, "").toLowerCase();
    const matched = sources.filter((s) => (s.company || "").toLowerCase().includes(needle) && s.enabled);
    const hasAnySource = matched.length > 0;
    const hasCampusSource = matched.some((s) => boardCoversCampus(s.board));
    out.set(c.pattern, { hasAnySource, hasCampusSource });
  }
  return out;
}
