// 路由切换过场（全产品统一）：仿 iOS 点开 App 的缩放开场。
//
// template.tsx 与 layout.tsx 的关键区别：layout 在导航间持久保留，template 则会在
// 每次导航时被 Next 重建实例。正是这个「重新挂载」让下面的 .route-zoom 节点每次导航
// 都重新创建 → globals.css 里的 route-zoom-in 缩放动画随之重播。
//
// 纯 CSS 动画（见 globals.css 的 .route-zoom），无需引入 framer-motion 等重型依赖；
// prefers-reduced-motion 下自动关闭。RadarRings / MagicBentoFX 挂在 layout（在本包裹层
// 之外），因此过场时固定背景不动、只有内容缩放展开，更贴近「App 从背景里打开」的观感。
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="route-zoom">{children}</div>;
}
