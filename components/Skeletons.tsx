// 轻量骨架占位：tab 切换 / 冷启动时由各路由 loading.tsx 即时渲染，
// 把「空白冻屏等服务端跑完」换成「秒出同构骨架 + 数据流入」。纯展示、无状态，
// 暖纸风（warm-paper），占位尺寸对齐真实组件以避免数据到达时的布局跳动。
import { cn } from "@/lib/utils";

// 单条占位骨条
function Bar({ className }: { className?: string }) {
  return <div className={cn("rounded-md bg-black/[0.06]", className)} aria-hidden="true" />;
}

// 单张岗位卡骨架（对齐 JobCard 的 .surface 卡片：公司 / 标题 / 标签 / 操作）
export function JobCardSkeleton() {
  return (
    <div className="surface p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-3">
          <Bar className="h-3 w-24" />
          <Bar className="h-5 w-2/3" />
          <div className="flex flex-wrap gap-2 pt-1">
            <Bar className="h-6 w-20 rounded-full" />
            <Bar className="h-6 w-16 rounded-full" />
            <Bar className="h-6 w-24 rounded-full" />
          </div>
          <Bar className="h-3 w-full max-w-md" />
        </div>
        <Bar className="h-9 w-24 shrink-0 rounded-full" />
      </div>
    </div>
  );
}

// 岗位列表骨架
export function JobListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="animate-pulse space-y-3" role="status" aria-label="加载中">
      <span className="sr-only">正在加载岗位…</span>
      {Array.from({ length: count }).map((_, i) => (
        <JobCardSkeleton key={i} />
      ))}
    </div>
  );
}

// 指标卡片网格骨架（对齐 ProductChrome.MetricTile 的移动横排 / 桌面竖排）
export function MetricTilesSkeleton({
  count = 5,
  gridClassName = "grid grid-cols-2 gap-3 lg:grid-cols-5",
}: {
  count?: number;
  gridClassName?: string;
}) {
  return (
    <div className={cn("animate-pulse", gridClassName)} aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="surface-soft flex items-center gap-3 px-3.5 py-3 sm:flex-col sm:items-start sm:gap-0 sm:px-4 sm:py-4"
        >
          <Bar className="size-9 shrink-0 rounded-xl" />
          <div className="min-w-0 space-y-2 sm:mt-5">
            <Bar className="h-6 w-12" />
            <Bar className="h-3 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

// Hero 右侧统计 / 徽标位的骨架（如岗位库总数卡、计数徽标）
export function HeroStatSkeleton({ className }: { className?: string }) {
  return (
    <Bar
      className={cn("h-[72px] w-full animate-pulse rounded-2xl sm:w-[340px] lg:w-[360px]", className)}
    />
  );
}

// 通用面板骨架（用于个人主页 / 偏好等含表单、卡片块的页面）
export function PanelSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("surface animate-pulse space-y-4 p-6", className)} aria-hidden="true">
      <Bar className="h-5 w-40" />
      <Bar className="h-3 w-full max-w-lg" />
      <Bar className="h-3 w-3/4 max-w-md" />
      <div className="grid gap-3 sm:grid-cols-2">
        <Bar className="h-10 w-full rounded-xl" />
        <Bar className="h-10 w-full rounded-xl" />
      </div>
      <Bar className="h-10 w-32 rounded-full" />
    </div>
  );
}
