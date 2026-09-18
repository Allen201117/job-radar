/**
 * 推荐页 0 岗时「说真话」用的纯函数（2026-09-18 立）。
 *
 * 为什么要有它：空队列原先只说一句「今天暂时没有新的对口机会 / 系统持续在监控你关注的官方招聘源」。
 * 对真实用户是**误导**——2026-09-18 走查里那个 0 岗用户的画像是「深圳 · 校招 · 仓库文员/办公室文员」，
 * 库里确实有 4 个对口岗（拓竹「仓库储干」「仓库账务员」、广和通「仓库经理」、创维「仓库账务员（光伏方向）」），
 * 但三个条件叠起来就是空。那句文案让他读成「今天没有新岗、明天再来」，于是他明天、后天还是空——
 * 这正是「静默丢失用户」的具体形态：页面说了话，但说的不是真原因。
 *
 * 这里只负责**决定放宽哪一维 + 造出放宽后的画像**；真实数字由调用方拿同一条召回链路重算一次拿到
 * （见 app/today/page.tsx）。刻意不在这里查库：数字必须和用户下一步真能看到的东西同口径，
 * 自己另写一条 count SQL 就会出现「提示说有 12 个、点进去只有 3 个」——那比不给数字更伤。
 */
import type { RadarProfile } from "./types";

/**
 * 可放宽的维度。顺序即优先级，**刻意不按「哪个放出来的岗多」排**：
 * 2026-09-18 拿那个真实 0 岗用户实测，放宽城市得 7 个、放宽求职阶段得 11 个——但他是校招生，
 * 放宽阶段等于让他去看社招岗（要工作经验），数字更大却基本投不了。换城市则是他自己能决定的事。
 */
export type WidenDim = "city" | "stage";

export interface WideningPlan {
  dim: WidenDim;
  /** 当前值的可读描述，用于「放宽 <from> 之后…」的文案。 */
  from: string;
}

export interface EmptyWidening extends WideningPlan {
  /** 放宽这一维之后真实召回到的机会数（由调用方用同一条链路重算得到）。 */
  count: number;
}

/**
 * 这个画像有哪些维度**值得**试着放宽。
 *
 * 只列真正收窄了结果的维度：没填城市就没有「放宽城市」可言，阶段为空（不限）同理。
 * 刻意**不放宽方向词**：方向是用户最明确的诉求，把「仓库文员」放宽成「全部岗位」等于
 * 把推荐变成大杂烩，违反产品第一原则（精准 > 规模）。方向召回过窄是召回层的结构问题
 * （「仓库文员」被拆成 `仓库 AND 文员`），要在那里修，不能靠空态绕过去。
 */
export function planWidenings(profile: RadarProfile): WideningPlan[] {
  const plans: WideningPlan[] = [];
  const cities = profile.targetLocations.filter((c) => String(c || "").trim());
  if (cities.length > 0) {
    plans.push({ dim: "city", from: cities.join("、") });
  }
  if (profile.experienceStage) {
    plans.push({ dim: "stage", from: profile.experienceStage });
  }
  return plans;
}

/** 造出放宽某一维后的画像；其余字段逐字不动（放宽一次只动一维，否则说不清是哪一维带来的增量）。 */
export function widenProfile(profile: RadarProfile, dim: WidenDim): RadarProfile {
  if (dim === "city") return { ...profile, targetLocations: [] };
  return { ...profile, experienceStage: "" };
}

/**
 * 用户当前的筛选条件摘要，给空态照原样念回去。
 *
 * 为什么要念回去：0 岗的真实原因几乎总是「几个条件叠起来太窄」，而用户看不见自己叠了什么
 * （城市在偏好页、阶段在另一处、方向词是简历解析出来的）。把三样摆在一起，他自己就知道该松哪一个。
 */
export function summarizeCriteria(profile: RadarProfile): string[] {
  const out: string[] = [];
  const cities = profile.targetLocations.filter((c) => String(c || "").trim());
  if (cities.length) out.push(cities.join("、"));
  if (profile.experienceStage) out.push(profile.experienceStage);
  const roles = profile.targetRoles.filter((r) => String(r || "").trim());
  if (roles.length) out.push(roles.join("、"));
  else {
    const keywords = profile.targetKeywords.filter((k) => String(k || "").trim());
    if (keywords.length) out.push(keywords.join("、"));
  }
  return out;
}

/** 放宽维度的中文名，UI 与文案共用一处，避免两边各写各的。 */
export const WIDEN_DIM_LABEL: Record<WidenDim, string> = {
  city: "城市",
  stage: "求职阶段",
};
