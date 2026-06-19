import { cn } from "@/lib/utils";

/**
 * 雷达扫描标记（品牌 logo 符号）。环 / 中心点用 currentColor（随主题翻转），
 * 扫描扇形 + 命中点恒为雷达绿。用在品牌字标的方块里。
 */
export function RadarMark({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <circle cx="24" cy="24" r="16" stroke="currentColor" strokeWidth="3" opacity="0.42" />
      <path d="M24 24V8a16 16 0 0 1 13.9 8Z" fill="#00e676" opacity="0.9" />
      <circle cx="24" cy="24" r="3" fill="currentColor" />
      <circle cx="34" cy="16" r="2.6" fill="#00e676" />
    </svg>
  );
}

/**
 * 品牌字标：雷达方块 + 「职达 JobRadar」。
 * 方块在浅色 = 墨黑底 / 米白标，深色 = 米白底 / 墨黑标（两色 logo 自动适配）。
 */
export default function BrandMark({
  tile = 28,
  icon = 18,
  wordmark = true,
  wordSize = 15,
  className,
}: {
  tile?: number;
  icon?: number;
  wordmark?: boolean;
  wordSize?: number;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span
        className="grid shrink-0 place-items-center bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
        style={{ width: tile, height: tile, borderRadius: Math.round(tile * 0.32) }}
      >
        <RadarMark size={icon} />
      </span>
      {wordmark && (
        <span className="inline-flex items-baseline gap-1.5 leading-none">
          <span
            className="display-tight font-semibold text-[#1a1714] dark:text-[#f3ecdf]"
            style={{ fontSize: wordSize }}
          >
            职达
          </span>
          <span className="text-[10px] font-bold tracking-[0.2em] text-[#9a9184] dark:text-[#837c70]">
            JOBRADAR
          </span>
        </span>
      )}
    </span>
  );
}
