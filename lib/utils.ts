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
