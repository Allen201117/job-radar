const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

// 判「新岗」只有一份实现（lib/job-novelty.ts）。这里钉三件事：
//   ① 规则本身：只把「有官方发布日、且比首见早 7 天以上」的岗排除出「新」，其余一律照旧；
//   ② JS 与 SQL 两份判据用同一个天数、同一个方向；
//   ③ 读侧每一处都走它——谁再手写「首见 N 天内 = 新」就红。
const ROOT = path.join(__dirname, "..");
const novelty = loadTs(path.join(ROOT, "lib", "job-novelty.ts"));
const { STALE_ON_ARRIVAL_DAYS, staleOnArrival, noveltyAgeMs, isNewWithinDays, SQL_NOT_STALE_ON_ARRIVAL, sqlIsNew } = novelty;

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-12T12:00:00Z");
const iso = (ms) => new Date(ms).toISOString();
// now 默认用写死的 NOW，只给「被测函数自己显式收 nowMs」的用例用；被测代码读真实时钟的，传 Date.now() 进来。
const job = (seenDaysAgo, postedDaysAgo, now = NOW) => ({
  first_seen_at: iso(now - seenDaysAgo * DAY),
  posted_at: postedDaysAgo === null ? null : iso(now - postedDaysAgo * DAY),
});

test("没有发布日 → 照旧按首见算", () => {
  assert.equal(staleOnArrival(job(1, null)), false);
  assert.equal(isNewWithinDays(job(1, null), 7, NOW), true);
  assert.equal(isNewWithinDays(job(8, null), 7, NOW), false);
  assert.equal(noveltyAgeMs(job(2, null), NOW), 2 * DAY);
});

test("发布日比首见早 7 天以上 → 不算新岗，哪个窗口都不算", () => {
  const old = job(0.5, 40); // 半天前才抓到，官网写的是 40 天前发布
  assert.equal(staleOnArrival(old), true);
  assert.equal(noveltyAgeMs(old, NOW), null);
  for (const days of [1, 3, 7]) assert.equal(isNewWithinDays(old, days, NOW), false);
});

test("门槛是「早 7 天以上」：正好 7 天不算老岗，多 1 毫秒才算", () => {
  const seen = NOW - DAY;
  assert.equal(staleOnArrival({ first_seen_at: iso(seen), posted_at: iso(seen - STALE_ON_ARRIVAL_DAYS * DAY) }), false);
  assert.equal(staleOnArrival({ first_seen_at: iso(seen), posted_at: iso(seen - STALE_ON_ARRIVAL_DAYS * DAY - 1) }), true);
  // 常见情形：昨天发布、今天凌晨抓到（隔 1~2 天）不受影响
  assert.equal(isNewWithinDays(job(0.2, 1.6), 3, NOW), true);
  // 隔 6 天才抓到，仍算新岗
  assert.equal(isNewWithinDays(job(0.5, 6.4), 7, NOW), true);
});

test("发布日比首见晚（对方刷新过）→ 照旧按首见算：发布日再新也不会把老行重新算成新岗", () => {
  const refreshed = job(40, 1); // 40 天前就抓到了，对方昨天刷新了发布日
  assert.equal(staleOnArrival(refreshed), false);
  assert.equal(isNewWithinDays(refreshed, 7, NOW), false, "首见 40 天前的行不许因为发布日新就算新");
  assert.equal(noveltyAgeMs(refreshed, NOW), 40 * DAY);
  // 首见在窗口内、发布日更晚：照常算新
  assert.equal(isNewWithinDays(job(2, 1), 3, NOW), true);
});

test("时间格式：node-pg 交付的原始文本、ISO、Date 对象都认；缺失 / 乱码不算新也不报错", () => {
  // lib/jobs-store/client.ts 把 timestamptz 原样交付成「2026-10-12 03:04:05.123456+00」这种文本
  const pg = { first_seen_at: "2026-10-12 03:04:05.123456+00", posted_at: "2026-08-01 00:00:00+08" };
  assert.equal(staleOnArrival(pg), true);
  assert.equal(staleOnArrival({ first_seen_at: new Date(NOW), posted_at: new Date(NOW - 30 * DAY) }), true);
  assert.equal(staleOnArrival({ first_seen_at: "2026-10-12T03:04:05Z", posted_at: "2026-10-10" }), false);
  for (const bad of [{}, { first_seen_at: null }, { first_seen_at: "" }, { first_seen_at: "not a date" }]) {
    assert.equal(staleOnArrival(bad), false);
    assert.equal(noveltyAgeMs(bad, NOW), null);
    assert.equal(isNewWithinDays(bad, 7, NOW), false);
  }
  // 发布日是乱码 → 当作没有发布日，照旧按首见算
  assert.equal(isNewWithinDays({ first_seen_at: iso(NOW - DAY), posted_at: "soon" }, 3, NOW), true);
});

// 这一条只钉「两份判据的文本用的是同一个天数、同一个方向」，不碰数据库，测不出 SQL 本身写错。
// SQL 在真库上的行为另做过逐行对拍（2026-10-12：11,346 行，两个方向 0 不一致，见
// docs/reviews/2026-10-12-novelty-official-posted-date.md §4.3）；改 SQL 片段要重做那一步。
test("SQL 与 JS 同一个天数、同一个方向", () => {
  assert.equal(
    SQL_NOT_STALE_ON_ARRIVAL,
    `(posted_at is null or first_seen_at - posted_at <= interval '${STALE_ON_ARRIVAL_DAYS} days')`,
  );
  assert.equal(
    sqlIsNew("first_seen_at > now() - interval '7 days'"),
    `(first_seen_at > now() - interval '7 days' and ${SQL_NOT_STALE_ON_ARRIVAL})`,
  );
  // 把 SQL 条件按字面翻成 JS 再对一遍边界：posted 为空放行；首见 - 发布 <= N 天放行。
  const sqlSays = (j) => {
    if (j.posted_at === null) return true;
    return Date.parse(j.first_seen_at) - Date.parse(j.posted_at) <= STALE_ON_ARRIVAL_DAYS * DAY;
  };
  for (const [seen, posted] of [[1, null], [1, 2], [1, 8], [1, 8.001], [1, 9], [0, 400], [40, 1], [3, 3]]) {
    const j = job(seen, posted);
    assert.equal(!staleOnArrival(j), sqlSays(j), `seen=${seen} posted=${posted}`);
  }
});

// ── 读侧每一处都走这一份 ──
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

test("岗位库打分 / 粗排 / 候选收窄用的是同一个判据", () => {
  const scoring = loadTs(path.join(ROOT, "lib", "scoring.ts"));
  const prefs = { target_roles: [], target_keywords: [], target_locations: [], target_companies: [], exclude_keywords: [] };
  const base = { id: "j1", company: "某公司", title: "岗位", summary: "", location: "", status: "active" };
  // scoreJob 判「近 7 天新增」读真实时钟（isNewWithinDays 不传 nowMs），样本必须按真实的现在造。
  // 曾按写死的 NOW（10-12）造：10-18 起 fresh 拿 0 分、CI 必红；old 拿 0 分也成了白测（首见本身就出了 7 天窗口）。
  const realNow = Date.now();
  const fresh = scoring.scoreJob({ ...base, ...job(1, null, realNow) }, prefs, []);
  const freshPosted = scoring.scoreJob({ ...base, ...job(1, 2, realNow) }, prefs, []);
  const old = scoring.scoreJob({ ...base, ...job(1, 60, realNow) }, prefs, []);
  assert.equal(fresh.score, 10);
  assert.equal(freshPosted.score, 10);
  assert.equal(old.score, 0, "进来时就已经发布 60 天的岗不拿「近 7 天新增」的分");
  assert.ok(fresh.match_reasons.some((r) => r.type === "freshness"));
  assert.ok(!old.match_reasons.some((r) => r.type === "freshness"), "也不出「近 7 天新增」这条理由");

  const search = read("lib/jobs-store/search.ts");
  assert.match(search, /const recent = sqlIsNew\("first_seen_at > now\(\) - interval '7 days'"\);/);
  // 加权项与收窄条件都引用同一个 recent；文件里不许再出现裸的「首见 7 天内」SQL 条件
  assert.match(search, /pieces\.push\(`\(\$\{recent\} is true\)::int \* 10`\)/);
  const bare = search.split("\n").filter((l) => !l.trim().startsWith("//") && !l.trim().startsWith("*"))
    .filter((l) => /first_seen_at > now\(\) - interval '7 days'/.test(l) && !/sqlIsNew\(/.test(l));
  assert.deepEqual(bare, [], "search.ts 里的「近 7 天」条件必须经 sqlIsNew");
});

test("「仅新岗位」筛选与卡片「新发现」徽标：首见 3 天内且不是老岗", () => {
  const { jobFilterMatch, DEFAULT_FILTERS } = loadTs(path.join(ROOT, "lib", "job-filter.ts"));
  const filters = { ...DEFAULT_FILTERS, showNewOnly: true };
  const base = { id: "j1", company: "某公司", title: "岗位", summary: "", location: "", status: "active", hidden_reason: null };
  const realNow = Date.now();
  const at = (seenDaysAgo, postedDaysAgo) => ({
    ...base,
    first_seen_at: iso(realNow - seenDaysAgo * DAY),
    posted_at: postedDaysAgo === null ? null : iso(realNow - postedDaysAgo * DAY),
  });
  assert.ok(jobFilterMatch(at(1, null), filters));
  assert.ok(jobFilterMatch(at(1, 2), filters));
  assert.equal(jobFilterMatch(at(1, 30), filters), null, "老岗不进「仅新岗位」");
  assert.equal(jobFilterMatch(at(4, null), filters), null);
  assert.ok(jobFilterMatch(at(1, 30), { ...DEFAULT_FILTERS }), "不开这个筛选时老岗照常展示");

  // 徽标与筛选共用同一个窗口常量，不是两处各写一个 3
  assert.equal(novelty.NEW_BADGE_DAYS, 3);
  assert.match(read("components/JobCard.tsx"), /const isNew = isNewWithinDays\(job, NEW_BADGE_DAYS\);/);
  assert.match(read("lib/job-filter.ts"), /filters\.showNewOnly && !isNewWithinDays\(job, NEW_BADGE_DAYS\)/);
});

test("今日推荐：老岗没有新鲜度事实 → 不出「今天首次发现」、不拿新鲜度分；召回的城市新岗层同口径", () => {
  const { scoreOpportunity, buildReasons } = loadTs(path.join(ROOT, "lib", "opportunities", "scoring.ts"));
  const facts = (noveltyHours) => ({
    roleTier: null, roleTitleHit: false, roleMatchLabel: null, companyHit: false, companyName: null,
    location: "mismatch", locationName: null, stage: "mismatch", stageLabel: null, industry: "mismatch", industryName: null,
    skillsHit: [], noveltyHours, freshness: "unknown", summaryLong: false, viewed: false, userAction: null,
  });
  assert.equal(scoreOpportunity(facts(2), []).score, 10);
  assert.equal(scoreOpportunity(facts(null), []).score, 0);
  assert.ok(buildReasons(facts(2)).some((r) => r.label === "今天首次发现"));
  assert.ok(!buildReasons(facts(null)).some((r) => r.label === "今天首次发现"));

  const elig = read("lib/opportunities/eligibility.ts");
  assert.match(elig, /const noveltyMs = noveltyAgeMs\(job, now\.getTime\(\)\);/);
  assert.ok(!/new Date\(job\.first_seen_at\)/.test(elig), "eligibility 不许再自己拿首见时间算新鲜度");

  const recall = read("lib/jobs-store/opportunities.ts");
  assert.match(recall, /conds: \[cityRef, "first_seen_at >= \$1", SQL_NOT_STALE_ON_ARRIVAL\]/);
  assert.match(read("lib/opportunities/grouping.ts"), /!staleOnArrival\(\{ first_seen_at: o\.firstSeenAt, posted_at: o\.officialPostedAt \}\)/);
});

test("读侧不许再手写「首见 N 天内 = 新」", () => {
  // 判新的算术只许出现在 lib/job-novelty.ts。扫 lib / app / components 的源码（去掉注释行）：
  // 「Date.now() 减 first_seen_at」这种 JS 写法出现在别处就红（改前三处读侧都是这个写法）。
  // 它拦不住别的写法，也拦不住 SQL 里手写的时间窗——那几处由上面各条用例逐个点名。
  const offenders = [];
  const walk = (dir) => {
    for (const ent of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = `${dir}/${ent.name}`;
      if (ent.isDirectory()) {
        if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
        walk(rel);
      } else if (/\.(ts|tsx|js)$/.test(ent.name) && rel !== "lib/job-novelty.ts") {
        const lines = read(rel).split("\n");
        lines.forEach((line, i) => {
          const code = line.trim();
          if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*")) return;
          if (/Date\.now\(\)\s*-\s*new Date\([^)]*first_seen_at\)/.test(code)) offenders.push(`${rel}:${i + 1}`);
        });
      }
    }
  };
  for (const dir of ["lib", "app", "components"]) walk(dir);
  assert.deepEqual(offenders, [], "判新一律走 lib/job-novelty（isNewWithinDays / noveltyAgeMs）");
});
