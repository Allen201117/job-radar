import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// 展示用：解 HTML 实体 + 去标签 + 合并空白。
// 部分历史岗位 summary 是实体编码的 HTML（greenhouse content：&lt;p&gt;…），不处理会显示乱码。
// 对已是纯文本的 summary 幂等无害。解两遍兜底双重编码（&amp;lt; → &lt; → <）。
export function cleanSummary(input?: string | null): string {
  if (!input) return "";
  let s = String(input);
  for (let i = 0; i < 2; i += 1) {
    s = s
      .replace(/&quot;/g, '"')
      .replace(/&#0?39;/g, "'")
      .replace(/&apos;/g, "'")
      .replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">");
  }
  return s
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// 岗位新鲜度：用 jobs.last_seen_at（每次爬取命中刷新）算「最近一次确认在招」距今多久。
// 这是产品对「真实可投」承诺的信任信号——超过 14 天没再被抓到，岗位很可能已下线。
// 纯函数，便于单测；null / 非法时间返回空 label（不展示）。
export function freshnessLabel(lastSeenAt: string | null): { label: string; stale: boolean } {
  if (!lastSeenAt) return { label: "", stale: false };
  const seen = new Date(lastSeenAt).getTime();
  if (Number.isNaN(seen)) return { label: "", stale: false };
  const days = Math.floor((Date.now() - seen) / 86_400_000);
  if (days <= 0) return { label: "今天确认在招", stale: false };
  if (days <= 14) return { label: `${days} 天前确认在招`, stale: false };
  return { label: "14+ 天未确认，可能已下线", stale: true };
}
