#!/usr/bin/env node
// 生成 lib/fts-token-df.json：香港 jobs 库里 active 岗 search_doc 的高频 token（文档频率 ndoc ≥ 阈值）。
//
// 用途：/jobs 登录 match 的候选收窄条件（lib/jobs-store/search.ts prescoreOrderBy）要判「哪个扩展词太泛」——
// 一个词的全部 token 都在这张表里 = 泛词，不进收窄条件（仍参与排序键）。
// 阈值取 active 文档数的 ~1.4%（2026-09-18 实测 6,800 / 493,067）：再低会把「会计」「后端」这类真方向词也判成泛词，
// 再高则「工程师」「产品」漏网、规划器对收窄条件放弃 GIN（创始人账号 236 子句 → Parallel Seq Scan 5.8s）。
//
// 运行（本地或 CI，需要 JOBS_DATABASE_URL；绝不把连接串打印/提交）：
//   set -a; source .env.local; set +a; node scripts/fts-token-df/gen.mjs
// ts_stat 全表扫 active 行约 7s；频率随库漂移很慢，改词表/大规模扩源后重跑一次即可。
import psqlLib from "../lib/psql.js";
import { writeFileSync } from "node:fs";
import path from "node:path";

if (!process.env.JOBS_DATABASE_URL) { console.error("JOBS_DATABASE_URL missing"); process.exit(1); }
const RATIO = Number(process.env.FTS_GENERIC_RATIO || 0.0138);
// 连接串经环境变量传给 psql、不进命令行（见 scripts/lib/psql.js 顶部注释）。
const psql = (q) => psqlLib.runPsql(["-tAc", q], { maxBuffer: 1e8 }).trim();
const activeDocs = Number(psql("select count(*) from jobs where status='active'"));
const minNdoc = Math.round(activeDocs * RATIO);
const rows = psql(
  `set statement_timeout='600s'; select word||E'\\t'||ndoc from ts_stat('select search_doc from jobs where status=''active''') where ndoc >= ${minNdoc} order by ndoc desc, word`,
).split("\n").filter((l) => l.includes("\t")); // 过滤 `SET` 这类 psql 回显行
const tokens = {};
for (const line of rows) { const [w, n] = line.split("\t"); if (Number.isFinite(Number(n))) tokens[w] = Number(n); }
const out = { generatedAt: new Date().toISOString().slice(0, 10), activeDocs, ratio: RATIO, minNdoc, tokens };
const target = path.join(process.cwd(), "lib", "fts-token-df.json");
writeFileSync(target, JSON.stringify(out, null, 0) + "\n");
console.log(`activeDocs=${activeDocs} minNdoc=${minNdoc} tokens=${rows.length} -> ${path.relative(process.cwd(), target)}`);
