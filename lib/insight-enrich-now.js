const HOUR_MS = 60 * 60 * 1000;
const IN_FLIGHT_STATUSES = new Set(["queued", "running"]);

function normalizeInsightCompany(company) {
  return String(company || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function runCompany(run) {
  return (
    run?.diagnostics?.company ||
    run?.company ||
    run?.query ||
    ""
  );
}

function runTime(run) {
  const ms = Date.parse(run?.created_at || run?.started_at || "");
  return Number.isFinite(ms) ? ms : null;
}

function retryAfterSec(untilMs, nowMs) {
  return Math.max(1, Math.ceil((untilMs - nowMs) / 1000));
}

function evaluateInsightEnrichDispatch(recentRuns = [], company, nowMs = Date.now(), opts = {}) {
  const normalized = normalizeInsightCompany(company);
  if (!normalized) return { action: "skip", reason: "missing_company" };

  const cooldownHours = Number.isFinite(Number(opts.cooldownHours))
    ? Math.max(0, Number(opts.cooldownHours))
    : 6;
  const hourlyCap = Number.isFinite(Number(opts.hourlyCap))
    ? Math.max(0, Math.floor(Number(opts.hourlyCap)))
    : 5;
  const cooldownMs = cooldownHours * HOUR_MS;

  const withTimes = (recentRuns || [])
    .map((run) => ({ run, time: runTime(run) }))
    .filter((entry) => entry.time !== null)
    .sort((a, b) => b.time - a.time);

  const sameCompany = withTimes.filter(
    ({ run }) => normalizeInsightCompany(runCompany(run)) === normalized,
  );
  const inFlight = sameCompany.find(({ run, time }) =>
    IN_FLIGHT_STATUSES.has(String(run.status || "")) &&
    (cooldownMs === 0 || time + cooldownMs > nowMs)
  );
  if (inFlight) return { action: "reuse", run: inFlight.run };

  if (cooldownMs > 0 && sameCompany.length > 0) {
    const newest = sameCompany[0];
    const until = newest.time + cooldownMs;
    if (until > nowMs) {
      return {
        action: "cooldown",
        run: newest.run,
        retryAfterSec: retryAfterSec(until, nowMs),
      };
    }
  }

  if (hourlyCap > 0) {
    const hourly = withTimes.filter(({ time }) => time >= nowMs - HOUR_MS);
    if (hourly.length >= hourlyCap) {
      const oldest = hourly[hourly.length - 1];
      return {
        action: "global_cap",
        retryAfterSec: retryAfterSec(oldest.time + HOUR_MS, nowMs),
      };
    }
  }

  return { action: "dispatch" };
}

function buildInsightEnrichRunRecord({ runId, userId, company, startedAt }) {
  const cleanCompany = String(company || "").trim();
  return {
    id: runId,
    user_id: userId || null,
    query: cleanCompany,
    company: cleanCompany,
    city: null,
    job_type: null,
    mode: "insight_enrich",
    status: "queued",
    provider_name: "insight_enrich",
    started_at: startedAt,
    candidates_found: 0,
    candidates_parsed: 0,
    candidates_pending: 0,
    jobs_created: 0,
    jobs_updated: 0,
    blocked_count: 0,
    failure_reason: null,
    diagnostics: {
      company: cleanCompany,
      source: "insights_enrich_now",
      progress: { done: 0, total: 1 },
    },
  };
}

function buildInsightWorkflowInputs({ company, runId }) {
  const inputs = {
    company: String(company || "").trim(),
    limit: "1",
  };
  if (runId) inputs.run_id = String(runId);
  return inputs;
}

module.exports = {
  HOUR_MS,
  normalizeInsightCompany,
  evaluateInsightEnrichDispatch,
  buildInsightEnrichRunRecord,
  buildInsightWorkflowInputs,
};
