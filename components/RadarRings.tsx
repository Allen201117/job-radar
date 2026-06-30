/**
 * 全站雷达波纹：复用原落地页 hero 的同心环效果（雷达绿，缓慢向外扩散），泛化到所有页面。
 * 固定在视口、落在页面内容背后（CSS .radar-rings 用 z-index:-1 + body 的 isolation 兜住），
 * pointer-events:none 不挡交互。挂在 app/layout.tsx 的 body 里，全站只此一处。
 * 纯展示、无状态，作为服务端组件渲染即可。
 */
export default function RadarRings() {
  return (
    <div className="radar-rings" aria-hidden="true">
      <span className="radar-ring" style={{ animationDelay: "0s" }} />
      <span className="radar-ring" style={{ animationDelay: "1.3s" }} />
      <span className="radar-ring" style={{ animationDelay: "2.6s" }} />
    </div>
  );
}
