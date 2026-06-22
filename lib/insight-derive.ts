// ============================================================
// 模块 B 职业洞察 — Tier 1 派生层（纯函数：无 LLM / 无网络 / 无 DB）
// 从自有 jobs 行直接算出事实级洞察：招聘节奏 timing / 招聘动态 hiring / 薪资带 compensation。
// 读时在 /api/insights 调用，产出 InsightItemView[]，与存储型洞察同形展示。
// 设计见 docs/superpowers/specs/2026-06-12-career-insights-overhaul-design.md §4。
// ============================================================
import type { InsightDimension, InsightItemView, Job } from "./types";

export type RecruitBucket = "campus" | "intern" | "social" | "unknown";

// 阈值：样本太少不出洞察（宁缺毋滥，避免拿 2 个岗位编节奏）
const TIMING_MIN_SAMPLE = 5;
const HIRING_MIN_SAMPLE = 3;
const SALARY_MIN_SAMPLE = 5;

// 与 crawler/normalizer.py 三桶同口径：实习 → 校招/应届 → 社招；都不命中 = unknown（不臆测）
export function classifyRecruitment(jobType: string | null, title: string | null): RecruitBucket {
  const t = `${jobType || ""} ${title || ""}`.toLowerCase();
  if (/实习|intern|internship/.test(t)) return "intern";
  if (/校招|校园招聘|应届|campus|graduate|new\s?grad/.test(t)) return "campus";
  if (/社招|社会招聘|experienced|professional/.test(t)) return "social";
  return "unknown";
}

// 解析岗位薪资文本为「月薪 K」区间。仅解析明示区间（k/千 或 4–6 位元）；
// 「万」存在年/月歧义 → 保守返回 null（不进垃圾）。无法解析返回 null。
export function parseSalaryText(raw: string | null): { minK: number; maxK: number } | null {
  if (!raw) return null;
  const s = raw.replace(/\s/g, "").toLowerCase();
  // 形如 15-30k / 15k-30k / 20-40千（单位可出现在首数字后或尾数字后）
  let m = s.match(/(\d+(?:\.\d+)?)(?:k|千)?[-~至到](\d+(?:\.\d+)?)(?:k|千)/);
  if (m) {
    const lo = parseFloat(m[1]);
    const hi = parseFloat(m[2]);
    if (lo > 0 && hi >= lo && hi < 1000) return { minK: Math.round(lo), maxK: Math.round(hi) };
    return null;
  }
  // 形如 15000-30000（元/月）→ /1000 取 K
  m = s.match(/(\d{4,6})[-~至到](\d{4,6})/);
  if (m) {
    const lo = parseInt(m[1], 10) / 1000;
    const hi = parseInt(m[2], 10) / 1000;
    if (lo > 0 && hi >= lo && hi < 1000) return { minK: Math.round(lo), maxK: Math.round(hi) };
    return null;
  }
  return null;
}

// ---- 内部工具（不导出，由派生函数复用） ----

function monthOf(iso: string | null): number | null {
  if (!iso) return null;
  const m = new Date(iso).getUTCMonth() + 1;
  return Number.isNaN(m) ? null : m;
}

function yyyymm(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function median(nums: number[]): number {
  if (nums.length === 0) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
}

// 构造派生展示态条目：固定 grade=fact、deidentified=true、status=active、derived=true、无溯源链接
function makeDerivedView(o: {
  dimension: InsightDimension;
  title: string;
  content: string;
  time_window: string;
  payload?: Record<string, unknown>;
  sample_size?: number | null;
  nowIso: string;
}): InsightItemView {
  return {
    id: `derived-${o.dimension}`,
    company_id: "derived",
    dimension: o.dimension,
    grade: "fact",
    title: o.title,
    content: o.content,
    sample_size: o.sample_size ?? null,
    payload: o.payload ?? {},
    time_window: o.time_window,
    valid_from: null,
    valid_until: null,
    last_verified_at: o.nowIso,
    deidentified: true,
    status: "active",
    created_at: o.nowIso,
    updated_at: o.nowIso,
    sources: [],
    outdated: false,
    derived: true,
  };
}

// 薪资带（compensation_intensity, fact）：聚合 active 岗位中「明示薪资」的月薪带中位区间。
export function deriveSalaryBand(jobs: Job[], nowIso: string): InsightItemView | null {
  const bands = jobs
    .filter((jb) => jb.status === "active")
    .map((jb) => parseSalaryText(jb.salary_text))
    .filter((b): b is { minK: number; maxK: number } => Boolean(b));
  if (bands.length < SALARY_MIN_SAMPLE) return null;
  const lo = median(bands.map((b) => b.minK));
  const hi = median(bands.map((b) => b.maxK));
  const content = `公开在招岗位中明示薪资的约 ${bands.length} 个，月薪带集中在约 ${lo}–${hi}K（中位区间，仅供参考）。`;
  return makeDerivedView({
    dimension: "compensation_intensity",
    title: "薪资带 · 据在招岗位",
    content,
    payload: { min_k: lo, max_k: hi, sample: bands.length },
    time_window: `截至 ${yyyymm(nowIso)}`,
    sample_size: bands.length,
    nowIso,
  });
}

// 出现频次最高的 1–2 个月（升序返回），用于「校招集中在 X、Y 月」
function peakMonths(months: number[]): number[] {
  const freq = new Map<number, number>();
  for (const m of months) freq.set(m, (freq.get(m) || 0) + 1);
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .slice(0, 2)
    .map((e) => e[0])
    .sort((a, b) => a - b);
}

// 招聘节奏（timing, fact）：按三桶聚合发布月份（posted_at 缺则用 first_seen_at 代理）。
export function deriveTiming(jobs: Job[], nowIso: string): InsightItemView | null {
  const dated = jobs.filter((jb) => jb.posted_at || jb.first_seen_at);
  if (dated.length < TIMING_MIN_SAMPLE) return null;

  const byBucket: Record<"campus" | "intern" | "social", number[]> = {
    campus: [], intern: [], social: [],
  };
  for (const jb of dated) {
    const b = classifyRecruitment(jb.job_type, jb.title);
    if (b === "unknown") continue;
    const mo = monthOf(jb.posted_at || jb.first_seen_at);
    if (mo) byBucket[b].push(mo);
  }

  const LABEL: Record<"campus" | "intern" | "social", string> = {
    campus: "校招", intern: "实习", social: "社招",
  };
  const parts: string[] = [];
  (["campus", "intern", "social"] as const).forEach((b) => {
    const months = byBucket[b];
    if (months.length < 3) return; // 单桶样本不足不下结论
    if (b === "social" && new Set(months).size >= 6) {
      parts.push("社招全年滚动");
      return;
    }
    parts.push(`${LABEL[b]}集中在 ${peakMonths(months).join("、")} 月`);
  });
  if (parts.length === 0) return null;

  const content = `据本平台 ${dated.length} 个在招岗位的发布时间聚合：${parts.join("；")}。`;
  return makeDerivedView({
    dimension: "timing",
    title: "招聘节奏 · 据在招岗位",
    content,
    time_window: `截至 ${yyyymm(nowIso)}`,
    nowIso,
  });
}

// 频次 Top-n（key→count），用于热门城市/方向
function topN(keys: string[], n: number): Array<{ key: string; count: number }> {
  const freq = new Map<string, number>();
  for (const k of keys) freq.set(k, (freq.get(k) || 0) + 1);
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => ({ key, count }));
}

// 取城市主名：按常见分隔切第一段，去「市/地区」后缀
function cityOf(location: string | null): string | null {
  if (!location) return null;
  const first = location.split(/[·、,，/\s-]+/).filter(Boolean)[0] || "";
  const city = first.replace(/(市|地区)$/, "").trim();
  return city || null;
}

// 粗粒度职能归类（算法在「研发」之前判，避免「算法工程师」落到研发）
const FUNCTION_RULES: Array<[RegExp, string]> = [
  [/算法|machine\s?learning|\bml\b|\bai\b|nlp|\bcv\b|数据科学|data\s?scien/i, "算法/AI"],
  [/前端|后端|全栈|开发|工程师|研发|software|engineer|backend|frontend|测试|\bqa\b|运维|\bsre\b|devops/i, "研发"],
  [/产品经理|产品|product\s?manager|\bpm\b/i, "产品"],
  [/设计|design|\bux\b|\bui\b|交互/i, "设计"],
  [/运营|operation/i, "运营"],
  [/市场|marketing|品牌|公关|增长|growth/i, "市场"],
  [/销售|sales|商务|\bbd\b/i, "销售"],
  [/人力|\bhr\b|招聘|财务|法务|行政|finance|legal/i, "职能"],
];
function coarseFunction(title: string | null): string | null {
  if (!title) return null;
  for (const [re, label] of FUNCTION_RULES) if (re.test(title)) return label;
  return "其他";
}

// 近 30 天新增岗位环比（first_seen_at）；前一窗口样本 <3 不报趋势（null）
function trendPct(jobs: Job[], nowIso: string): number | null {
  const now = new Date(nowIso).getTime();
  const D30 = 30 * 86_400_000;
  let recent = 0;
  let prior = 0;
  for (const jb of jobs) {
    if (!jb.first_seen_at) continue;
    const t = new Date(jb.first_seen_at).getTime();
    if (Number.isNaN(t)) continue;
    if (t >= now - D30) recent++;
    else if (t >= now - 2 * D30) prior++;
  }
  if (prior < 3) return null;
  return Math.round(((recent - prior) / prior) * 100);
}

// 公司规模档（wikidata headcount_band）→ 约数员工，用于「相对规模」招聘强度。启发式、抗小幅变动。
const HEADCOUNT_APPROX: Record<string, number> = {
  "1-100": 50, "100-500": 300, "500-1000": 750, "1000-5000": 3000,
  "5000-1万": 7500, "1万-5万": 30000, "5万-10万": 75000, "10万+": 150000,
};

export type HiringSignal = {
  momentum: "expanding" | "steady" | "tightening";
  intensity?: "high" | "mid" | "low";
  trend: number | null;
  active_count: number;
};

// 招聘「大小年 / HC 强度」信号：趋势(扩张/平稳/收紧) + 相对公司规模的强度(需 headcountBand)。
// 诚实边界：这是「当前窗口」信号(自有发岗数据现算)，非年度周期对比——真年度大小年需累积 ≥1 年历史 + 官方员工数同比(业绩维度)。
export function classifyHiringSignal(
  activeCount: number,
  trend: number | null,
  headcountBand?: string | null,
): HiringSignal {
  let momentum: HiringSignal["momentum"] = "steady";
  if (typeof trend === "number") {
    if (trend >= 25) momentum = "expanding";
    else if (trend <= -25) momentum = "tightening";
  }
  const emp = headcountBand ? HEADCOUNT_APPROX[headcountBand] : undefined;
  let intensity: HiringSignal["intensity"];
  if (emp && emp > 0 && activeCount > 0) {
    const ratio = activeCount / emp;
    intensity = ratio >= 0.015 ? "high" : ratio >= 0.004 ? "mid" : "low";
  }
  return { momentum, intensity, trend, active_count: activeCount };
}

const _MOM_CN = { expanding: "近月招聘明显扩张", steady: "近月招聘平稳", tightening: "近月招聘收紧" };
const _INT_CN = { high: "高", mid: "中", low: "低" };

function hiringSignalSentence(sig: HiringSignal): string {
  const intens = sig.intensity ? `，相对其规模属${_INT_CN[sig.intensity]}强度招聘` : "";
  const read =
    sig.momentum === "expanding" && (sig.intensity === "high" || sig.intensity === "mid")
      ? "（HC 较充足、进入窗口相对宽）"
      : sig.momentum === "tightening"
        ? "（HC 偏紧、竞争或更激烈）"
        : "";
  return `招聘信号：${_MOM_CN[sig.momentum]}${intens}${read}`;
}

// 招聘动态（hiring, fact）：在招规模 + 热门城市/方向 + 校社占比 + 新增趋势 + 大小年/HC 强度信号。
export function deriveHiring(
  jobs: Job[],
  nowIso: string,
  opts: { headcountBand?: string | null } = {},
): InsightItemView | null {
  const active = jobs.filter((jb) => jb.status === "active");
  if (active.length < HIRING_MIN_SAMPLE) return null;

  const cities = topN(
    active.map((jb) => cityOf(jb.location)).filter((x): x is string => Boolean(x)),
    3,
  );
  const functions = topN(
    active
      .map((jb) => coarseFunction(jb.title))
      .filter((x): x is string => Boolean(x) && x !== "其他"),
    3,
  );
  const mix = { campus: 0, intern: 0, social: 0, unknown: 0 };
  for (const jb of active) mix[classifyRecruitment(jb.job_type, jb.title)]++;
  const trend = trendPct(active, nowIso);
  const signal = classifyHiringSignal(active.length, trend, opts.headcountBand);

  const cityStr = cities.length ? `主要在 ${cities.map((c) => c.key).join("、")}` : "";
  const fnStr = functions.length ? `热门方向 ${functions.map((f) => f.key).join("、")}` : "";
  const trendStr = trend !== null ? `近一月新增岗位环比 ${trend > 0 ? "+" : ""}${trend}%` : "";
  const tail = [cityStr, fnStr, trendStr].filter(Boolean).join("，");
  const content = `当前在招约 ${active.length} 个岗位${tail ? "，" + tail : ""}。${hiringSignalSentence(signal)}。`;

  return makeDerivedView({
    dimension: "hiring",
    title: "招聘动态 · 据在招岗位",
    content,
    payload: {
      active_count: active.length, top_cities: cities, top_functions: functions, mix, trend,
      hiring_signal: signal,
    },
    time_window: `截至 ${yyyymm(nowIso)}`,
    nowIso,
  });
}

// 聚合入口：从某公司的 jobs 行算出所有可派生维度（算不出的维度不出现在结果里）。
// 返回形如 { timing?: [view], hiring?: [view], compensation_intensity?: [view] }。
export function deriveCompanyInsights(
  jobs: Job[],
  now: Date = new Date(),
  opts: { headcountBand?: string | null } = {},
): Partial<Record<InsightDimension, InsightItemView[]>> {
  const nowIso = now.toISOString();
  const out: Partial<Record<InsightDimension, InsightItemView[]>> = {};
  const timing = deriveTiming(jobs, nowIso);
  if (timing) out.timing = [timing];
  const hiring = deriveHiring(jobs, nowIso, opts);
  if (hiring) out.hiring = [hiring];
  const salary = deriveSalaryBand(jobs, nowIso);
  if (salary) out.compensation_intensity = [salary];
  return out;
}
