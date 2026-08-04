// 招聘板块（sources.board）的读侧纯函数。
//
// board 本身是 DB 派生列（迁移 187 的 generated column，由 adapter_name + source_url 算出），
// **权威在 SQL、这里不重复实现分类逻辑**——只提供「读到 board 之后怎么判」的共用谓词，
// 免得 app / 爬虫 / 看板各写一份 `=== "campus" || === "mixed"` 迟早写歪。
//
// ⚠️ board 只是静态分类。判「某公司有没有校招供给」时它不是唯一依据：
// live 实测有 149 个源 adapter 非 mixed、URL 也没有 campus 令牌，却在产大量校招岗
// （比亚迪 2053 / 小红书 585 / 华为 198 / 蚂蚁 109…自建门户把校校社混在一个列表里）。
// 所以选源要 board ∪ 实际产出（crawler/campus_lane.py），徽章要 campusJobCount 优先（lib/campus-zone.ts）。

/** 覆盖校招的板块值：campus=专职校招板块；mixed=adapter 一次抓全社招+校招+实习。 */
export const CAMPUS_BOARDS = ["campus", "mixed"] as const;

export type SourceBoard = "social" | "campus" | "intern" | "mixed";

/**
 * 该板块是否覆盖校招岗。
 * 未知值（含迁移前的 null / 将来新增的板块）一律 false —— 假阳性会让专区把没接校招的公司
 * 标成「已接入」，比漏报更伤（砸诚实徽章的立身之本）。
 */
export function boardCoversCampus(board: string | null | undefined): boolean {
  return (CAMPUS_BOARDS as readonly string[]).includes(board || "");
}
