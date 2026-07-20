// 校招专区纯函数：准入门 / 窗口态 / 排序 / 归组。无 LLM、无网络、无 DB —— 纯输入输出，独立可测。
// 纯 ESM export（不写 module.exports）；测试经 tests/_load-ts.js 转译加载（见 Global Constraints）。
import { recruitmentCategory } from "./china-keyword-expansion";

export type CampusAdmission = "campus" | "intern" | "reject";

// 专区准入门：直接复用 recruitmentCategory（已精度优先，弱词不判校招）。
// campus = 进默认列表；intern = 单独可筛桶；reject = 不进专区（社招/无信号）。
export function campusAdmission(job: any = {}): CampusAdmission {
  const cat = recruitmentCategory(job);
  if (cat === "实习") return "intern";
  if (cat === "校招") return "campus";
  return "reject";
}

export type WindowState = {
  state: "hiring" | "no_campus_now" | "not_ingested" | "stale";
  subReason?: "no_source" | "source_only_social" | "crawl_error";
};

const DEFAULT_FRESHNESS_MS = 72 * 3600 * 1000;

export function windowStatus(input: any): WindowState {
  const { campusJobCount, hasCampusSource, hasAnySource, lastSeenAtMs, nowMs } = input;
  const threshold = input.freshnessThresholdMs ?? DEFAULT_FRESHNESS_MS;

  // campusJobCount 权威化：有真实校招岗（哪怕源 URL 不含 campus 令牌，如飞书/moka/beisen
  // 通用租户靠 job_type=校招 识别）就不能判待接入，否则卡面列着岗却说「待接入」自相矛盾。
  if (campusJobCount > 0) {
    // 但数据太旧 → 降级，不拿旧数据冒充在招。
    if (lastSeenAtMs != null && nowMs - lastSeenAtMs > threshold) {
      return { state: "stale" };
    }
    return { state: "hiring" };
  }
  // 无校招岗时才看有没有校招源 → 诚实告知待接入（区分尚未接入 / 只接了社招）。
  if (hasCampusSource) return { state: "no_campus_now" };
  return { state: "not_ingested", subReason: hasAnySource ? "source_only_social" : "no_source" };
}

function ms(x: any): number | null {
  if (!x) return null;
  const t = Date.parse(x);
  return Number.isNaN(t) ? null : t;
}

export function compareCampusJobs(a: any, b: any): number {
  const da = ms(a.deadline), db = ms(b.deadline);
  if (da != null && db != null) return da - db;   // 都有截止 → 临近优先
  if (da != null) return -1;                       // 有截止的排前
  if (db != null) return 1;
  const fa = ms(a.first_seen_at) || 0, fb = ms(b.first_seen_at) || 0;
  return fb - fa;                                   // 都无截止 → 新增降序
}

export const WINDOW_ORDER: Record<string, number> = {
  hiring: 0, no_campus_now: 1, stale: 2, not_ingested: 3,
};

export function compareCompanyCards(a: any, b: any): number {
  const oa = WINDOW_ORDER[a.window.state], ob = WINDOW_ORDER[b.window.state];
  if (oa !== ob) return oa - ob;
  const na = a.nearestDeadlineMs, nb = b.nearestDeadlineMs;
  if (na != null && nb != null) return na - nb;
  if (na != null) return -1;
  if (nb != null) return 1;
  return 0;
}

export function groupCampusJobs(jobs: any[]): any[] {
  const buckets = new Map<string, any[]>();
  for (const j of jobs || []) {
    const key = (j.city || "").trim() || "其他";
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(j);
  }
  const groups = Array.from(buckets.entries()).map(([key, gj]) => ({
    key, label: key, jobs: gj.slice().sort(compareCampusJobs),
  }));
  groups.sort((a, b) => b.jobs.length - a.jobs.length);
  return groups;
}
