const { toDbDetectedPlatform } = require("./filtering");

function buildSourceCandidateRecord({
  query,
  fallbackCompany,
  fallbackTitle,
  url,
  classification,
  providerResult,
  status,
}) {
  const provider = providerResult || {};
  const reason = {
    provider_name: provider.provider_name || null,
    provider_query: provider.provider_query || null,
    title: provider.title || null,
    snippet: provider.snippet || null,
    query,
    url,
    company_guess: classification.company || fallbackCompany || null,
    source_type: classification.sourceType,
    detected_platform: classification.detectedPlatform,
    db_detected_platform: classification.dbDetectedPlatform,
    confidence: classification.confidence,
    status,
    reason: classification.reason,
    matched_keywords: classification.matchedKeywords || [],
    official_signal: classification.officialSignal || null,
    reject_reason: classification.rejectReason || null,
    parser_supported: Boolean(classification.parserSupported),
    parser_name: classification.parserName || null,
    classification,
  };

  return {
    query,
    company: classification.company || fallbackCompany,
    title: fallbackTitle,
    url,
    source_type: classification.sourceType,
    detected_platform: classification.dbDetectedPlatform || toDbDetectedPlatform(classification.detectedPlatform),
    confidence: classification.confidence,
    status,
    reason: JSON.stringify(reason),
  };
}

function buildSourceCandidateStatusReason({
  previousReason,
  status,
  statusReason,
  updatedAt = new Date().toISOString(),
} = {}) {
  const base = parseReasonJson(previousReason);
  return JSON.stringify({
    ...base,
    status,
    status_update: statusReason,
    status_updated_at: updatedAt,
  });
}

function parseReasonJson(reason) {
  if (!reason) return {};
  if (typeof reason === "object") return reason;
  try {
    const parsed = JSON.parse(String(reason));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : { previous_reason: String(reason) };
  } catch {
    return { previous_reason: String(reason) };
  }
}

function summarizeDiscoveryOutcome({
  totalExtractedUrls,
  blockedCount,
  candidatesFound,
  candidatesParsed,
  candidatesPending,
  candidatesFailed = 0,
  parserSupportedCandidates = null,
  qualityGateFailures = 0,
  jobsCreated,
  jobsUpdated,
  providers,
  errors,
}) {
  const providerFailures = (providers || []).filter(
    (provider) => provider.status === "provider_failed",
  );
  const hasProviderFailures = providerFailures.length > 0;
  const hasProviderRateLimit = (providers || []).some(isProviderRateLimited);
  const hasProviderDisabled = (providers || []).some(isProviderDisabled);
  const hasWrittenJobs = jobsCreated > 0 || jobsUpdated > 0;
  const errorMessage = (errors || []).filter(Boolean).join("\n").slice(0, 4000);
  const supportedCandidateCount =
    parserSupportedCandidates === null || parserSupportedCandidates === undefined
      ? null
      : Number(parserSupportedCandidates) || 0;

  if (hasWrittenJobs) {
    return {
      status:
        hasProviderFailures || candidatesFailed > 0 || qualityGateFailures > 0
          ? "partial_success"
          : "success",
      failureReason:
        qualityGateFailures > 0 || candidatesFailed > 0
          ? "quality_gate_failed"
          : hasProviderRateLimit
            ? "provider_rate_limited"
            : hasProviderFailures
              ? "provider_failed"
              : null,
      errorMessage: errorMessage || null,
    };
  }

  if (hasProviderRateLimit) {
    return {
      status: "failed",
      failureReason: "provider_rate_limited",
      errorMessage: errorMessage || "Baidu Qianfan rate limited the realtime discovery request.",
    };
  }

  if (hasProviderDisabled) {
    return {
      status: "failed",
      failureReason: "provider_disabled",
      errorMessage:
        errorMessage ||
        "Baidu Qianfan web search is disabled by BAIDU_QIANFAN_SEARCH_DISABLED.",
    };
  }

  if (hasProviderFailures && totalExtractedUrls === 0) {
    return {
      status: "failed",
      failureReason: "provider_failed",
      errorMessage: errorMessage || "All search providers failed before returning URLs.",
    };
  }

  if (totalExtractedUrls === 0) {
    return {
      status: "failed",
      failureReason: "provider_no_results",
      errorMessage: "Search provider returned no extractable results.",
    };
  }

  if (candidatesFound === 0) {
    return {
      status: "failed",
      failureReason: "all_results_rejected",
      errorMessage:
        "Search provider returned URLs, but every result was rejected by source-quality filters.",
    };
  }

  if (qualityGateFailures > 0 || candidatesFailed > 0) {
    return {
      status: "partial_success",
      failureReason: "quality_gate_failed",
      errorMessage:
        errorMessage || "Supported parsers found candidates, but the job detail quality gate rejected them.",
    };
  }

  if (candidatesFound > 0 && candidatesPending === candidatesFound) {
    if (supportedCandidateCount === 0) {
      return {
        status: "partial_success",
        failureReason: "parser_missing",
        errorMessage:
          "Official candidates were recorded, but no supported parser can produce high-quality job detail URLs yet.",
      };
    }

    return {
      status: "partial_success",
      failureReason: "candidates_pending",
      errorMessage:
        "Discovered candidates are pending review or unsupported parsers; no jobs were written.",
    };
  }

  if (candidatesFound > 0 && candidatesParsed === 0) {
    return {
      status: "partial_success",
      failureReason: "quality_gate_failed",
      errorMessage:
        errorMessage || "Supported parsers produced no jobs with high-quality detail URLs.",
    };
  }

  return {
    status: hasProviderFailures ? "partial_success" : "success",
    failureReason: hasProviderFailures ? "provider_failed" : null,
    errorMessage: errorMessage || null,
  };
}

function isProviderRateLimited(provider) {
  return Boolean(
    provider?.diagnostics?.rate_limited ||
      provider?.http_status === 429 ||
      /429|rate\s*limit|too many requests|限流|频率/i.test(String(provider?.error || "")),
  );
}

function isProviderDisabled(provider) {
  return Boolean(
    provider?.diagnostics?.disabled ||
      provider?.diagnostics?.disabled_by_env ||
      /disabled/i.test(String(provider?.error || "")),
  );
}

function summarizeCachedDiscovery({ run, candidates = [], jobs = [] } = {}) {
  const candidatesParsed = candidates.filter((candidate) => candidate.status === "parsed").length;
  const candidatesPending = candidates.filter((candidate) => candidate.status === "pending").length;
  const candidatesFailed = candidates.filter((candidate) => candidate.status === "failed").length;
  const jobsReused = jobs.length;

  return {
    cache_hit: true,
    cache_source: run ? "discovery_runs" : "memory",
    status: jobsReused > 0 ? "success" : run?.status || "partial_success",
    candidates_found: candidates.length,
    candidates_parsed: candidatesParsed,
    candidates_pending: candidatesPending,
    candidates_failed: candidatesFailed,
    jobs_reused: jobsReused,
    jobs_created: 0,
    jobs_updated: 0,
    failure_reason:
      jobsReused > 0
        ? null
        : candidates.length > 0
          ? candidatesFailed > 0 && candidatesPending === 0
            ? "quality_gate_failed"
            : "candidates_pending"
          : "provider_no_results",
    error_message: jobsReused > 0 ? null : run?.error_message || null,
  };
}

module.exports = {
  buildSourceCandidateRecord,
  buildSourceCandidateStatusReason,
  summarizeDiscoveryOutcome,
  summarizeCachedDiscovery,
};
