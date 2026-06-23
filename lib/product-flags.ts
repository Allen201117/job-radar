// 产品特性开关（§9.3）。手动爬取 UI（刷新对口公司 / 发掘新公司）默认隐藏——后台能力保留，
// 仅在故障回滚时把 NEXT_PUBLIC_MANUAL_CRAWL_UI=true 在 /jobs 的「高级工具」折叠区恢复。
// Landing / Today / 主导航永不引用该能力。
export const MANUAL_CRAWL_UI_ENABLED = process.env.NEXT_PUBLIC_MANUAL_CRAWL_UI === "true";
