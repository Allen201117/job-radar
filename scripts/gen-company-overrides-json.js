#!/usr/bin/env node
// 从 lib/company-industry.js 的 COMPANY_OVERRIDES（唯一数据源）生成 lib/data/company-industry-overrides.json，
// 供爬虫 Python(crawler/company_industry.py) 读取，避免 JS/Python 两份公司表漂移。
// 用法：改完 COMPANY_OVERRIDES 后跑 `node scripts/gen-company-overrides-json.js`。
// tests/company-industry-overrides-sync.test.js 会守卫「JSON 与模块一致」，忘记重生成则 CI 红。
const fs = require("fs");
const path = require("path");
const { COMPANY_OVERRIDES } = require("../lib/company-industry.js");

const out = path.join(__dirname, "..", "lib", "data", "company-industry-overrides.json");
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(COMPANY_OVERRIDES) + "\n");
console.log(`[gen-company-overrides] 写出 ${COMPANY_OVERRIDES.length} 条 → ${path.relative(path.join(__dirname, ".."), out)}`);
