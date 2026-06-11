const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildAppleDetailUrl,
  extractBaiduInitialDataFromHtml,
  extractAppleSearchResultsFromHtml,
  formatBaiduSearchResult,
  formatGreenhouseJob,
  formatJdJob,
  formatLeverPosting,
  formatAppleSearchResult,
  filterJobsByQueryAndCity,
  excludeJobs,
  isHighQualityJdUrl,
  mergeJobsByUrl,
} = require("../lib/live-search");

test("formats Apple search results with official detail URLs", () => {
  const job = formatAppleSearchResult({
    id: "200609884-0836",
    postingTitle: "Software Engineer, Watch Software",
    transformedPostingTitle: "software-engineer-watch-software",
    team: { teamCode: "SFTWR" },
    locations: [{ name: "Cupertino" }],
    jobSummary: "Build software for Apple Watch.",
    postingDate: "2026-04-01",
    type: "REQ",
  });

  assert.equal(
    job.jd_url,
    "https://jobs.apple.com/en-us/details/200609884-0836/software-engineer-watch-software?team=SFTWR",
  );
  assert.equal(job.apply_url, job.jd_url);
  assert.equal(job.company, "Apple");
  assert.equal(job.location, "Cupertino");
  assert.ok(isHighQualityJdUrl(job.jd_url, "apple"));
});

test("rejects home and search pages as job detail URLs", () => {
  assert.equal(isHighQualityJdUrl("https://jobs.apple.com/en-us/search", "apple"), false);
  assert.equal(isHighQualityJdUrl("https://jobs.apple.com/", "apple"), false);
  assert.equal(isHighQualityJdUrl("", "apple"), false);
});

test("accepts Moka and generic official detail URLs only when they are detail pages", () => {
  assert.equal(
    isHighQualityJdUrl(
      "https://app.mokahr.com/campus_apply/acme/123?pure=1#/job/job-1/apply",
      "moka",
    ),
    true,
  );
  assert.equal(
    isHighQualityJdUrl("https://app.mokahr.com/campus_apply/acme/123#/jobs", "moka"),
    false,
  );
  assert.equal(
    isHighQualityJdUrl(
      "https://www.shlab.org.cn/joinus/detail/7612950926287391027?mode=campus",
      "generic_official_detail",
    ),
    true,
  );
  assert.equal(
    isHighQualityJdUrl("https://www.shlab.org.cn/joinus", "generic_official_detail"),
    false,
  );
});

test("deduplicates live and cached jobs by jd_url and keeps cached ids", () => {
  const cached = [{ id: "db-1", jd_url: "https://jobs.apple.com/en-us/details/1/a", source: "cached" }];
  const live = [
    { id: "live-1", jd_url: "https://jobs.apple.com/en-us/details/1/a", source: "live" },
    { id: "live-2", jd_url: "https://jobs.apple.com/en-us/details/2/b", source: "live" },
  ];

  const merged = mergeJobsByUrl(cached, live);

  assert.deepEqual(
    merged.map((job) => job.id),
    ["db-1", "live-2"],
  );
});

test("builds Apple detail URL from title when slug is absent", () => {
  assert.equal(
    buildAppleDetailUrl({
      id: "200000001",
      postingTitle: "Data Science Manager",
      team: {},
    }),
    "https://jobs.apple.com/en-us/details/200000001/data-science-manager",
  );
});

test("extracts Apple search results from public search page hydration data", () => {
  const hydration = {
    loaderData: {
      search: {
        searchResults: [
          {
            id: "200664580-3956",
            postingTitle: "Technical Product Manager",
            transformedPostingTitle: "technical-product-manager",
            team: { teamCode: "CORSV" },
            locations: [{ name: "Sunnyvale" }],
          },
        ],
      },
    },
  };
  const html = `<script>window.__staticRouterHydrationData = JSON.parse(${JSON.stringify(JSON.stringify(hydration))});</script>`;

  const rows = extractAppleSearchResultsFromHtml(html);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].id, "200664580-3956");
  assert.equal(rows[0].postingTitle, "Technical Product Manager");
});

test("extracts Baidu official SSR jobs and builds exact detail URLs", () => {
  const html = `
    <script>
      window.__INITIAL_DATA__ ={"listData":{"recruitType":"SOCIAL","listDetailData":[
        {"postId":"46ad568d-c116-417c-91fa-49146c36bb05","name":"Go研发工程师（J100115）","workPlace":"上海市","postType":"技术","updateDate":"2026-05-20","workContent":"负责 Go 后端研发","projectType":undefined}
      ]}}; window.prefix="/jobs";undefined
    </script>
  `;

  const rows = extractBaiduInitialDataFromHtml(html);
  const job = formatBaiduSearchResult(rows[0], "SOCIAL");

  assert.equal(rows.length, 1);
  assert.equal(job.company, "百度");
  assert.equal(job.title, "Go研发工程师（J100115）");
  assert.equal(
    job.jd_url,
    "https://talent.baidu.com/jobs/detail/SOCIAL/46ad568d-c116-417c-91fa-49146c36bb05",
  );
  assert.ok(isHighQualityJdUrl(job.jd_url, "baidu"));
});

test("formats JD public list jobs with official detail URLs", () => {
  const job = formatJdJob({
    requirementId: 217525,
    positionId: 217451,
    positionNameOpen: "数据分析师",
    jobType: "研发类",
    workCity: "北京市",
    formatPublishTime: "2026-05-13",
    workContent: "负责业务数据分析。",
    qualification: "熟练使用 SQL。",
  });

  assert.equal(job.company, "京东");
  assert.equal(job.title, "数据分析师");
  assert.equal(job.location, "北京");
  assert.equal(
    job.jd_url,
    "https://zhaopin.jd.com/web/job-info-detail?requementId=217525",
  );
  assert.ok(isHighQualityJdUrl(job.jd_url, "jd"));
});

test("formats Greenhouse jobs with official absolute URLs", () => {
  const job = formatGreenhouseJob(
    {
      id: 123,
      title: "Forward Deployed Software Engineer",
      absolute_url: "https://job-boards.greenhouse.io/acme/jobs/123",
      location: { name: "New York, NY" },
      departments: [{ name: "Engineering" }],
      updated_at: "2026-05-20T00:00:00Z",
      content: "Build production systems with customers.",
    },
    { company: "Acme", slug: "acme" },
  );

  assert.equal(job.company, "Acme");
  assert.equal(job.title, "Forward Deployed Software Engineer");
  assert.equal(job.job_type, "Engineering");
  assert.equal(job.jd_url, "https://job-boards.greenhouse.io/acme/jobs/123");
  assert.equal(job.apply_url, job.jd_url);
  assert.ok(isHighQualityJdUrl(job.jd_url, "greenhouse"));
});

test("cleans Greenhouse escaped HTML summaries", () => {
  const job = formatGreenhouseJob(
    {
      id: 124,
      title: "AI Engineer",
      absolute_url: "https://job-boards.greenhouse.io/acme/jobs/124",
      location: { name: "Remote" },
      content: "&lt;div class=&quot;intro&quot;&gt;&lt;p&gt;Build &amp;amp; ship AI systems.&lt;/p&gt;&lt;/div&gt;",
    },
    { company: "Acme", slug: "acme" },
  );

  assert.equal(job.summary, "Build & ship AI systems.");
});

test("formats Lever postings with hosted posting URLs", () => {
  const job = formatLeverPosting(
    {
      id: "abc",
      text: "Product Engineer",
      hostedUrl: "https://jobs.lever.co/acme/abc",
      categories: {
        location: "San Francisco, CA",
        team: "Engineering",
        commitment: "Full-time",
      },
      descriptionPlain: "Build product experiences.",
      createdAt: Date.UTC(2026, 4, 20),
    },
    { company: "Acme", slug: "acme" },
  );

  assert.equal(job.company, "Acme");
  assert.equal(job.title, "Product Engineer");
  assert.equal(job.location, "San Francisco, CA");
  assert.equal(job.job_type, "Engineering · Full-time");
  assert.equal(job.jd_url, "https://jobs.lever.co/acme/abc");
  assert.ok(isHighQualityJdUrl(job.jd_url, "lever"));
});

test("filters generic ATS jobs by query and city before upsert", () => {
  const jobs = [
    { title: "Data Engineer", company: "Acme", location: "New York", summary: "Pipelines" },
    { title: "Product Manager", company: "Acme", location: "Remote", summary: "Roadmaps" },
    { title: "Backend Engineer", company: "Beta", location: "London", summary: "Data systems" },
  ];

  assert.deepEqual(
    filterJobsByQueryAndCity(jobs, "data", "new").map((job) => job.title),
    ["Data Engineer"],
  );
});

test("excludeJobs is a no-op when the exclude list is empty", () => {
  const jobs = [
    { title: "Sales Lead", company: "Acme", location: "Beijing" },
    { title: "Data Engineer", company: "Beta", location: "Shanghai" },
  ];
  assert.deepEqual(excludeJobs(jobs, []), jobs);
  assert.deepEqual(excludeJobs(jobs, ["  ", null, undefined]), jobs);
});

test("excludeJobs drops jobs matching an exclude keyword across all fields, case-insensitive", () => {
  const jobs = [
    { title: "Sales Manager", company: "Acme", location: "Beijing", job_type: "社招", summary: "lead the team", salary_text: "" },
    { title: "Data Engineer", company: "BeijingSalesCo", location: "Shanghai", job_type: "社招", summary: "pipelines" },
    { title: "Backend Engineer", company: "Beta", location: "Guangzhou", job_type: "校招", summary: "build APIs" },
    { title: "Marketing Specialist", company: "Gamma", location: "Hangzhou", job_type: "实习", summary: "outreach", salary_text: "20-30万" },
  ];

  // 大小写不敏感 + 命中 title/company 任一字段即剔除（"sales" 命中前两条）。
  assert.deepEqual(
    excludeJobs(jobs, ["SALES"]).map((j) => j.title),
    ["Backend Engineer", "Marketing Specialist"],
  );

  // 多个排除词 OR 语义：命中任一即丢（summary "outreach" + location "guangzhou"）。
  assert.deepEqual(
    excludeJobs(jobs, ["outreach", "guangzhou"]).map((j) => j.title),
    ["Sales Manager", "Data Engineer"],
  );

  // 命中 salary_text 字段也剔除。
  assert.deepEqual(
    excludeJobs(jobs, ["20-30万"]).map((j) => j.title),
    ["Sales Manager", "Data Engineer", "Backend Engineer"],
  );
});

test("expands Chinese search terms for English ATS boards", () => {
  const jobs = [
    {
      title: "Machine Learning Engineer",
      company: "Acme",
      location: "Remote",
      summary: "Build ranking models.",
    },
    {
      title: "Product Designer",
      company: "Acme",
      location: "Remote",
      summary: "Design systems.",
    },
  ];

  assert.deepEqual(
    filterJobsByQueryAndCity(jobs, "算法", "").map((job) => job.title),
    ["Machine Learning Engineer"],
  );
});
