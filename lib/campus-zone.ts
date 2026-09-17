// 校招专区纯函数：准入门 / 窗口态 / 排序 / 归组 / 看板聚合折叠。
// 无 LLM、无网络、无 DB —— 纯输入输出，独立可测。
// 纯 ESM export（不写 module.exports）；测试经 tests/_load-ts.js 转译加载（见 Global Constraints）。
import { recruitmentCategory } from "./china-keyword-expansion";
import { campusFacetKey } from "./campus-facets";
import { isCurrentSeasonGradClass } from "./grad-class";

export type CampusAdmission = "campus" | "intern" | "reject";

/** `recruitment_category` 物化列的合法取值；其余（NULL / 脏值）必须回到正文现算。 */
export const VALID_RECRUITMENT_CATEGORIES = ["校招", "实习", "社招"] as const;

// 专区准入门：直接复用 recruitmentCategory（已精度优先，弱词不判校招）。
// campus = 进默认列表；intern = 单独可筛桶；reject = 不进专区（社招/无信号）。
export function campusAdmission(job: any = {}): CampusAdmission {
  // 库里的 recruitment_category 就是同一份 JS 分类器算出来的（crawler/recruitment_classify.py 隔进程调
  // lib/china-keyword-expansion.js；触发器 jobs_guard_recruitment_class 在分类依据变化时置 NULL）。
  // 2026-09-09 live 对拍互联网清单 30 家 20,311 行：列与现算**零不一致**。有值就直接认，
  // 现算只兜 NULL ——这样专区取数不必为了判桶把 6.5MB 正文拖回函数。
  // ⚠️ NULL 不是「全库 36 行」那么少（旧注释与 CLAUDE.md 都这么写，2026-09-18 实测**不成立**）：
  //    触发器在分类依据变化时置 NULL、2h 补漏 cron 才重算，所以任一时刻都有一批在途——
  //    实测 493,067 个 active 岗里 **18,731 行（3.8%）** recruitment_category 为 NULL、882 行 job_function 为 NULL。
  //    凡是「靠列取数」的地方都必须给这批行留一条现算兜底路径（见 foldCampusZone 的 rowLevel 入参）。
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

// ────────────────────────────────────────────────────────────────────────────
// 看板聚合折叠（2026-09-18）：把「一岗一行拉回函数再在 JS 里筛」换成「SQL 先 group by、JS 只折叠」
//
// 病灶（实测）：旧 getCampusZone 对互联网清单 30 家一次拉回 **21,607 行 / 7.0 MB**，
// 而这坨数据的**唯一去向**是压成 ~1,900 个 (城市,学历,职能,届别) 四元组 + 每家的计数/最近截止/最近抓取。
// 7 MB 里 jd_url + apply_url 两列长 URL 就占一大截，而它们只在「recruitment_category 为 NULL、
// 要回正文现算分类」的极少数行上才被读到。香港库出口带宽是个位数 Mbps，这 7 MB 是纯粹的过路费。
//
// 改法 = 把 group by 下推给库：(company, location, education, job_function, grad_class,
// recruitment_category, deadline) + count(*) + max(last_seen_at)。同一批数据 21,607 行 → 3,609 组。
// 「列判不出桶/职能」的行（NULL 或脏值）单独走 rowLevel 一条小查询，带正文回来现算，保总数精确。
//
// ⚠️ 两条不变量（漂了就是卡面计数静静地错）：
//   ① trim / 分类 一律在 **JS 侧**做（SQL 的 btrim 只认 ASCII 空白，JS 的 .trim() 还吃全角空格 U+3000），
//      所以 SQL 原样返回 location/education，这里 trim 后再合并同键组 —— 与逐行口径逐字相同。
//   ② 归属（哪个 pattern 得这家公司）/ 届别门 / 准入门 三处判据与 getCampusCompanyJobs、
//      getCampusFreshStats 逐字一致：list 里**第一个** pattern 命中者得。
// ────────────────────────────────────────────────────────────────────────────

/** SQL 聚合行：一行 = 一个 (公司,城市,学历,职能,届别,招聘类型,截止日) 组。 */
export type CampusZoneAggregateRow = {
  company: string | null;
  location: string | null;
  education: string | null;
  job_function: string | null;
  grad_class: number | null;
  recruitment_category: string | null;
  deadline: string | null;
  n: number | string;
  last_seen: string | null;
};

/** 折叠后的分面组：分面四维 + 截止日 + 这一组代表多少个岗。 */
export type CampusGroup = {
  city: string;
  education: string;
  fn: string;
  gc: number | null;
  deadline: string | null;
  count: number;
};

export type CampusCompanyRow = {
  company: string;          // 必投清单展示名
  pattern: string;
  campusGroups: CampusGroup[]; // 通过准入门 campus 的分面组
  internGroups: CampusGroup[]; // intern 桶
  campusTotal: number;
  internTotal: number;
  hasAnyActiveJob: boolean; // 该公司「校招相关粗筛」里有没有岗（判 source_only_social 的输入之一，非严格任意在招）
  lastSeenAtMs: number | null;
  pastClassJobCount: number; // 明确标了往届（如秋招期库里没下架干净的 2026 届）而被移出列表的岗数，供卡面诚实说明
};

type Acc = CampusCompanyRow & { _campus: Map<string, CampusGroup>; _intern: Map<string, CampusGroup> };

function groupId(g: Omit<CampusGroup, "count">): string {
  return `${g.city} ${g.education} ${g.fn} ${g.gc ?? ""} ${g.deadline ?? ""}`;
}

/**
 * 把「SQL 聚合行 + 少量逐行兜底行」折叠成每家公司的看板输入。
 *
 * @param list         必投清单（顺序即归属优先级：第一个 pattern 命中者得）
 * @param aggregate    `CAMPUS_ZONE_AGGREGATE_SQL` 的结果（列判得出桶与职能的那批）
 * @param rowLevel     `CAMPUS_ZONE_ROW_LEVEL_SQL` 的结果（列为 NULL/脏值，需要正文现算的那批完整行）
 * @param now          届别门的「当季」基准（测试可注入）
 */
export function foldCampusZone(
  list: Array<{ name: string; pattern: string }>,
  aggregate: CampusZoneAggregateRow[],
  rowLevel: any[],
  now: Date = new Date(),
): CampusCompanyRow[] {
  const byName = new Map<string, Acc>();
  for (const c of list) {
    byName.set(c.name, {
      company: c.name, pattern: c.pattern,
      campusGroups: [], internGroups: [], campusTotal: 0, internTotal: 0,
      hasAnyActiveJob: false, lastSeenAtMs: null, pastClassJobCount: 0,
      _campus: new Map(), _intern: new Map(),
    });
  }
  const needles = list.map((c) => c.pattern.replace(/%/g, "").toLowerCase());
  const ownerOf = (company: unknown): Acc | null => {
    const lower = String(company ?? "").toLowerCase();
    if (!lower) return null;
    const i = needles.findIndex((n) => lower.includes(n));
    return i < 0 ? null : byName.get(list[i].name) ?? null;
  };

  /** 一组（或一行，count=1）计入某家公司。与旧逐行实现同序：先记 hasAny/lastSeen，再判桶、再判届别。 */
  const take = (
    agg: Acc,
    lastSeen: string | null,
    admission: CampusAdmission,
    key: { city: string; education: string; fn: string; gc: number | null },
    deadline: string | null,
    count: number,
  ) => {
    agg.hasAnyActiveJob = true;
    const seen = lastSeen ? Date.parse(String(lastSeen)) : NaN;
    if (!Number.isNaN(seen)) agg.lastSeenAtMs = Math.max(agg.lastSeenAtMs ?? 0, seen);
    if (admission === "reject") return;
    if (!isCurrentSeasonGradClass(key.gc, now)) {
      agg.pastClassJobCount += count;
      return;
    }
    const bucket = admission === "campus" ? agg._campus : agg._intern;
    const g: Omit<CampusGroup, "count"> = { city: key.city, education: key.education, fn: key.fn, gc: key.gc, deadline };
    const id = groupId(g);
    const hit = bucket.get(id);
    if (hit) hit.count += count;
    else bucket.set(id, { ...g, count });
    if (admission === "campus") agg.campusTotal += count;
    else agg.internTotal += count;
  };

  for (const r of aggregate) {
    const agg = ownerOf(r.company);
    if (!agg) continue;
    const count = Number(r.n) || 0;
    if (count <= 0) continue;
    // 列判得出：准入门只看 recruitment_category 列（SQL 侧已保证取值合法），职能直接用 job_function 列。
    const admission = campusAdmission({ recruitment_category: r.recruitment_category });
    take(
      agg, r.last_seen, admission,
      {
        city: String(r.location ?? "").trim(),
        education: String(r.education ?? "").trim(),
        fn: String(r.job_function ?? ""),
        gc: typeof r.grad_class === "number" ? r.grad_class : null,
      },
      r.deadline ?? null,
      count,
    );
  }

  // 列为 NULL / 脏值的少数行：带正文回来，走与逐行实现**完全相同**的 campusAdmission + campusFacetKey。
  for (const r of rowLevel) {
    if (!r || !r.id || !r.company) continue;
    const agg = ownerOf(r.company);
    if (!agg) continue;
    take(agg, r.last_seen_at ?? null, campusAdmission(r), campusFacetKey(r), r.deadline ?? null, 1);
  }

  return list.map((c) => {
    const a = byName.get(c.name)!;
    a.campusGroups = Array.from(a._campus.values());
    a.internGroups = Array.from(a._intern.values());
    const { _campus, _intern, ...row } = a;
    return row;
  });
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
