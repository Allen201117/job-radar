/** SQL ILIKE 的轻量等价匹配器；快路径只处理双端 %X%，单端 % 仍走正则。 */
export function ilikeMatcher(pattern: string): (company: string) => boolean {
  const needle = pattern.replace(/^%|%$/g, "");
  if (pattern.startsWith("%") && pattern.endsWith("%") && !needle.includes("%") && !needle.includes("_")) {
    const normalized = needle.toLocaleLowerCase();
    return (company) => company.toLocaleLowerCase().includes(normalized);
  }
  const escaped = pattern
    .split("")
    .map((char) => (char === "%" ? ".*" : char === "_" ? "." : char.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("");
  const expression = new RegExp(`^${escaped}$`, "i");
  return (company) => expression.test(company);
}
