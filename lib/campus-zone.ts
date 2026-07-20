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

// Placeholder stubs for future tasks (Task 2-5)
export function windowStatus(job: any = {}): string {
  throw new Error("Not implemented");
}

export function compareCampusJobs(a: any, b: any): number {
  throw new Error("Not implemented");
}

export function compareCompanyCards(a: any, b: any): number {
  throw new Error("Not implemented");
}

export function groupCampusJobs(jobs: any[] = []): any {
  throw new Error("Not implemented");
}
