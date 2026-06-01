// 公司 → 资本来源 分类（用于按外企/美企/德企/日企/欧企筛选）。
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
