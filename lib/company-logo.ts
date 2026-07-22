// 企业 logo 的前端纯函数：归一 key + 首字母兜底（文本 + 确定性暖色）。
// CompanyLogo 组件在「抓不到真 favicon」时用它生成首字母色块；纯函数便于单测（tests/company-logo.test.js）。

export function logoKey(company: string): string {
  return (company || "").trim().toLowerCase();
}

// 暖色调色板：呼应项目 warm-editorial（低饱和暖色），每项 {bg, fg} 自带足够对比度。
const WARM_PALETTE: Array<{ bg: string; fg: string }> = [
  { bg: "#c9662f", fg: "#fff6ec" }, // 暖橙
  { bg: "#a2542b", fg: "#fceee0" }, // 赭棕
  { bg: "#5f7a3a", fg: "#f4f6e8" }, // 橄榄绿
  { bg: "#3f6f8c", fg: "#eef6fb" }, // 暖蓝
  { bg: "#8a4b52", fg: "#fbeef0" }, // 绛红
  { bg: "#6b5a8e", fg: "#f2eefb" }, // 暖紫
  { bg: "#a8823a", fg: "#fdf5e4" }, // 芥黄
];

// djb2 确定性 hash → 同名恒定同色。
function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h;
}

// 首字母：中文取首字、拉丁取首字母大写、空串给一个中性点。取第一个 code point（中文 / emoji 安全）。
export function monogramText(company: string): string {
  const s = (company || "").trim();
  if (!s) return "·";
  const first = Array.from(s)[0];
  return /[a-z]/i.test(first) ? first.toUpperCase() : first;
}

export function monogramColor(company: string): { bg: string; fg: string } {
  const key = logoKey(company);
  if (!key) return WARM_PALETTE[0];
  return WARM_PALETTE[hashString(key) % WARM_PALETTE.length];
}
