// 公司 → 资本来源 分类（用于按外企/美企/德企/日企/欧企筛选）。
import { isForeignAtsAdapter } from "./source-adapters";

const COMPANY_ORIGIN: Record<string, string> = {
  // 中国
  字节跳动: "中国", 腾讯: "中国", 阿里巴巴: "中国", 百度: "中国", 京东: "中国",
  美团: "中国", 华为: "中国", 小米: "中国", 蔚来: "中国", 小鹏汽车: "中国",
  地平线: "中国", 比亚迪: "中国", 宁德时代: "中国", 快手: "中国", 小红书: "中国",
  网易: "中国", 海尔: "中国", shlab: "中国", 招商银行: "中国", 中国移动: "中国",
  理想汽车: "中国", 商汤: "中国", 寒武纪: "中国",
  // 美企
  Apple: "美企", Microsoft: "美企", Amazon: "美企", Tesla: "美企", Google: "美企",
  Meta: "美企", "J&J": "美企", AbbVie: "美企", Merck: "美企", Anthropic: "美企",
  Reddit: "美企", Discord: "美企", Cloudflare: "美企", Figma: "美企",
  Twilio: "美企", Airtable: "美企", Nvidia: "美企", Intel: "美企",
  // 德企
  Siemens: "德企", Bosch: "德企", SAP: "德企", BMW: "德企", Mercedes: "德企",
  // 欧企（瑞士/法国等）
  Roche: "欧企", Novartis: "欧企", Nestle: "欧企", "L'Oreal": "欧企",
  // 日企
  Sony: "日企", Toyota: "日企", Honda: "日企", Panasonic: "日企", Nintendo: "日企",
};

export function classifyCompanyOrigin(company: string | null | undefined): string {
  if (!company) return "其它";
  if (COMPANY_ORIGIN[company]) return COMPANY_ORIGIN[company];
  const c = company.toLowerCase();
  for (const [k, v] of Object.entries(COMPANY_ORIGIN)) {
    const kl = k.toLowerCase();
    if (c.includes(kl) || kl.includes(c)) return v;
  }
  return "其它";
}

// 综合判定资本来源（治本「外企筛选漏放中国公司」）：
//  1. 公司名名单优先 —— 能判出具体国别（中国/美企/德企/日企/欧企）就信它，名单准且能细分。
//  2. 名单判不出（"其它"）时看来源：外企 ATS / 外企自建源 → "外企"（笼统，adapter 判不出具体国别）。
//  3. 其余一律默认 "中国" —— 库里岗位绝大多数为本土，「公司名没收录 + 不是外企源」的几乎都是
//     未收录的本土公司；默认中国，"外企" 筛选（踢掉 origin==="中国"）才能把它们挡住。
// 这样选「外企」不会再混入中国公司；代价是选「中国」时极少数「名单未收录 + 走非外企源」的小外企
// 可能混入（远比旧 bug 轻）。adapter 缺失（前端无源信息）时按规则 3 默认中国，与服务端口径一致。
export function classifyCompanyOriginWithSource(
  company: string | null | undefined,
  adapterName: string | null | undefined,
): string {
  const byName = classifyCompanyOrigin(company);
  if (byName !== "其它") return byName;
  if (isForeignAtsAdapter(adapterName)) return "外企";
  return "中国";
}
