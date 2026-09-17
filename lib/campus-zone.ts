// 校招专区纯函数：准入门 / 窗口态 / 排序 / 归组。无 LLM、无网络、无 DB —— 纯输入输出，独立可测。
// 纯 ESM export（不写 module.exports）；测试经 tests/_load-ts.js 转译加载（见 Global Constraints）。
import { recruitmentCategory } from "./china-keyword-expansion";

export type CampusAdmission = "campus" | "intern" | "reject";

/** 专区的两种模式。两个视图（全部校招岗 / 必投 30 家）共用同一个状态。 */
export type RecruitMode = "campus" | "intern";

/** 专区顶部的两种视图。默认 `all`（创始人 2026-09-18 定：专区 = 校招岗位库，不是 30 家公司）。 */
export type CampusView = "all" | "must";

/** 上次选的视图记在这个 localStorage 键下；读写都必须包 try/catch（隐私窗口会抛）。 */
export const CAMPUS_VIEW_STORAGE_KEY = "campus-view";

export function isCampusView(value: unknown): value is CampusView {
  return value === "all" || value === "must";
}

/**
 * 模式 → `/api/jobs/search` 的 `jobType` 取值。
 *
 * ⚠️ 这两个字符串必须与 `lib/job-filter.ts` 的三桶分类、以及 `lib/jobs-store/search.ts` 的
 * `appendRecruitmentPrefilter` 逐字一致 —— 那边是 `recruitment_category = '校招'` 这种字面量比较，
 * 这里写错一个字不会报错，只会让专区返回空列表。
 */
export const CAMPUS_MODE_JOB_TYPE: Record<RecruitMode, string> = {
  campus: "校招",
  intern: "实习",
};

/**
 * 把 `jobType` 强制写成当前模式对应的值。
 *
 * 为什么需要它：「全部校招岗」视图用 `/api/jobs/search`，而那条接口一旦 `jobType` 为空就会
 * 返回**全库岗位（含社招）**。这是**静默**失效——页面照常渲染、不报错、不变慢，只是校招专区
 * 悄悄变成了岗位库。所以每一个会写 filters 的路径（切模式 / 清空全部 / 清空单项）都必须过这个函数。
 *
 * ⚠️ 别把它「简化」成只在切模式时调一次：清空按钮走的是另一条路（`DEFAULT_FILTERS.jobType === ""`），
 * 漏掉它就正好把 jobType 抹掉。三条泄漏路径见 docs/superpowers/specs/2026-09-18-campus-zone-*。
 */
export function withCampusMode<T extends { jobType: string }>(filters: T, mode: RecruitMode): T {
  const jobType = CAMPUS_MODE_JOB_TYPE[mode];
  return filters.jobType === jobType ? filters : { ...filters, jobType };
}

/**
 * 「清空全部」在专区里的语义：回到默认筛选，但**保留**排序偏好与当前模式的 jobType。
 *
 * 排序保留的理由与 `useJobFilters.clearAll` 一致（排序是展示偏好不是筛选条件，
 * 用户刚切「按发布时间」不该被静默改回去）；jobType 保留的理由见 `withCampusMode`。
 */
export function campusResetFilters<T extends { jobType: string; sortBy: string }>(
  defaults: T,
  current: T,
  mode: RecruitMode,
): T {
  return withCampusMode({ ...defaults, sortBy: current.sortBy } as T, mode);
}

// 专区准入门：直接复用 recruitmentCategory（已精度优先，弱词不判校招）。
// campus = 进默认列表；intern = 单独可筛桶；reject = 不进专区（社招/无信号）。
export function campusAdmission(job: any = {}): CampusAdmission {
  // 库里的 recruitment_category 就是同一份 JS 分类器算出来的（crawler/recruitment_classify.py 隔进程调
  // lib/china-keyword-expansion.js；触发器 jobs_guard_recruitment_class 在分类依据变化时置 NULL）。
  // 2026-09-09 live 对拍互联网清单 30 家 20,311 行：列与现算**零不一致**。有值就直接认，
  // 现算只兜 NULL（全库 36 行）——这样专区取数不必为了判桶把 6.5MB 正文拖回函数。
  const stored = job?.recruitment_category;
  const cat = stored === "校招" || stored === "实习" || stored === "社招" ? stored : recruitmentCategory(job);
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

/**
 * 「对你有货优先」的卡片排序（2026-09-17）。
 *
 * 必投清单本身**保持静态**（北极星口径，见 docs/reviews/2026-09-17-core-features-adversarial-review.md §5），
 * 这里只换看板的**呈现顺序**：清单 ∩「有该用户对得上的校招/实习岗」的公司先看。
 *
 * 排序键（依次）：
 *   ① 有没有对口岗（`fitCount > 0` 在前，0 沉底）—— 用户抱怨的正是「点进来先看到一排 0 岗的卡」；
 *   ② 窗口态 WINDOW_ORDER（招聘中 > 未观测到 > 待更新 > 待接入）—— 桶内仍保持原有语义；
 *   ③ 对口岗数降序；判不出用户方向时（`fitCount == null`）退回**总岗数**降序；
 *   ④ 最近截止（compareCompanyCards 的原有尾部规则）。
 *
 * ⚠️ `fitCount == null` 表示「这个用户判不出方向」，对全体卡片同时成立 → ① 恒同组、③ 退回总数，
 * 净效果 = 旧行为 + 总数兜底，不会只对部分卡生效而造成半套排序。
 */
export function compareCompanyCardsByFit(a: any, b: any): number {
  const fa: number | null = typeof a.fitCount === "number" ? a.fitCount : null;
  const fb: number | null = typeof b.fitCount === "number" ? b.fitCount : null;
  const ba = fa != null && fa > 0 ? 0 : 1;
  const bb = fb != null && fb > 0 ? 0 : 1;
  if (fa != null && fb != null && ba !== bb) return ba - bb;

  const oa = WINDOW_ORDER[a.window.state], ob = WINDOW_ORDER[b.window.state];
  if (oa !== ob) return oa - ob;

  const ra = fa != null ? fa : (a.fitTotal ?? 0);
  const rb = fb != null ? fb : (b.fitTotal ?? 0);
  if (ra !== rb) return rb - ra;

  return compareCompanyCards(a, b);
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
