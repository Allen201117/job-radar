// 校招专区的「聚合分面」：把岗位压成 (城市, 学历, 职能, 届别) → 计数，取代逐条下发岗位记录。
//
// 为什么存在：/campus 原先给客户端下发每一条岗位的轻量记录，30 家必投公司下**单页 16,494 条、
// 2.09 MB HTML**，首屏 responseEnd 实测 10.1s。但客户端拿这些记录只做两件事——填筛选下拉、
// 算「当前筛选下有几个岗」，两件事都只依赖上面那四个维度，与具体是哪个岗无关。
// 于是同一四元组的岗合并成一个计数：live 实测 16,494 条压成 1,917 个四元组（8.6:1），
// **任意筛选组合下的计数与逐条过滤逐位相同**（等价性由 tests/campus-facets.test.js 钉死）。
//
// 构建（服务端 buildCampusFacets）与匹配（客户端 countMatchingFacets）刻意放在同一文件：
// 下标口径一旦两边漂了，卡面计数就会错，而这种错不会报错、只会静静地骗用户。
import { classifyJobFunction } from "@/lib/china-keyword-expansion";

/** 一条分面：`[城市下标, 学历下标, 职能下标, 届别, 岗位数]`。
 *  前三个下标指向 CampusFilterOptions 里对应的选项数组；`-1` = 该维度为空（只被「全部」匹配到）。 */
export type CampusFacet = [number, number, number, number | null, number];

export type CampusFilterOptions = {
  cityOptions: string[];
  educationOptions: string[];
  functionOptions: string[];
  gradClassOptions: number[];
};

export type CampusFilterValues = {
  city: string;
  education: string;
  jobFunction: string;
  gradClass: number | null;
};

/** 筛选值翻成的下标：`-1` = 该维度没筛（匹配全部）；`NO_MATCH` = 筛了个当前选项表里没有的值。 */
export type CampusFacetSelection = {
  city: number;
  education: number;
  fn: number;
  gc: number | null;
};

/** 哨兵：筛选值在当前模式的选项表里不存在（切校招/实习后可能出现）→ 匹配不到任何分面、计数为 0。
 *  与逐条实现「字符串比不中」同义。 */
export const NO_MATCH = -2;

/** 单条岗位在四个筛选维度上的取值。城市/学历取 trim 后的值，空串表示该岗没有这个字段。 */
export function campusFacetKey(job: any): {
  city: string;
  education: string;
  fn: string;
  gc: number | null;
} {
  return {
    city: String(job?.city ?? "").trim(),
    education: String(job?.education ?? "").trim(),
    // 服务端用**完整 summary** 算职能，与客户端此前现算的是同一份实现、同一份输入 → 精度零损失。
    fn: classifyJobFunction({ title: job?.title, job_type: job?.job_type, summary: job?.summary }),
    gc: typeof job?.grad_class === "number" ? job.grad_class : null,
  };
}

/**
 * 把某个模式（校招 / 实习）下所有公司的岗位压成分面。
 * 下拉候选值的收集口径与逐条实现逐字一致（同样 trim / filter(Boolean) / sort），
 * 分面里的下标就指向这几个数组。
 */
export function buildCampusFacets(lists: Array<{ pattern: string; jobs: any[] }>): {
  options: CampusFilterOptions;
  byPattern: Map<string, CampusFacet[]>;
  totals: Map<string, number>;
} {
  const cities = new Set<string>();
  const edus = new Set<string>();
  const fns = new Set<string>();
  const gradClasses = new Set<number>();
  const keysByPattern = new Map<string, ReturnType<typeof campusFacetKey>[]>();

  for (const { pattern, jobs } of lists) {
    const keys = (jobs || []).map(campusFacetKey);
    keysByPattern.set(pattern, keys);
    for (const k of keys) {
      if (k.city) cities.add(k.city);
      if (k.education) edus.add(k.education);
      fns.add(k.fn);
      if (k.gc !== null) gradClasses.add(k.gc);
    }
  }

  const options: CampusFilterOptions = {
    cityOptions: Array.from(cities).filter(Boolean).sort(),
    educationOptions: Array.from(edus).filter(Boolean).sort(),
    functionOptions: Array.from(fns).filter(Boolean).sort(),
    gradClassOptions: Array.from(gradClasses).sort((a, b) => b - a),
  };
  const cityIdx = new Map(options.cityOptions.map((v, i) => [v, i]));
  const eduIdx = new Map(options.educationOptions.map((v, i) => [v, i]));
  const fnIdx = new Map(options.functionOptions.map((v, i) => [v, i]));

  const byPattern = new Map<string, CampusFacet[]>();
  const totals = new Map<string, number>();
  for (const [pattern, keys] of keysByPattern) {
    const counts = new Map<string, CampusFacet>();
    for (const k of keys) {
      const c = k.city ? cityIdx.get(k.city) ?? NO_MATCH : -1;
      const e = k.education ? eduIdx.get(k.education) ?? NO_MATCH : -1;
      const f = fnIdx.get(k.fn) ?? -1;
      const id = `${c}|${e}|${f}|${k.gc ?? ""}`;
      const hit = counts.get(id);
      if (hit) hit[4] += 1;
      else counts.set(id, [c, e, f, k.gc, 1]);
    }
    byPattern.set(pattern, Array.from(counts.values()));
    totals.set(pattern, keys.length);
  }
  return { options, byPattern, totals };
}

/** 把当前筛选值翻成分面下标。选项表来自服务端下发的当前模式选项。 */
export function selectFacetIndexes(
  filters: CampusFilterValues,
  options: CampusFilterOptions,
): CampusFacetSelection {
  const pick = (value: string, list: string[]) => {
    if (!value) return -1;
    const i = list.indexOf(value);
    return i >= 0 ? i : NO_MATCH;
  };
  return {
    city: pick(filters.city, options.cityOptions),
    education: pick(filters.education, options.educationOptions),
    fn: pick(filters.jobFunction, options.functionOptions),
    gc: filters.gradClass,
  };
}

export function facetMatches(f: CampusFacet, sel: CampusFacetSelection): boolean {
  if (sel.city !== -1 && f[0] !== sel.city) return false;
  if (sel.education !== -1 && f[1] !== sel.education) return false;
  if (sel.fn !== -1 && f[2] !== sel.fn) return false;
  if (sel.gc !== null && f[3] !== sel.gc) return false;
  return true;
}

/** 当前筛选下这批分面代表多少个岗。 */
export function countMatchingFacets(facets: CampusFacet[], sel: CampusFacetSelection): number {
  let n = 0;
  for (const f of facets || []) if (facetMatches(f, sel)) n += f[4];
  return n;
}

/**
 * 单条**完整岗位行**是否通过当前筛选（展开区用）。
 * `row.fn` 由 /api/campus-zone/jobs 随行返回（服务端算），与分面里的职能标签同源同值 →
 * 客户端不重跑分类器，也不会两处算出不同结果。
 */
export function campusRowMatches(row: any, filters: CampusFilterValues): boolean {
  if (filters.city && String(row?.city ?? "").trim() !== filters.city) return false;
  if (filters.education && String(row?.education ?? "").trim() !== filters.education) return false;
  if (filters.jobFunction && row?.fn !== filters.jobFunction) return false;
  if (filters.gradClass !== null && (typeof row?.grad_class === "number" ? row.grad_class : null) !== filters.gradClass) {
    return false;
  }
  return true;
}
