#!/usr/bin/env node
/**
 * 只读：抽样 active 岗位的 jd_url，按 host 探活，统计 404/410（死链）占比。
 * 不写任何表，不打印密钥。用法：set -a; source .env.local; set +a; node scripts/probe-dead-links.js
 */
const { createClient } = require("@supabase/supabase-js");
const SUPA_URL = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!SUPA_URL || !KEY) { console.error("NO_ENV"); process.exit(1); }

const PER_HOST = 6;       // 每个 host 最多探这么多
const CONCURRENCY = 30;
const TIMEOUT_MS = 7000;

const hostOf = (u) => { try { return new URL(u).host; } catch { return null; } };

async function probe(url) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    // 多数招聘站不支持 HEAD，用 GET 但只读状态码
    const r = await fetch(url, { method: "GET", redirect: "follow", signal: ctrl.signal,
      headers: { "User-Agent": "Mozilla/5.0 (compatible; JobRadarLinkCheck/1.0)" } });
    return r.status;
  } catch (e) {
    return e.name === "AbortError" ? "timeout" : "neterr";
  } finally { clearTimeout(t); }
}

(async () => {
  const sb = createClient(SUPA_URL, KEY, { auth: { persistSession: false } });
  // 跨全库分散抽样（覆盖老岗+新岗，非只看最近）：在 0..N 等距取若干 1000 条窗口，按 host 分桶。
  const head = await sb.from("jobs").select("id", { count: "exact", head: true }).eq("status", "active");
  const N = head.count || 0;
  const OFFSETS = [0, 0.2, 0.4, 0.6, 0.8, 0.95].map((f) => Math.floor(f * Math.max(0, N - 1000)));
  const data = [];
  const seen = new Set();
  for (const off of OFFSETS) {
    if (seen.has(off)) continue;
    seen.add(off);
    const { data: page, error } = await sb.from("jobs").select("jd_url,company,first_seen_at")
      .eq("status", "active").order("first_seen_at", { ascending: false }).range(off, off + 999);
    if (error) { console.error("query fail:", error.message); process.exit(1); }
    if (page && page.length) data.push(...page);
  }
  console.log(`全库 ${N} 活跃岗，跨 ${seen.size} 个分散窗口取 ${data.length} 条做分桶探活。`);

  const byHost = new Map();
  for (const j of data || []) {
    const h = hostOf(j.jd_url);
    if (!h) continue;
    if (!byHost.has(h)) byHost.set(h, []);
    const arr = byHost.get(h);
    if (arr.length < PER_HOST) arr.push(j);
  }
  const sample = [];
  for (const [h, arr] of byHost) for (const j of arr) sample.push({ host: h, ...j });
  console.log(`抽样 ${sample.length} 条（覆盖 ${byHost.size} 个 host），探活中…\n`);

  const results = [];
  for (let i = 0; i < sample.length; i += CONCURRENCY) {
    const batch = sample.slice(i, i + CONCURRENCY);
    const codes = await Promise.all(batch.map((s) => probe(s.jd_url)));
    batch.forEach((s, k) => results.push({ ...s, code: codes[k] }));
    process.stderr.write(`\r  ${Math.min(i + CONCURRENCY, sample.length)}/${sample.length}`);
  }
  process.stderr.write("\n\n");

  // 按 host 汇总
  const agg = new Map();
  for (const r of results) {
    if (!agg.has(r.host)) agg.set(r.host, { total: 0, dead: 0, ok: 0, other: 0, codes: {} });
    const a = agg.get(r.host);
    a.total++;
    a.codes[r.code] = (a.codes[r.code] || 0) + 1;
    if (r.code === 404 || r.code === 410) a.dead++;
    else if (r.code === 200) a.ok++;
    else a.other++;
  }
  let totalDead = 0, total = 0;
  const rows = [...agg.entries()].map(([h, a]) => { totalDead += a.dead; total += a.total; return { h, ...a }; })
    .sort((x, y) => (y.dead / y.total) - (x.dead / x.total) || y.total - x.total);

  console.log("================ 死链探活（按 host）================");
  console.log(`总抽样 ${total}，其中 404/410 死链 ${totalDead} (${((totalDead/total)*100).toFixed(1)}%)\n`);
  console.log("host 维度（死链率降序）：");
  for (const r of rows) {
    const codeStr = Object.entries(r.codes).map(([c, n]) => `${c}:${n}`).join(" ");
    const flag = r.dead > 0 ? " ⚠" : "";
    console.log(`  ${r.h}  → ${r.total}抽样 死链${r.dead} ok${r.ok} 其他${r.other}  [${codeStr}]${flag}`);
  }
})().catch((e) => { console.error("probe fail:", e.message); process.exit(1); });
