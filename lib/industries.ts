// 行业分类 — 职业洞察按行业扩展覆盖（任务 4.3）。
// admin 录入表单的 datalist 建议 + 覆盖视图共用；存储为自由文本（datalist 仅建议，可填自定义）。

export const INDUSTRIES = [
  "互联网/科技",
  "金融",
  "消费/零售",
  "制造/工业",
  "汽车/出行",
  "医疗/医药",
  "能源/化工",
  "地产/建筑",
  "物流/供应链",
  "传媒/文娱",
  "教育",
  "央国企",
  "其他",
] as const;

export type Industry = (typeof INDUSTRIES)[number];

// 归一化录入的行业值：去空白、截断；空串视为未填（null）。允许自定义行业（datalist 仅建议）。
export function normalizeIndustry(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, 40) : null;
}
