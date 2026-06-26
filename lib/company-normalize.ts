// 公司名归一（§10.2）：仅用于「目标公司 ↔ 已有 source.company」的 exact 覆盖对比；不做模糊编辑距离自动合并。
// 原始 display name 由调用方保留。归一规则：NFKC → trim → lowercase → 移除所有空白 → 剥常见公司尾缀。
// ⚠️ 按 spec，「中国/China」也作尾缀剥除（如「字节跳动中国」→「字节跳动」）；边角如「中国银行」会被剥成「银行」，
//    属已知取舍——归一值只用于对比、两端口径一致即可，宁可漏判 covered 也不误并不同公司。

// 长的尾缀必须排在前面，确保「股份有限公司」整体剥除而非先剥「有限公司」留下残尾。
const SUFFIXES = ["股份有限公司", "有限公司", "集团", "控股", "中国", "china"];

export function normalizeCompany(raw: unknown): string {
  if (typeof raw !== "string") return "";
  let s = raw.normalize("NFKC").trim().toLowerCase().replace(/\s+/g, "");
  let changed = true;
  while (changed) {
    changed = false;
    for (const suf of SUFFIXES) {
      if (s.length > suf.length && s.endsWith(suf)) {
        s = s.slice(0, -suf.length);
        changed = true;
      }
    }
  }
  return s;
}
