const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

function workflow(name) {
  return fs.readFileSync(path.join(__dirname, "..", ".github", "workflows", name), "utf8");
}

function matrixAdapters(text) {
  const match = text.match(/adapter:\s*\[([^\]]+)\]/m);
  assert.ok(match, "adapter matrix not found");
  return new Set(
    match[1]
      .split(",")
      .map((adapter) => adapter.trim())
      .filter(Boolean),
  );
}

function maxParallel(text) {
  const match = text.match(/max-parallel:\s*(\d+)/m);
  return match ? Number(match[1]) : null;
}

test("enrich-backlog drains supported overseas httpx detail adapters", () => {
  const adapters = matrixAdapters(workflow("enrich-backlog.yml"));

  for (const adapter of [
    "workday",
    "oracle",
    "eightfold",
    "smartrecruiters",
    "greenhouse",
    "lever",
    "amazon",
    "microsoft",
  ]) {
    assert.equal(adapters.has(adapter), true, adapter);
  }

  // siemens/google：2026-07-14 live 核实两者详情页都是 SSR，httpx 直接拿得到 <main> 正文
  // （Siemens 7.6k 字符 / Google 5-6k）。此前 siemens 不在任何富化流 → 338 个在招岗 100% 无正文薄卡；
  // google 被 best-effort 归为 SPA 走无头审计 → 91 岗同样无正文。两者现走 httpx 富化。
  assert.equal(adapters.has("siemens"), true);
  assert.equal(adapters.has("google"), true);
  // phenom 仍排除：jd_url 落到 SPA 壳（careers.amd.com/pepsicojobs.com），httpx 拿不到正文。
  assert.equal(adapters.has("phenom"), false);
});

test("enrich-backlog caps adapter fan-out after overseas matrix expansion", () => {
  assert.equal(maxParallel(workflow("enrich-backlog.yml")), 3); // 2026-09-03 与 liveness-sweep 错峰后降到 3（峰值 27 连接）
});

test("liveness-sweep covers overseas httpx closure-capable adapters", () => {
  const adapters = matrixAdapters(workflow("liveness-sweep.yml"));

  for (const adapter of [
    "workday",
    "oracle",
    "eightfold",
    "smartrecruiters",
    "greenhouse",
    "lever",
    "amazon",
    "microsoft",
  ]) {
    assert.equal(adapters.has(adapter), true, adapter);
  }

  // siemens/google：2026-07-14 live 核实两者详情页都是 SSR，httpx 直接拿得到 <main> 正文
  // （Siemens 7.6k 字符 / Google 5-6k）。此前 siemens 不在任何富化流 → 338 个在招岗 100% 无正文薄卡；
  // google 被 best-effort 归为 SPA 走无头审计 → 91 岗同样无正文。两者现走 httpx 富化。
  assert.equal(adapters.has("siemens"), true);
  assert.equal(adapters.has("google"), true);
  // phenom 仍排除：jd_url 落到 SPA 壳（careers.amd.com/pepsicojobs.com），httpx 拿不到正文。
  assert.equal(adapters.has("phenom"), false);
});

test("dead-link-audit main rotation reserves capacity for must-apply companies", () => {
  const text = workflow("dead-link-audit.yml");

  assert.match(text, /--must-apply-first/);
});

// 只断言结构性事实（job 存在 + 用了 --must-apply-only + 有并发上限），
// 不锁死 cron 时间/分片数/limit 具体值——那些是运维可调参数，调参不该报红。
test("dead-link-audit has lightweight must-apply-only schedule", () => {
  const text = workflow("dead-link-audit.yml");

  assert.match(text, /must_apply_audit:/);
  assert.match(text, /--must-apply-only/);
  assert.match(text, /max-parallel:\s*\d+/);
});

// 2026-09-19 自动修复：@supabase/supabase-js 在 Node 20 上启动即抛
// `Node.js 20 detected without native WebSocket support.`。台账写入是 fail-open 的
// （只打日志、不拖垮主任务），所以症状是「workflow 全绿 + 一行台账都没有」——
// 体检据此报「这条链没在跑」，实际在跑，只是没留痕。ux-walkthrough 09-18 已按 Node 22 修过，
// 同日 bd34eb4d 给两条 backfill 加台账时又落回 Node 20，无人察觉。
test("装了 @supabase/supabase-js 的 workflow 必须跑 node>=22（否则台账静默丢失）", () => {
  const dir = path.join(__dirname, "..", ".github", "workflows");
  const offenders = [];
  let checked = 0;

  for (const name of fs.readdirSync(dir).filter((f) => f.endsWith(".yml") || f.endsWith(".yaml"))) {
    const text = fs.readFileSync(path.join(dir, name), "utf8");
    if (!text.includes("@supabase/supabase-js")) continue;
    checked += 1;
    const versions = [...text.matchAll(/node-version:\s*"?(\d+)/g)].map((m) => Number(m[1]));
    assert.ok(versions.length > 0, `${name} 装了 supabase-js 却没有显式 node-version`);
    if (versions.some((v) => v < 22)) offenders.push(`${name}(node ${versions.join("/")})`);
  }

  assert.ok(checked > 0, "没有扫到任何装 supabase-js 的 workflow，断言失效了");
  assert.deepEqual(offenders, [], `这些 workflow 会静默丢台账：${offenders.join(", ")}`);
});
