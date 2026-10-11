// ============================================================
// 模块 B 职业洞察 — Tier 1 派生层（纯函数：无 LLM / 无网络 / 无 DB）
// 从自有 jobs 行直接算出事实级洞察：招聘节奏 timing / 招聘动态 hiring / 薪资带 compensation。
// 读时在 /api/insights 调用，产出 InsightItemView[]，与存储型洞察同形展示。
// 设计见 docs/superpowers/specs/2026-06-12-career-insights-overhaul-design.md §4。
// ============================================================
import { classifyJobFunction } from "./china-keyword-expansion";
import type { InsightDimension, InsightItemView, Job } from "./types";

export type RecruitBucket = "campus" | "intern" | "social" | "unknown";

// ============================================================
// 样本量阈值（v3 §1.5 硬规则）：样本不足即整字段/整卡不显示。
// 导出供展示层单测用，禁止内联数字（改一处就全改）。
// ============================================================
/** signal 类招聘动态（公司级分布类）最少样本 */
export const SIGNAL_MIN_COMPANY = 10;
/** signal 类招聘动态（业务线级）最少样本 */
export const SIGNAL_MIN_BU = 20;
/** signal 类趋势（两期各需满足）最少样本 */
export const SIGNAL_MIN_TREND = 10;
/** n < 此值禁止渲染百分比（防小样本百分比误导）*/
export const SIGNAL_NO_PCT_BELOW = 10;

// 内部用别名（保持代码可读）
const TIMING_MIN_SAMPLE = 5;
// 基础招聘卡（count + hiring_signal）门槛低，3 条岗即可出卡（计数是事实，不是分布）。
// 分布类统计（经验/学历分布）另有 DIST_MIN_SAMPLE 门（见 spec §1.5 「公司级分布类 n≥10」）。
const HIRING_MIN_SAMPLE = 3;
const SALARY_MIN_SAMPLE = 5;
// 经验/学历分布最少样本：至少 10 个岗有该字段才输出分布（spec §1.5 公司级分布类 n≥10）
const DIST_MIN_SAMPLE = SIGNAL_MIN_COMPANY;

// 经验要求归桶：覆盖常见中文表述 + 英文
export function bucketExperience(text: string | null): string | null {
  if (!text) return null;
  const t = text.toLowerCase().trim();
  if (!t) return null;
  if (/不限|不要求|无要求|no\s*requirement/.test(t)) return "不限";
  if (/应届|在校|应届毕业|fresh\s*grad|new\s*grad/.test(t)) return "应届";
  if (/3[-~至到]5|三[至到]五/.test(t)) return "3-5年";
  if (/1[-~至到]3|一[至到]三/.test(t)) return "1-3年";
  if (/5[-~至到]10|五[至到]十/.test(t)) return "5-10年";
  if (/10\s*年以上|10\+|十年以上|\b10\+\s*years?/.test(t)) return "10年+";
  // 「X年以上」
  const above = t.match(/(\d+)\s*年(?:以上|及以上|以上经验|years?\s*(?:above|or\s*more|above))?/);
  if (above) {
    const y = parseInt(above[1], 10);
    if (y === 0) return "不限";
    if (y <= 1) return "1-3年";
    if (y <= 3) return "1-3年";
    if (y <= 5) return "3-5年";
    if (y <= 10) return "5-10年";
    return "10年+";
  }
  // 「X-Y年」区间
  const rng = t.match(/(\d+)[-~至到](\d+)\s*年/);
  if (rng) {
    const lo = parseInt(rng[1], 10);
    if (lo < 1) return "不限";
    if (lo < 3) return "1-3年";
    if (lo < 5) return "3-5年";
    if (lo < 10) return "5-10年";
    return "10年+";
  }
  return null;
}

// 学历要求归桶：覆盖常见中文表述
export function bucketEducation(text: string | null): string | null {
  if (!text) return null;
  const t = text.toLowerCase().trim();
  if (!t) return null;
  if (/不限|不要求|无学历要求/.test(t)) return "不限";
  if (/博士|phd|doctorate/.test(t)) return "博士";
  if (/硕士|master|研究生/.test(t)) return "硕士";
  if (/本科|bachelor|学士/.test(t)) return "本科";
  if (/大专|专科|associate|college/.test(t)) return "大专";
  return null;
}

// intern 必须整词。与 china-keyword-expansion 的 sourceDeclaredCategory 是同一条正则（那边带 /i，这里先转了小写；
// hasInternSignal 另认 url 里的拼音 shixi，这里只看 job_type + 标题，用不上）。tests/insight-derive.test.js 钉着两处不漂。
// ⚠️ 下划线 / 数字算词字符："Intern_Compliance"、"Intern3D" 单看这一个词不认（全库 3 行，都另写了「实习」）。
// ❌ 原来是裸子串 /实习|intern|internship/：2026-10-11 全库 441,589 个在招岗里把 593 个（122 家公司）算成实习
//    —— 按词计 International 357、Internal 236、Internet 10（一个标题可同时含两个；"Senior Analyst - Internal Audit"）；
//    99 家公司抽屉里的「类型」占比因此不同，28 家的「实习」全是假的。反方向：写了整词 intern / 实习 却没判实习的 0 个；
//    这 593 个再按库里的招聘类型列 + 学生类字样（student / co-op / 培训生…）全量筛一遍，3 个算得上学生 / 实习岗
//    （强生 "Internal Communications Co-op"、西门子 "Strategic Student Program"、迪卡侬实习源的
//    "Internal Communications Specialist"）—— 旧规则是靠 Internal 碰巧算对的，现在落 unknown。
const INTERN_RE = /实习|\bintern(?:ship)?s?\b/;

// 关键词判法：只看 job_type + 标题，实习 → 校招/应届 → 社招；都不命中 = unknown（不臆测）。
// 只给 recruitBucket 当「列还没算出来」时的退路用，三桶的正主是岗位库那一列。
// 📌 纠错（2026-10-11）：此处原写「与 crawler/normalizer.py 三桶同口径」，不成立。normalizer 里没有三桶函数
//    （extract_job_type 判的是细分类型）；岗位库的三桶是 china-keyword-expansion 的 recruitmentCategory。
export function classifyRecruitment(jobType: string | null, title: string | null): RecruitBucket {
  const t = `${jobType || ""} ${title || ""}`.toLowerCase();
  if (INTERN_RE.test(t)) return "intern";
  if (/校招|校园招聘|应届|campus|graduate|new\s?grad/.test(t)) return "campus";
  if (/社招|社会招聘|experienced|professional/.test(t)) return "social";
  return "unknown";
}

// 抽屉里的招聘类型三桶：认岗位库物化的那一列（jobs.recruitment_category，七层判定，还看经验年限、url 渠道）。
//   · 列判校招 / 实习 → 照列；
//   · 列判社招且有依据（recruitment_explicit = true）→ 社招；
//   · 列判社招但只是兜底（没有任何标记、默认社招）→ unknown，不进占比的分母（2026-10-11 创始人选定）；
//   · 列为空（刚入库 / 依据变了等重算；或走 Supabase 兜底表，那张表没有这两列）→ 退回关键词判法。
//
// ❌ 此前占比与招聘节奏直接用关键词判法。2026-10-11 全库 441,123 个在招岗（在招 ≥3 的公司 1,450 家）对拍，
//    关键词判法 × 列：判不出而列判校招 23,606（大多靠校招门户 url，这里取不到 url）、列判实习 204、
//    列判有依据的社招 116,351；判校招而列判社招 2,221；判实习而列判社招 38（实习频道里挂的蓝领社招岗）。
//    后果：137 家没有「类型」这一行，470 家的百分比是按不到一半的在招岗算的，103 家只写「实习 100%」
//    （岚图 1,389 个在招岗里判得出 2 个，写的是「校招 50%·实习 50%」）。
//    改后「类型」行会变的 700 家（新出现 131 / 文字变 569 / 消失 0）：社招占比升 475 家降 50 家、
//    校招升 154 降 318、实习升 9 降 360；「招聘节奏」那句话变 546 家（新出现 203 / 文字变 343）。
// ⚠️ 比亚迪从「校招 100%」变成「社招 99%·校招 1%」：它有 1,587 个岗来源标校招、链接在社招门户、正文写
//    「应届硕士生 / 本科 2 年 / 大专 3 年以上相关工作经验」，列按经验门判了社招。这类岗算不算校招归分类器定，这里跟列走。
// ⚠️ 「有依据」是岗位库的定义（来源填了 job_type 就算，哪怕填的是职能），不等于「写明了招聘类型」：
//    同日快照里有依据的社招 254,367 个，其中 60,026 个是这种。兜底社招 73,943 个全部没有 job_type，集中在
//    外企 ATS（Target 4,105 个在招岗里 3,603 个是兜底）—— 这些公司的占比只在剩下的岗里算，实习 / 校招偏高。
//    改后仍有 6 家没有这一行、140 家按不到一半的在招岗算。
// ⚠️ 夜间物化的同名指标（crawler/bu_signals.py 的 bucket_share，洞察库用）读同一列，但兜底社招也算社招：
//    同一家公司两处的数字可以不同（同日 89 家差 10 个百分点以上、25 家占比最高的类别不同）。
//    要统一得两边一起定，别只改一边。
export function recruitBucket(
  jb: Pick<Job, "job_type" | "title" | "recruitment_category" | "recruitment_explicit">,
): RecruitBucket {
  if (jb.recruitment_category === "校招") return "campus";
  if (jb.recruitment_category === "实习") return "intern";
  if (jb.recruitment_category === "社招") return jb.recruitment_explicit === true ? "social" : "unknown";
  return classifyRecruitment(jb.job_type, jb.title);
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

// 构造派生展示态条目：grade=fact（兼容旧字段），assertion=signal（v3 语义）
// payload 里必须包含 sample_n（样本量）供展示层「基于 N 个在招岗」标注（v3 §1.5）。
function makeDerivedView(o: {
  dimension: InsightDimension;
  title: string;
  content: string;
  time_window: string;
  payload?: Record<string, unknown>;
  sample_size?: number | null;
  nowIso: string;
}): InsightItemView {
  const sn = o.sample_size ?? (o.payload?.active_count as number | undefined) ?? null;
  return {
    id: `derived-${o.dimension}`,
    company_id: "derived",
    dimension: o.dimension,
    grade: "fact",
    assertion: "signal",  // v3：派生条目属「自有岗位库观测量」，只给数字不下结论
    title: o.title,
    content: o.content,
    sample_size: sn,
    payload: { sample_n: sn, ...(o.payload ?? {}) },
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
    const b = recruitBucket(jb);
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

// 频次 Top-n（key→count），用于热门城市/方向。
// 并列按 key 的码点升序定序：取数没有 order by（行序 = 堆物理顺序，岗位一被改写就变），只按 count 排的话
// 并列的几个谁被截在前 n 之外随行序变，同一家公司刷新两次第三名会换人。
function topN(keys: string[], n: number): Array<{ key: string; count: number }> {
  const freq = new Map<string, number>();
  for (const k of keys) freq.set(k, (freq.get(k) || 0) + 1);
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
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

// 职能归类：用岗位库的分类器，只喂标题。这里不许再有自己的词表。
// 逐岗判法与夜间物化的同名指标相同（crawler/bu_signals.py 的 function_share → scripts/classify-job-function.js）；
// 聚合不同：那边把判不出的「其他」也算进分布，这里的热门方向不含「其他」—— 两处的排名 / 占比不必逐位相等。
//
// ❌ 此前是一张私有的 8 条正则表、按顺序取第一个命中（`\bai\b` 排最前、「工程师」算研发）。
//    2026-10-11 全库 441,589 个在招岗逐条对拍（改前 → 现在）：算法/AI → 产品 2,608（「AI产品经理」）、
//    研发 → 生产制造 21,395（机械 / 电气工程师）、研发 → 销售 1,209（销售工程师）、判不出方向 217,781 → 115,723；
//    在招 ≥3 的 1,445 家公司里 679 家的第一方向不同（比亚迪 研发 → 生产制造、汇丰 研发 → 金融业务）。
//    反方向也有：算法/AI → 判不出 2,668（"Machine Learning Researcher" 这类英文研究岗）、销售 → 判不出 1,152（商务专员）。
//    「算法/AI」不再是单独一桶，并进研发（岗位库的 17 个职能桶里没有它）。
// ❌ 按顺序取第一个命中还会被「岗位名 - 业务线」的尾巴带偏（「产品经理 - AI平台」算成算法）。爬虫 2026-10-11 起
//    入库保留完整标题（此前「 - 」后面整段截掉，当天实测库里这种标题还是 0 条，随列表重抓陆续出现）。
//    拿 live 抓到的 27,069 个带「 - 」的原始标题对拍（截断时代的判法 → 完整标题的判法）：旧规则改判 2,639 个；
//    分类器的「分段标题先看第一段」（_titleLeadSegment）下，原本判得出职能的只改判 9 个。
//    分段标题怎么判归分类器，这里不另写一份。
// ⚠️ 不读物化列 jobs.job_function：那一列带正文兜底（给卡片徽标 / 筛选用），做分布统计会把正文里的套话词算进来
//    —— 同日对拍两者有 39,479 岗不一致，几乎全是列靠正文多判出来的（其中「市场」12,692 岗），136 家公司的第一方向因此不同。
function titleFunction(title: string | null): string | null {
  if (!title) return null;
  return classifyJobFunction({ title });
}

// 🚫 这里**不能**用 first_seen_at 在当前 active 岗上算「近 30 天环比」（2026-09-08 删除，修 F4）。
//
// 原因是幸存者偏差，而且偏差方向恒为正：能被读到的只有**此刻仍 active** 的岗，
// 已关闭的岗每天被 purge-expired 物理删除 → 越早的窗口被删得越干净 → 分母单调缩水。
// 实测反例：两个窗口各真实发布 30 个岗（真实趋势 0%），只把旧窗关掉 27 个、一个新岗都没发，
// 算出来就是 **+900% 扩张**，还会进一步推出「HC 较充足」。用户看到的是一个凭空造出来的结论。
//
// 正确的趋势只能来自**跨日快照**（crawler/bu_signals.py 的 insight_subject_daily，
// 那边的模块注释专门写了「趋势为什么不在这里由 first_seen_at 直接算」）。
// 所以读时派生这条链一律不自产趋势：由 opts.trendPct 从快照派生结果注入，注入不了就是 null=未知。

// 公司规模档（wikidata headcount_band）→ 约数员工，用于「相对规模」招聘强度。启发式、抗小幅变动。
const HEADCOUNT_APPROX: Record<string, number> = {
  "1-100": 50, "100-500": 300, "500-1000": 750, "1000-5000": 3000,
  "5000-1万": 7500, "1万-5万": 30000, "5万-10万": 75000, "10万+": 150000,
};

export type HiringSignal = {
  // unknown = 没有可比基线。**不许**在这种情况下退化成 "steady"——「平稳」是一个有内容的结论，
  // 说它需要证据；没有证据时唯一诚实的输出是「不知道」（chip 侧会因此不渲染任何断言）。
  momentum: "expanding" | "steady" | "tightening" | "unknown";
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
  let momentum: HiringSignal["momentum"] = "unknown";
  if (typeof trend === "number") {
    if (trend >= 25) momentum = "expanding";
    else if (trend <= -25) momentum = "tightening";
    else momentum = "steady";
  }
  const emp = headcountBand ? HEADCOUNT_APPROX[headcountBand] : undefined;
  let intensity: HiringSignal["intensity"];
  if (emp && emp > 0 && activeCount > 0) {
    const ratio = activeCount / emp;
    intensity = ratio >= 0.015 ? "high" : ratio >= 0.004 ? "mid" : "low";
  }
  return { momentum, intensity, trend, active_count: activeCount };
}

const _MOM_CN: Record<HiringSignal["momentum"], string> = {
  expanding: "本平台收录的在招岗位数近月明显增加",
  steady: "本平台收录的在招岗位数近月基本持平",
  tightening: "本平台收录的在招岗位数近月减少",
  unknown: "近月变化暂无可比基线",
};
const _INT_CN = { high: "高", mid: "中", low: "低" };

// ⚠️ 措辞是刻意的，别改回去（2026-09-08，修 F4）：
//   ① 我们只观测得到**本平台收录到的岗位**，说「这家公司在扩张」超出了证据能支撑的范围
//      —— 源覆盖变动、抓取截断、旧岗退出都会让这个数字动，跟企业招聘预算不是一回事。
//   ② 删掉了原来的「（HC 较充足、进入窗口相对宽）/（HC 偏紧、竞争或更激烈）」：
//      从「岗位条数」推不出 HC 余量或竞争强度，中间缺了一整条因果链，属于无据外推。
function hiringSignalSentence(sig: HiringSignal): string {
  const intens = sig.intensity
    ? `，相对其公司规模档属${_INT_CN[sig.intensity]}密度`
    : "";
  return `招聘信号：${_MOM_CN[sig.momentum]}${intens}`;
}

// 招聘动态（hiring, fact）：在招规模 + 热门城市/方向 + 校社占比 + 新增趋势 + 大小年/HC 强度信号。
export function deriveHiring(
  jobs: Job[],
  nowIso: string,
  // sampleCapped：调用方只取了前 N 行做样本、且取满了 —— 真实在招数不止 active.length。
  opts: { headcountBand?: string | null; trendPct?: number | null; sampleCapped?: boolean } = {},
): InsightItemView | null {
  const active = jobs.filter((jb) => jb.status === "active");
  if (active.length < HIRING_MIN_SAMPLE) return null;

  const cities = topN(
    active.map((jb) => cityOf(jb.location)).filter((x): x is string => Boolean(x)),
    3,
  );
  const functions = topN(
    active
      .map((jb) => titleFunction(jb.title))
      .filter((x): x is string => Boolean(x) && x !== "其他"),
    3,
  );
  const mix = { campus: 0, intern: 0, social: 0, unknown: 0 };
  for (const jb of active) mix[recruitBucket(jb)]++;
  // 趋势只接受外部注入的快照派生值；本函数手里只有「当前 active」，算不出无偏趋势（见上方 F4 注释）。
  const trend = typeof opts.trendPct === "number" ? opts.trendPct : null;
  const signal = classifyHiringSignal(active.length, trend, opts.headcountBand);

  const cityStr = cities.length ? `主要在 ${cities.map((c) => c.key).join("、")}` : "";
  const fnStr = functions.length ? `热门方向 ${functions.map((f) => f.key).join("、")}` : "";
  const trendStr = trend !== null ? `近一月收录岗位环比 ${trend > 0 ? "+" : ""}${trend}%` : "";
  const tail = [cityStr, fnStr, trendStr].filter(Boolean).join("，");
  // 样本取满上限时写「N+」并说明下面是按样本算的：字节跳动在招 2 万多个，抽屉里却写着
  // 「当前收录 3000 个在招岗位」—— 那是取数上限，不是它的岗位数（2026-10-10 走查发现）。
  const countStr = opts.sampleCapped
    ? `${active.length}+ 个在招岗位（以下按其中 ${active.length} 个统计）`
    : `${active.length} 个在招岗位`;
  const content = `本平台当前收录 ${countStr}${tail ? "，" + tail : ""}。${hiringSignalSentence(signal)}。`;

  // 经验分布（≥DIST_MIN_SAMPLE 个岗有 experience 字段才输出）
  const expBuckets = active.map((jb) => bucketExperience(jb.experience)).filter(Boolean) as string[];
  const experience_dist: Record<string, number> | undefined =
    expBuckets.length >= DIST_MIN_SAMPLE
      ? Object.fromEntries(topN(expBuckets, 6).map(({ key, count }) => [key, count]))
      : undefined;

  // 学历分布（≥DIST_MIN_SAMPLE 个岗有 education 字段才输出）
  const eduBuckets = active.map((jb) => bucketEducation(jb.education)).filter(Boolean) as string[];
  const education_dist: Record<string, number> | undefined =
    eduBuckets.length >= DIST_MIN_SAMPLE
      ? Object.fromEntries(topN(eduBuckets, 5).map(({ key, count }) => [key, count]))
      : undefined;

  // 校招/实习/社招占比（仅含非 unknown 的桶，避免「unknown=40%」误导；unknown = 兜底社招，见 recruitBucket）
  const knownTotal = mix.campus + mix.intern + mix.social;
  const bucket_share: Record<string, number> | undefined =
    knownTotal > 0
      ? {
          campus: Math.round((mix.campus / knownTotal) * 100),
          intern: Math.round((mix.intern / knownTotal) * 100),
          social: Math.round((mix.social / knownTotal) * 100),
        }
      : undefined;

  // 在架时长中位数（active 岗 now−first_seen_at 天数；语义=这家公司的岗位平均在架多久）
  const nowMs = new Date(nowIso).getTime();
  const openAges = active
    .map((jb) => {
      if (!jb.first_seen_at) return null;
      const t = new Date(jb.first_seen_at).getTime();
      return Number.isNaN(t) ? null : Math.round((nowMs - t) / 86_400_000);
    })
    .filter((d): d is number => d !== null && d >= 0);
  // ≥5 样本才有代表性
  const open_age_days_median: number | undefined =
    openAges.length >= 5 ? median(openAges) : undefined;

  return makeDerivedView({
    dimension: "hiring",
    title: "招聘动态 · 据在招岗位",
    content,
    payload: {
      active_count: active.length, top_cities: cities, top_functions: functions, mix, trend,
      hiring_signal: signal,
      ...(experience_dist !== undefined && { experience_dist }),
      ...(education_dist !== undefined && { education_dist }),
      ...(bucket_share !== undefined && { bucket_share }),
      ...(open_age_days_median !== undefined && { open_age_days_median }),
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
  opts: { headcountBand?: string | null; sampleCapped?: boolean } = {},
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
