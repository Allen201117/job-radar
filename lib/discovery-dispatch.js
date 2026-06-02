/**
 * 按需「浏览器发现」派发层（纯函数 + 一个 fetch 触发器）。
 *
 * 职责：把"点一下发现 → 触发 GitHub Actions workflow_dispatch 跑 Playwright 拦截 →
 * 前端轮询 discovery_runs 状态"这套异步流的**可单测部分**抽出来：
 *   - 解析派发配置（token / repo / workflow / ref）
 *   - 校验/归一化发现入参
 *   - 构造 discovery_runs 的 'queued' 记录
 *   - 构造 GitHub workflow_dispatch 的 HTTP 请求
 *   - 把 DB run 状态汇总成前端加载态要的 phase
 *
 * 真正的网络/DB I/O 在 app/api/discovery/{dispatch,status}/route.ts 里，便于单测不打网络。
 */

const DEFAULT_WORKFLOW_FILE = "daily-crawl.yml";
const DEFAULT_DISPATCH_REF = "main";
const MAX_QUERY_LEN = 80;
const DEFAULT_LIMIT = 30;
const MAX_LIMIT = 60;
const TERMINAL_STATUSES = ["success", "partial_success", "failed", "skipped"];

/** "owner/name" 或完整 github URL → { owner, name }；不合法返回 null。 */
function parseRepoSlug(repo) {
  const text = String(repo || "").trim();
  if (!text) return null;
  const stripped = text
    .replace(/^https?:\/\/github\.com\//i, "")
    .replace(/\.git$/i, "");
  const parts = stripped.split("/").filter(Boolean);
  if (parts.length < 2) return null;
  return { owner: parts[0], name: parts[1] };
}

/** 从 env 读取派发配置；configured=false 时附带 missing 列表，路由可据此返回明确错误。 */
function resolveDispatchConfig(env = {}) {
  const token = env.GITHUB_DISPATCH_TOKEN || env.GH_DISPATCH_TOKEN || "";
  const repo = env.GITHUB_DISPATCH_REPO || env.GITHUB_REPO || "";
  const workflowFile = env.GITHUB_DISPATCH_WORKFLOW || DEFAULT_WORKFLOW_FILE;
  const ref = env.GITHUB_DISPATCH_REF || DEFAULT_DISPATCH_REF;
  const slug = parseRepoSlug(repo);

  const missing = [];
  if (!token) missing.push("GITHUB_DISPATCH_TOKEN");
  if (!slug) missing.push("GITHUB_DISPATCH_REPO");

  return {
    token,
    repo,
    slug,
    workflowFile,
    ref,
    configured: missing.length === 0,
    missing,
  };
}

/** 校验并归一化发现入参。 */
function validateDiscoveryDispatchInput(input = {}) {
  const errors = [];
  const query = String(input.query || "").trim();
  if (!query) errors.push("query_required");
  if (query.length > MAX_QUERY_LEN) errors.push("query_too_long");

  const city = String(input.city || "").trim();
  const company = String(input.company || "").trim();
  const jobType = String(input.jobType || input.job_type || "").trim();

  let limit = Number(input.limit);
  if (!Number.isFinite(limit) || limit <= 0) limit = DEFAULT_LIMIT;
  limit = Math.min(Math.max(Math.floor(limit), 1), MAX_LIMIT);

  return {
    ok: errors.length === 0,
    errors,
    normalized: { query, city, company, jobType, limit },
  };
}

/** 构造一条 'queued' 的 discovery_runs 记录（需 009 迁移：status='queued' + mode/started_at/user_id）。 */
function buildBrowserDiscoveryRunRecord({
  runId,
  userId,
  query,
  city,
  company,
  jobType,
  startedAt,
}) {
  return {
    id: runId,
    user_id: userId || null,
    query,
    city: city || null,
    company: company || null,
    job_type: jobType || null,
    mode: "browser_discovery",
    status: "queued",
    provider_name: "browser_intercept",
    started_at: startedAt,
    candidates_found: 0,
    candidates_parsed: 0,
    candidates_pending: 0,
    jobs_created: 0,
    jobs_updated: 0,
    blocked_count: 0,
    failure_reason: null,
  };
}

/** 构造 GitHub workflow_dispatch 的 HTTP 请求描述（不发起请求）。inputs 全部转成字符串（GitHub 要求）。 */
function buildWorkflowDispatchRequest({
  slug,
  workflowFile,
  ref,
  token,
  inputs,
  userAgent = "job-radar-discovery",
}) {
  if (!slug || !slug.owner || !slug.name) {
    throw new Error("buildWorkflowDispatchRequest: invalid repo slug");
  }
  if (!workflowFile) {
    throw new Error("buildWorkflowDispatchRequest: missing workflow file");
  }
  if (!token) {
    throw new Error("buildWorkflowDispatchRequest: missing dispatch token");
  }

  const url =
    `https://api.github.com/repos/${slug.owner}/${slug.name}` +
    `/actions/workflows/${encodeURIComponent(workflowFile)}/dispatches`;

  const stringInputs = {};
  for (const [key, value] of Object.entries(inputs || {})) {
    stringInputs[key] = value === null || value === undefined ? "" : String(value);
  }

  return {
    url,
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": userAgent,
    },
    body: JSON.stringify({ ref: ref || DEFAULT_DISPATCH_REF, inputs: stringInputs }),
  };
}

/** workflow_dispatch 成功是 204 No Content；容忍 200/201。 */
function isDispatchAccepted(httpStatus) {
  return httpStatus === 204 || httpStatus === 201 || httpStatus === 200;
}

/** 把 discovery_runs 行汇总成前端加载态要的 phase + 计数。 */
function summarizeDiscoveryRunStatus(run) {
  const status = String(run?.status || "").trim() || "unknown";
  const isTerminal = TERMINAL_STATUSES.includes(status);

  let phase;
  if (status === "queued") phase = "queued";
  else if (status === "running") phase = "running";
  else if (status === "success" || status === "partial_success") phase = "done";
  else if (status === "failed" || status === "skipped") phase = "failed";
  else phase = "unknown";

  return {
    status,
    phase,
    isTerminal,
    jobsCreated: Number(run?.jobs_created || 0),
    jobsUpdated: Number(run?.jobs_updated || 0),
    candidatesFound: Number(run?.candidates_found || 0),
    failureReason: run?.failure_reason || null,
    errorMessage: run?.error_message || null,
    startedAt: run?.started_at || run?.created_at || null,
    finishedAt: run?.finished_at || null,
  };
}

/** 从 run.diagnostics.produced_jd_urls 取本次产出的 jd_url 列表（status 端据此回查 jobs）。 */
function extractProducedJdUrls(run) {
  const diagnostics = run && run.diagnostics;
  const list =
    diagnostics && Array.isArray(diagnostics.produced_jd_urls)
      ? diagnostics.produced_jd_urls
      : [];
  return list.filter((url) => typeof url === "string" && url);
}

module.exports = {
  DEFAULT_WORKFLOW_FILE,
  DEFAULT_DISPATCH_REF,
  MAX_QUERY_LEN,
  TERMINAL_STATUSES,
  parseRepoSlug,
  resolveDispatchConfig,
  validateDiscoveryDispatchInput,
  buildBrowserDiscoveryRunRecord,
  buildWorkflowDispatchRequest,
  isDispatchAccepted,
  summarizeDiscoveryRunStatus,
  extractProducedJdUrls,
};
