#!/usr/bin/env node
/**
 * 岗位职能分类桥：stdin 收 JSON 数组，stdout 回 JSON 数组，一一对应。
 *
 * 存在的理由与 scripts/classify-recruitment.js 完全相同：判「研发/产品/销售…」的权威实现
 * 只有一份，在 lib/china-keyword-expansion.js 的 classifyJobFunction（两级词表 + 完整单测）。
 * 派生层是 Python，但**不翻译规则**——翻译=制造第二份会漂移的实现。
 *
 * ⚠️ 只喂 title：classifyJobFunction 的标题层是权威层，summary 兜底在本仓库实测约有 290 个
 * 误判（见 CLAUDE.md「岗位类型体系」段）。派生层做的是分布统计，宁可多判「其他」也不要错判方向。
 *
 * 输入每项：{ title }
 * 输出每项：职能桶名（字符串，如「研发」「产品」「其他」）
 *
 * 性能：进程启动是主要开销 → 调用方必须**按批**调（建议 2000 条/批），不要逐条调。
 */
"use strict";

const path = require("path");
const { classifyJobFunction } = require(
  path.join(__dirname, "..", "lib", "china-keyword-expansion.js"),
);

let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (buf += c));
process.stdin.on("end", () => {
  try {
    const rows = JSON.parse(buf || "[]");
    if (!Array.isArray(rows)) throw new Error("stdin 必须是 JSON 数组");
    process.stdout.write(
      JSON.stringify(rows.map((r) => classifyJobFunction({ title: (r && r.title) || "" }))),
    );
  } catch (e) {
    process.stderr.write(String((e && e.message) || e));
    process.exit(1);
  }
});
