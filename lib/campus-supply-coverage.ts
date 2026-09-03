// 必投清单公司的「校招供给覆盖」度量 —— 纯函数，无网络无 DB。
//
// 为什么要有它：创始人要求「必投三十家必须全部打通，形成稳定的岗位和洞察爬取链路」。
// 但此前**全站没有任何地方能回答「打通了几家」** —— 看板的「校招供给」卡只报任务跑没跑、
// 今天有多少家岗位数变了，不报覆盖。没有度量就谈不上「稳定」，也没法发现某家哪天断了。
//
// 核心口径：**区分「我们的锅」和「对方没开」**。把对方还没开放校招的公司算成我们的缺口，
// 会让指标失真、也会误导排期；反过来把自己漏抓的板块推给对方，就是自欺。
// 这条区分贯穿本产品（同 §指标诚实），这里把它变成可计算的字段 `blame`。

export type CampusSupplyState =
  | "healthy" // 校招供给相对社招体量正常
  | "thin" // 有岗但相对社招过少 —— 几乎必然是漏了校招板块
  | "no_supply"; // 一个校招/实习岗都没有

/** 缺口归属：ours = 我们能修的（没接通道 / 漏板块）；theirs = 对方还没开放；null = 不是缺口。 */
export type CampusSupplyBlame = "ours" | "theirs" | null;

export interface CampusSupplyInput {
  company?: string;
  campusJobs?: number;
  internJobs?: number;
  socialJobs?: number;
  hasCampusSource?: boolean;
  hasAnySource?: boolean;
}

export interface CampusSupplyResult {
  company: string | null;
  state: CampusSupplyState;
  blame: CampusSupplyBlame;
  campusTotal: number;
  socialJobs: number;
  /** (校招+实习) / 社招，百分比；社招为 0 时为 null。 */
  ratioPct: number | null;
}

/**
 * 比例下限：低于它且社招基数够大 → 判「漏板块」。
 *
 * 5% 不是拍脑袋，是真实库分布里的断层（2026-09-03，必投互联网 30 家）：
 *   ≤3.0%：vivo 0 / 快手 0.1 / 京东 0.1 / 中兴 0.4 / B站 0.4 / 小米 0.6 / 阿里 0.9 / SHEIN 3.0
 *   ≥6.9%：科大讯飞 6.9 / 腾讯 9.3 / 得物 11.2 / 大疆 13.9 / 携程 25.2 / 百度 33.2 / 美团 35.4 …
 * 3.0 与 6.9 之间没有任何一家，而低端那 8 家**全部**已被独立证实漏了校招板块
 * （例：`crawler/adapters/jd.py` 里白纸黑字写着「校招/实习在 campus.jd.com 独立门户，本 adapter 只抓社招」）。
 */
const THIN_RATIO_PCT = 5;

/**
 * 启用比例判据所需的最小社招基数。
 * 深信服 30:23、金山办公 26:33 的比例都 >100%，但基数只有二三十 —— 小样本比例没有判别力，
 * 拿它判「漏没漏板块」只会制造噪音。基数不够就只看「有没有岗」。
 */
const MIN_SOCIAL_BASE = 100;

function n(v: unknown): number {
  const x = Number(v);
  return Number.isFinite(x) && x > 0 ? x : 0;
}

export function classifyCampusSupply(input: CampusSupplyInput = {}): CampusSupplyResult {
  const campusTotal = n(input.campusJobs) + n(input.internJobs);
  const socialJobs = n(input.socialJobs);
  const ratioPct = socialJobs > 0 ? Math.round((campusTotal / socialJobs) * 1000) / 10 : null;
  const company = input.company ?? null;

  if (campusTotal === 0) {
    // 零供给分两种，处置完全不同：
    //  · 校招通道都没接 → 我们的锅，去接
    //  · 通道接好了、还在跑，对方就是没放岗 → 对方的节奏，不该算进我们的缺口
    const blame: CampusSupplyBlame = input.hasCampusSource ? "theirs" : "ours";
    return { company, state: "no_supply", blame, campusTotal, socialJobs, ratioPct };
  }

  if (socialJobs >= MIN_SOCIAL_BASE && ratioPct !== null && ratioPct < THIN_RATIO_PCT) {
    // 有几千个社招岗却只有个位数校招岗 —— 对方不可能这么招人，一定是我们漏了板块。
    return { company, state: "thin", blame: "ours", campusTotal, socialJobs, ratioPct };
  }

  return { company, state: "healthy", blame: null, campusTotal, socialJobs, ratioPct };
}

export interface CampusSupplySummary {
  total: number;
  healthy: number;
  thin: number;
  noSupply: number;
  /** 我们能修的缺口家数（没接通道 / 漏板块）。 */
  ourGap: number;
  /** 对方还没开放的家数 —— 单独计，不进我们的缺口。 */
  theirGap: number;
  /**
   * 打通率：healthy / (总数 − 对方没开的)。
   * **分母剔掉「对方没开」的**：那不是我们能修的，算进去只会让指标看着更差却指导不了任何行动。
   * 没有可达样本时返回 null，不编造百分比。
   */
  reachablePct: number | null;
  ourGapCompanies: string[];
  rows: CampusSupplyResult[];
}

export function summarizeCampusSupply(inputs: CampusSupplyInput[] | null | undefined): CampusSupplySummary {
  const rows = (inputs || []).map((i) => classifyCampusSupply(i));
  const healthy = rows.filter((r) => r.state === "healthy").length;
  const thin = rows.filter((r) => r.state === "thin").length;
  const noSupply = rows.filter((r) => r.state === "no_supply").length;
  const ourGapRows = rows.filter((r) => r.blame === "ours");
  const theirGap = rows.filter((r) => r.blame === "theirs").length;
  const reachable = rows.length - theirGap;
  return {
    total: rows.length,
    healthy,
    thin,
    noSupply,
    ourGap: ourGapRows.length,
    theirGap,
    reachablePct: reachable > 0 ? Math.round((healthy / reachable) * 100) : null,
    ourGapCompanies: ourGapRows.map((r) => r.company).filter((c): c is string => !!c),
    rows,
  };
}
