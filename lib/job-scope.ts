export type JobScopePreference = "domestic" | "overseas" | "all";
export type JobRegion = "US" | "SG" | "Remote";

type ScopePrefs = {
  job_scope?: string | null;
  target_regions?: string[] | null;
} | null;

type ScopeJob = {
  job_scope?: string | null;
  country_code?: string | null;
  location?: string | null;
};

const DEFAULT_OVERSEAS_REGIONS: JobRegion[] = ["US", "SG", "Remote"];
const REGION_ALIASES: Record<string, JobRegion> = {
  us: "US",
  usa: "US",
  "united states": "US",
  美国: "US",
  sg: "SG",
  singapore: "SG",
  新加坡: "SG",
  remote: "Remote",
  global: "Remote",
  全球远程: "Remote",
  远程: "Remote",
};

export function effectiveJobScope(preferences: ScopePrefs): JobScopePreference {
  const scope = preferences?.job_scope;
  return scope === "overseas" || scope === "all" ? scope : "domestic";
}

export function normalizeJobRegion(value: unknown): JobRegion | "" {
  if (typeof value !== "string") return "";
  const key = value.trim().toLowerCase();
  return REGION_ALIASES[key] || "";
}

export function effectiveTargetRegions(preferences: ScopePrefs): JobRegion[] {
  const scope = effectiveJobScope(preferences);
  if (scope === "domestic") return [];

  const out: JobRegion[] = [];
  const seen = new Set<JobRegion>();
  for (const raw of preferences?.target_regions || []) {
    const region = normalizeJobRegion(raw);
    if (!region || seen.has(region)) continue;
    seen.add(region);
    out.push(region);
  }
  return out.length > 0 ? out : DEFAULT_OVERSEAS_REGIONS;
}

export function jobMatchesRegion(job: ScopeJob, regionValue: unknown): boolean {
  const region = normalizeJobRegion(regionValue);
  if (!region) return true;
  if (job.job_scope !== "overseas") return false;
  if (region === "Remote") return isGlobalRemoteJob(job);
  return String(job.country_code || "").toUpperCase() === region;
}

export function jobMatchesScope(
  job: ScopeJob,
  preferences: ScopePrefs,
  regionValue: unknown = "",
): boolean {
  const region = normalizeJobRegion(regionValue);
  if (region) return jobMatchesRegion(job, region);

  const scope = effectiveJobScope(preferences);
  const jobScope = job.job_scope || "domestic";
  if (scope === "domestic") return jobScope === "domestic";
  if (scope === "all") return true;
  if (jobScope !== "overseas") return false;

  const regions = effectiveTargetRegions(preferences);
  return regions.some((r) => jobMatchesRegion(job, r));
}

export function appendJobScopeWhere(
  conds: string[],
  params: unknown[],
  preferences: ScopePrefs,
  filters: { region?: string | null } = {},
): void {
  const region = normalizeJobRegion(filters.region || "");
  if (region) {
    conds.push("job_scope = 'overseas'");
    appendRegionWhere(conds, params, [region]);
    return;
  }

  const scope = effectiveJobScope(preferences);
  if (scope === "domestic") {
    conds.push("coalesce(job_scope, 'domestic') = 'domestic'");
    return;
  }
  if (scope === "all") return;

  conds.push("job_scope = 'overseas'");
  appendRegionWhere(conds, params, effectiveTargetRegions(preferences));
}

function appendRegionWhere(conds: string[], params: unknown[], regions: JobRegion[]): void {
  const countryRegions = regions.filter((r) => r !== "Remote");
  const parts: string[] = [];
  if (countryRegions.length > 0) {
    params.push(countryRegions);
    parts.push(`country_code = any($${params.length}::text[])`);
  }
  if (regions.includes("Remote")) {
    parts.push(
      "(country_code is null and (lower(coalesce(location, '')) like '%remote%' or coalesce(location, '') like '%远程%'))",
    );
  }
  if (parts.length > 0) conds.push(`(${parts.join(" or ")})`);
}

function isGlobalRemoteJob(job: ScopeJob): boolean {
  if (job.job_scope !== "overseas") return false;
  if (job.country_code) return false;
  const location = String(job.location || "").toLowerCase();
  return location.includes("remote") || location.includes("远程");
}
