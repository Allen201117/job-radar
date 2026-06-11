// Thin orchestration barrel for official-source discovery (/api/discovery).
//
// The implementation is split by responsibility into ./discovery/*:
//   - filtering.js  URL classification, third-party/content/campus blocking,
//                   official-entry & ATS recognition, China-signal gating.
//   - parsing.js    HTML/JSON -> job-record extraction + detail-page quality
//                   gate (the only IO in this library).
//   - providers.js  search-engine result extraction, provider diagnostics,
//                   daily budget / cache key / query-batch selection.
//   - persist.js    source_candidate record shaping + run-outcome summaries.
//
// This file re-exports the exact same public surface as before the split, so
// every existing importer (app/api/discovery/route.ts, lib/baidu-qianfan-search.js,
// tests/official-discovery.test.js) keeps working unchanged.
const filtering = require("./discovery/filtering");
const parsing = require("./discovery/parsing");
const providers = require("./discovery/providers");
const persist = require("./discovery/persist");

module.exports = {
  buildDiscoveryCacheKey: providers.buildDiscoveryCacheKey,
  buildDiscoveryDailyBudgetStatus: providers.buildDiscoveryDailyBudgetStatus,
  buildDiscoveryQueries: providers.buildDiscoveryQueries,
  buildShanghaiDayWindow: providers.buildShanghaiDayWindow,
  buildSourceCandidateRecord: persist.buildSourceCandidateRecord,
  buildSourceCandidateStatusReason: persist.buildSourceCandidateStatusReason,
  buildRawResultsAudit: providers.buildRawResultsAudit,
  classifyDiscoveryUrl: filtering.classifyDiscoveryUrl,
  createProviderDiagnostic: providers.createProviderDiagnostic,
  extractBingResultUrls: providers.extractBingResultUrls,
  extractDuckDuckGoResultUrls: providers.extractDuckDuckGoResultUrls,
  extractGenericOfficialDetailJob: parsing.extractGenericOfficialDetailJob,
  extractMokaJobsFromHtml: parsing.extractMokaJobsFromHtml,
  extractMokaJobsFromRows: parsing.extractMokaJobsFromRows,
  buildMokaBoardUrl: parsing.buildMokaBoardUrl,
  hasChinaOfficialSignal: filtering.hasChinaOfficialSignal,
  isBannedJobPlatformUrl: filtering.isBannedJobPlatformUrl,
  looksLikeJobDetailPageUrl: filtering.looksLikeJobDetailPageUrl,
  pageContainsJobTitle: parsing.pageContainsJobTitle,
  selectDiscoveryQueryBatch: providers.selectDiscoveryQueryBatch,
  shouldRecordDiscoveryCandidate: filtering.shouldRecordDiscoveryCandidate,
  summarizeCachedDiscovery: persist.summarizeCachedDiscovery,
  summarizeDiscoveryOutcome: persist.summarizeDiscoveryOutcome,
  validateJobQualityGate: parsing.validateJobQualityGate,
};
