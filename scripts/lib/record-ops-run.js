"use strict";
/**
 * JS 侧的 ops_runs 台账写入（Python 侧对应 crawler/ops_runs.record_ops_run）。
 *
 * 台账是旁路观测：写入失败只打日志，绝不能让调用方的主任务因此失败——与 Python 侧
 * `record_ops_run` 同一语义（见 crawler/ops_runs.py 顶部注释）。
 *
 * 用法：
 *   const { recordOpsRun } = require("./lib/record-ops-run.js");
 *   await recordOpsRun("backfill_job_function", { scanned, changed, written }, "success");
 *
 * 没有 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 时直接跳过（本地手跑没配这两个 env 很常见），
 * 不当成错误、也不重试。
 */

function statusFromCounts(processed, failed) {
  const total = Math.max(0, Number(processed) || 0);
  const failures = Math.max(0, Number(failed) || 0);
  if (total > 0 && failures >= total) return "failed";
  if (failures > 0) return "partial";
  return "success";
}

// ⚠️ run_date 必须按 Asia/Shanghai 取日，不能用 toISOString().slice(0,10)（那是 UTC 日期）。
// crawler/ops_runs.py 的 Python 侧就是按上海时区取的（_as_iso 里 `.astimezone(SHANGHAI).date()`）——
// 两侧写同一张按 run_date 分桶的表，取日口径必须一致，否则 UTC 16:00~23:59（上海次日 0~7:59）
// 这 8 小时里 JS 写的行会落进「前一天」的桶，backfill 两条 workflow 恰好各有一档卡在
// UTC 19:30/19:45，正中这个漂移窗口（2026-09-18 review 抓到）。
function shanghaiDateString(d) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(d);
}

async function recordOpsRun(module, metrics, status = "success", opts = {}) {
  const { startedAt, finishedAt, createClient: createClientOverride } = opts;
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    console.error(`[ops-runs] ${module} 跳过台账写入（SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置）`);
    return false;
  }
  const finished = finishedAt || new Date();
  const started = startedAt || finished;
  try {
    // 延迟 require：调用方多为一次性脚本，没配 Supabase env 时不必强装这个包。
    // 测试用 opts.createClient 注入假客户端，不打真网络。
    const createClient = createClientOverride || require("@supabase/supabase-js").createClient;
    const client = createClient(url, key, { auth: { persistSession: false } });
    const { error } = await client.from("ops_runs").insert({
      module: String(module),
      run_date: shanghaiDateString(finished),
      metrics: metrics || {},
      status: ["success", "partial", "failed"].includes(status) ? status : "failed",
      started_at: started.toISOString(),
      finished_at: finished.toISOString(),
    });
    if (error) {
      console.error(`[ops-runs] ${module} 台账写入失败（主任务不受影响）: ${error.message}`);
      return false;
    }
    return true;
  } catch (e) {
    console.error(`[ops-runs] ${module} 台账写入失败（主任务不受影响）: ${e.message}`);
    return false;
  }
}

module.exports = { recordOpsRun, statusFromCounts, shanghaiDateString };
