// 学历层级判定（纯函数，无依赖）——学历筛选「准确遵循」的核心，独立成 .js 以便 node --test 完整覆盖。
//
// 岗位 education 字段是高度混杂的原始文本（实测 active 库里几十种变体：本科 / 本科及以上 / 大学本科 /
// 硕士研究生及以上 / 大专(含高职) / 统招本科及以上 / 中专 / 不限 / 其他 …，且约 43% 为空），
// 故按「学历层级」容错解析、而非精确字符串相等匹配。

// 文本 → 学历档位（数值越大门槛越高）；解析不出返回 null。
// 判断顺序必须高→低：「博士研究生」含「研究生」但应判博士档，故博士先于硕士；「大学本科」含「本科」判本科档。
function educationRank(text) {
  if (!text) return null;
  const t = String(text).replace(/\s/g, "");
  if (/博士|ph\.?d|doctorofphilosophy|doctora/i.test(t)) return 6;
  if (/硕士|研究生|master'?s?|m\.?s\.?|m\.?eng|m\.?sc/i.test(t)) return 5;
  if (/本科|学士|bachelor'?s?|b\.?s\.?|b\.?a\.?|b\.?sc|undergrad/i.test(t)) return 4;
  if (/大专|专科|高职|associate('?s)?degree/i.test(t)) return 3;
  if (/高中|中专|中技|技校|职高/.test(t)) return 2;
  if (/初中|小学/.test(t)) return 1;
  if (/不限/.test(t)) return 0;
  return null; // 「其他」/「其它」/纯数字等无学历语义 → 无法判断
}

// 给定岗位学历要求文本 + 用户所选学历，返回判定（门槛/资格语义，用户拍板）：
//   "pass"    —— 用户够格（岗位要求 ≤ 所选 或 不限）→ 精确放行
//   "degrade" —— 岗位要求缺失 / 解析不出 → 信息缺失不一刀切，降级放行（排到精确匹配之后）
//   "reject"  —— 岗位要求高于用户学历 → 够不着，淘汰
// wantLabel 为空（「学历不限」）→ 不筛，恒 "pass"。
function educationMatch(jobEducation, wantLabel) {
  if (!wantLabel) return "pass";
  const want = educationRank(wantLabel);
  const text = (jobEducation || "").trim();
  if (!text) return "degrade";
  const r = educationRank(text);
  if (r === null) return "degrade";
  if (want !== null && r > want) return "reject";
  return "pass";
}

module.exports = { educationRank, educationMatch };
