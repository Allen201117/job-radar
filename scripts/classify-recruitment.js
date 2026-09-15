#!/usr/bin/env node
/**
 * 岗位分类桥（招聘类型 + 职能）：stdin 收 JSON 数组，stdout 回 JSON 数组，一一对应。
 *
 * 存在的理由：判「社招/校招/实习」与「产品/研发/设计…」的权威实现各只有一份，都在 JS
 * （lib/china-keyword-expansion.js 的七层裁决 / classifyJobFunction + 完整单测）。爬虫是 Python，
 * 但**不翻译规则**——翻译=制造第二份会漂移的实现（本仓库在 canonicalize_jd_url 上吃过这个亏）。
 * 让 Python 隔着一个进程同时拿两个结论，规则始终只有一处、且省一次进程启动。
 *
 * 输入每项只需 7 个字段（两个分类器的全部输入并集）：
 *   { title, summary, jd_url, apply_url, job_type, company, experience }
 * 输出每项：{ category: "社招"|"校招"|"实习", explicit: boolean, function: 职能桶名 }
 *
 * ⚠️ 职能**带 summary 算**（classifyJobFunction 会对歧义标题看正文精修）：这与
 *    scripts/classify-job-function.js（**只喂 title**、服务于 insight 职能分布统计、宁可多判「其他」）
 *    是两种口径。物化到 jobs.job_function 用的是**这里带 summary 的口径**，与校招看板读路径一致。
 *
 * 性能：实测 0.011ms/行，一批 500 条约 6ms —— 进程启动才是主要开销，所以调用方应**按批**调，
 * 不要逐条调。
 */
"use strict";

const path = require("path");
const {
  recruitmentCategory,
  hasExplicitRecruitmentType,
  classifyJobFunction,
} = require(path.join(__dirname, "..", "lib", "china-keyword-expansion.js"));

let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (buf += c));
process.stdin.on("end", () => {
  try {
    const rows = JSON.parse(buf || "[]");
    if (!Array.isArray(rows)) throw new Error("stdin 必须是 JSON 数组");
    const out = rows.map((r) => ({
      category: recruitmentCategory(r || {}),
      explicit: hasExplicitRecruitmentType(r || {}),
      function: classifyJobFunction(r || {}),
    }));
    process.stdout.write(JSON.stringify(out));
  } catch (e) {
    process.stderr.write(String((e && e.message) || e));
    process.exit(1);
  }
});
