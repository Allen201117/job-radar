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
  const threshold = input.freshnessThresholdMs || DEFAULT_FRESHNESS_MS;

  // 无校招源 → 诚实告知待接入（区分尚未接入 / 只接了社招）。
  if (!hasCampusSource) {
    return { state: "not_ingested", subReason: hasAnySource ? "source_only_social" : "no_source" };
  }
  // 有校招源但数据太旧 → 降级，不拿旧数据冒充在招。
  if (lastSeenAtMs != null && nowMs - lastSeenAtMs > threshold) {
    return { state: "stale" };
  }
  if (campusJobCount > 0) return { state: "hiring" };
  return { state: "no_campus_now" };
}
