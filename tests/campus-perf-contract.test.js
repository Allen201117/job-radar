// /campus 首屏性能契约（2026-09-23 线上实测 8.8~10.1s 的两处根因，别退回去）。
// ① 「全部 active 公司名」不许再用 `select distinct company`（规划器已退化成全表扫，3.1s），
//    必须走松散索引扫描，且要有跨实例缓存（进程内 Map 在 serverless 多实例下命中率≈0）。
// ② 校招卡面的「计数 + 新鲜度」要有独立短缓存，不能每请求冷盘聚合（3.6s）。
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");

test("active 公司名走松散索引扫描 + 跨实例缓存", () => {
  const src = read("lib/jobs-store/read.ts");
  assert.doesNotMatch(src, /select distinct company from jobs where status = 'active'/);
  assert.match(src, /with recursive t as \(/);
  assert.match(src, /select \(select min\(company\) from jobs where status = 'active' and company > t\.c\)/);
  assert.match(src, /\["active-company-names-v1"\]/);
});

test("校招卡面计数走独立 60s 缓存，Map 以 entries 形式进缓存", () => {
  const src = read("lib/jobs-store/read.ts");
  assert.match(src, /\["campus-fresh-stats-v1"\],\s*\{ revalidate: 60/);
  assert.match(src, /entries: Array\.from\(byPattern\.entries\(\)\)/);
  assert.match(src, /byPattern: new Map\(entries\)/);
});
