#!/usr/bin/env node
/**
 * 回填 jobs.search_bigrams（迁移 140 的中文 bigram 全文检索列）存量行。
 * 循环调 backfill_search_bigrams(batch) RPC（行级锁 + skip locked，不挡读），直到返回 0。
 * 用法：set -a; source .env.local; set +a; node scripts/backfill-search-bigrams.js
 * 只写 search_bigrams 列（由 SQL 函数按现有字段计算），不改业务字段；可随时中断后重跑（幂等：只填 NULL 的）。
 */
const { createClient } = require("@supabase/supabase-js");
const SUPA_URL = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!SUPA_URL || !KEY) {
  console.error("✗ 缺少 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY（先 set -a; source .env.local; set +a）");
  process.exit(1);
}
const BATCH = Number(process.argv[2] || 2000);

(async () => {
  const sb = createClient(SUPA_URL, KEY, { auth: { persistSession: false } });
  let total = 0;
  let round = 0;
  let fails = 0;
  for (;;) {
    const t = Date.now();
    const { data, error } = await sb.rpc("backfill_search_bigrams", { batch: BATCH });
    if (error) {
      fails += 1;
      console.error(`! 第 ${round + 1} 批失败(${fails}/5): ${error.message} — 重试`);
      if (fails >= 5) {
        console.error("✗ 连续失败过多，停止。可降低 batch 后重跑（幂等，只填 NULL）。");
        process.exit(1);
      }
      continue; // 同批重试（未提交→仍是 NULL，幂等）
    }
    fails = 0;
    const n = Number(data || 0);
    total += n;
    round += 1;
    if (round % 10 === 0 || n === 0) {
      console.log(`round ${round}: +${n}（累计 ${total}）${Date.now() - t}ms`);
    }
    if (n === 0) break;
  }
  console.log(`✓ 回填完成，共 ${total} 行。`);
})().catch((e) => {
  console.error("回填异常:", e.message);
  process.exit(1);
});
