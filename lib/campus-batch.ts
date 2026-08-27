// 校招岗位批次展示纯函数：无网络、无 DB；空字段保持留白，不拿未验证的词扩展批次含义。
import { currentGradClass } from "./grad-class";

// 展示端的届别合理窗口（相对当季）。抽取端 lib/grad-class.js 的 MIN/MAX 是 2015-2100
// 「宽进」，那是对的——但展示端必须严：生产实测 active 岗位里有 2030(12 条) / 2037(1 条)
// 这类误提取（标题里的其它年份被当成届别），直接渲染出来就是错的。
// 往前 2 届容纳收尾岗，往后 3 届容纳提前批与低年级实习。
const SHOW_BEFORE = 2;
const SHOW_AFTER = 3;

/** 将已结构化的毕业届别转成卡面短标签；没有可靠值、或明显超出合理窗口就不展示。 */
export function gradClassLabel(
  gradClass: number | null | undefined,
  now: Date = new Date(),
): string | null {
  if (typeof gradClass !== "number" || !Number.isInteger(gradClass)) return null;
  const season = currentGradClass(now);
  if (gradClass < season - SHOW_BEFORE || gradClass > season + SHOW_AFTER) return null;
  return `${gradClass}届`;
}

/** 只认岗位标题中已经验证过的「提前批」字样。 */
export function isEarlyBatch(title: string | null | undefined): boolean {
  return typeof title === "string" && title.includes("提前批");
}
