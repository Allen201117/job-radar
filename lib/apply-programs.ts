// 项目制投递入口的读侧纯函数（无网络、无 DB）。
//
// 这一层承载的是**一类客观事实**：有些公司不存在「一岗一页」，
// 我们再怎么改抓取也拿不到 jd_url —— 中通校招是「蓝天计划」项目制投递
// （2026-09-04 浏览器实测：只有项目介绍 + 宣讲会 + 一个投递按钮，没有岗位列表），
// 国有大行是公告制。此前这类公司在产品里完全不存在，用户搜不到、也不知道为什么搜不到。
//
// ⚠️ 最重要的不变量：**这些条目不是岗位，UI 上必须让用户一眼看出来**。
// 把它们渲染成岗位卡片 = 用「看起来有岗」骗点击，比不展示更伤信任。
// 所以类型名、文案、徽章都刻意说人话，不留任何可以被误读成「岗位」的措辞。

export type ApplyProgramType = "campus_program" | "announcement" | "talent_pool";

export interface ApplyProgram {
  id?: string;
  company: string;
  programName: string;
  programType: ApplyProgramType;
  entryUrl: string;
  description?: string | null;
  windowText?: string | null;
  industry?: string | null;
  verifiedAt?: string | null;
}

/** 徽章文案：说清「这是什么」，不是岗位。 */
export const PROGRAM_TYPE_LABEL: Record<ApplyProgramType, string> = {
  campus_program: "项目制投递",
  announcement: "公告制招聘",
  talent_pool: "人才库",
};

/** 一句话解释「为什么这里没有岗位列表」——用户最需要知道的就是这个。 */
export const PROGRAM_TYPE_HINT: Record<ApplyProgramType, string> = {
  campus_program: "对方按项目收简历，不按岗位逐个挂出，投递后由对方分配方向",
  announcement: "对方按公告批量招聘，具体岗位写在公告里，官网没有逐个岗位的详情页",
  talent_pool: "对方常年收简历进人才库，有匹配机会再联系，没有固定岗位列表",
};

/** 徽章色：复用设计系统的语义 tone，不要在调用方写 hex。 */
export const PROGRAM_TYPE_TONE: Record<ApplyProgramType, "green" | "amber" | "neutral"> = {
  campus_program: "green", // 与校招同族
  announcement: "amber",
  talent_pool: "neutral",
};

function isProgramType(value: unknown): value is ApplyProgramType {
  return value === "campus_program" || value === "announcement" || value === "talent_pool";
}

/**
 * DB 行 → 展示模型。**只放行「已启用 + 已核实 + 入口 URL 是 http(s)」的行**。
 *
 * 为什么在读侧再挡一道（RLS 已经挡过一次）：这一层是给页面用的，
 * 而「未核实的链接被展示出去」的代价是用户点开一个死链——
 * 与其信任上游永远配置正确，不如在渲染前再判一次（fail-safe 更便宜）。
 */
export function toApplyProgram(row: Record<string, unknown> | null | undefined): ApplyProgram | null {
  if (!row) return null;
  const company = String(row.company ?? "").trim();
  const programName = String(row.program_name ?? row.programName ?? "").trim();
  const entryUrl = String(row.entry_url ?? row.entryUrl ?? "").trim();
  const programType = row.program_type ?? row.programType;
  const verifiedAt = row.verified_at ?? row.verifiedAt ?? null;
  const enabled = row.enabled ?? true;

  if (!company || !programName || !entryUrl) return null;
  if (!isProgramType(programType)) return null;
  if (!verifiedAt) return null;
  if (enabled === false) return null;
  if (!/^https?:\/\//i.test(entryUrl)) return null;

  return {
    id: row.id ? String(row.id) : undefined,
    company,
    programName,
    programType,
    entryUrl,
    description: (row.description as string) ?? null,
    windowText: (row.window_text ?? row.windowText ?? null) as string | null,
    industry: (row.industry as string) ?? null,
    verifiedAt: String(verifiedAt),
  };
}

/** 批量转换并丢掉不合格行（顺序保持）。 */
export function toApplyPrograms(rows: unknown): ApplyProgram[] {
  if (!Array.isArray(rows)) return [];
  return rows
    .map((row) => toApplyProgram(row as Record<string, unknown>))
    .filter((p): p is ApplyProgram => p !== null);
}

/** 按类型分组，供页面分区展示；组内保持传入顺序。 */
export function groupByType(programs: ApplyProgram[]): Array<{
  type: ApplyProgramType;
  label: string;
  hint: string;
  items: ApplyProgram[];
}> {
  const order: ApplyProgramType[] = ["campus_program", "announcement", "talent_pool"];
  return order
    .map((type) => ({
      type,
      label: PROGRAM_TYPE_LABEL[type],
      hint: PROGRAM_TYPE_HINT[type],
      items: programs.filter((p) => p.programType === type),
    }))
    .filter((group) => group.items.length > 0);
}
