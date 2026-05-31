function mapApiSearchJobsToScoredJobs(apiJobs, query, nowIso = new Date().toISOString()) {
  return (apiJobs || [])
    .filter((job) => Boolean(job?.id && job?.jdUrl))
    .map((job) => ({
      ...job,
      id: job.id,
      source_id: job.sourceId || "",
      match_score: job.match?.score || 50,
      matched_keywords: query ? [query] : [],
      hidden_reason: null,
      user_action: null,
      location: job.location,
      job_type: job.type || "全职",
      company: job.company,
      title: job.title,
      summary: job.summary || "",
      jd_url: job.jdUrl,
      apply_url: job.applyUrl || job.jdUrl,
      salary_text: job.salary || "官网未披露",
      posted_at: job.postedAt || null,
      first_seen_at: job.firstSeenAt || job.postedAt || nowIso,
      last_seen_at: nowIso,
      status: "active",
      content_hash: null,
      created_at: nowIso,
    }));
}

module.exports = {
  mapApiSearchJobsToScoredJobs,
};
