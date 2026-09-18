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

async function recordOpsRun(module, metrics, status = "success", { startedAt, finishedAt } = {}) {
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
    const { createClient } = require("@supabase/supabase-js");
    const client = createClient(url, key, { auth: { persistSession: false } });
    const { error } = await client.from("ops_runs").insert({
      module: String(module),
      run_date: finished.toISOString().slice(0, 10),
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

module.exports = { recordOpsRun, statusFromCounts };
