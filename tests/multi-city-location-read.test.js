// 多城市地点「北京/深圳/上海」在读侧的每条路径上，每个城市都得匹配得上（2026-10-11）。
//
// 背景：爬虫入库清洗（crawler/normalizer.clean_location）此前把多地并列的地点整串折成**一个**城市，
// 现在逐个城市折、用「/」连起来——与标题城市兜底（lib/geo titleCityLocation「连云港/苏州」）同一种写法。
// 读侧一共五处读 location 判城市，这里各钉一条：少认一个城市 = 那个城市的用户在今日推荐被硬拒 / 筛选搜不到。
const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");
const { loadTs } = require("./_load-ts");

const ROOT = path.join(__dirname, "..");
const { matchLocationTargets, locationTargetSqlTerms } = loadTs(
  path.join(ROOT, "lib", "opportunities", "location-targets.ts"),
);
const { locationMatchesCityFilter, cityFtsTerms, citySqlLikeTokens } = loadTs(path.join(ROOT, "lib", "job-filter.ts"));
const { queryTokens } = loadTs(path.join(ROOT, "lib", "job-search.ts"));
const { scoreJob } = loadTs(path.join(ROOT, "lib", "scoring.ts"));
const {
  normalizeCampusCity, buildCampusFacets, campusFacetKey, selectFacetIndexes, countMatchingFacets, campusRowMatches,
  selectFitIndexes, facetMatchesFit,
} = loadTs(path.join(ROOT, "lib", "campus-facets.ts"));

const MULTI = "北京/深圳/上海";

// jobs-db/schema.sql 的 search_tokens + to_tsvector('simple')：按空白切词，纯拉丁整词，其余相邻双字（标点由 simple 解析器丢掉）。
function searchDocTokens(location) {
  const out = new Set();
  for (const tok of location.toLowerCase().split(/\s+/)) {
    if (!tok) continue;
    if (/^[a-z0-9]+$/.test(tok) || tok.length === 1) {
      out.add(tok);
      continue;
    }
    for (let i = 0; i < tok.length - 1; i++) out.add(tok.slice(i, i + 2));
  }
  return out;
}
function ftsHits(location, terms) {
  const doc = searchDocTokens(location);
  return terms.some((term) => {
    const tokens = queryTokens(term);
    return tokens.length > 0 && tokens.every((t) => doc.has(t));
  });
}

function job(location) {
  return {
    id: "j1", source_id: "s1", company: "示例公司", title: "产品经理", location, job_type: null,
    summary: "负责产品规划", jd_url: "https://e/job/1", apply_url: null, salary_text: null,
    posted_at: null, experience: null, education: null, deadline: null,
    first_seen_at: "2026-10-11T00:00:00.000Z", last_seen_at: "2026-10-11T00:00:00.000Z", status: "active",
    content_hash: null, created_at: "",
  };
}
function locationBonus(location, target) {
  const prefs = {
    target_keywords: [], exclude_keywords: [], target_locations: [target], target_companies: [],
    target_roles: [], skills: [], industries: [],
  };
  return scoreJob(job(location), prefs, []).match_reasons.some((r) => r.type === "location");
}

test("/today：多城市地点里的每个城市、所在的省都算命中，没列的城市不算", () => {
  for (const city of ["北京", "深圳", "上海", "广东", "广东省"]) {
    assert.ok(matchLocationTargets(MULTI, [city]), city);
  }
  assert.equal(matchLocationTargets(MULTI, ["杭州"]), null);
  assert.equal(matchLocationTargets(MULTI, ["浙江"]), null);
  assert.ok(matchLocationTargets("长春/沈阳", ["辽宁"]));
  assert.ok(matchLocationTargets("北京/河北", ["河北"]));
});

test("/jobs 城市筛选：每个城市（含别名写法）都筛得到，没列的城市筛不到", () => {
  for (const city of ["北京", "深圳", "上海", "深圳市", "Shenzhen", "广东", "珠三角"]) {
    assert.equal(locationMatchesCityFilter(MULTI, [city]), true, city);
  }
  assert.equal(locationMatchesCityFilter(MULTI, ["杭州"]), false);
  assert.equal(locationMatchesCityFilter(MULTI, ["四川"]), false);
});

test("全文候选门：每个城市的检索词都在 search_doc 的相邻双字里（三字城市名也在）", () => {
  for (const city of ["北京", "深圳", "上海", "广东"]) {
    assert.ok(ftsHits(MULTI, cityFtsTerms([city])), `/jobs ${city}`);
    assert.ok(ftsHits(MULTI, locationTargetSqlTerms(city)), `/today ${city}`);
  }
  assert.ok(ftsHits("连云港/苏州/乌鲁木齐", cityFtsTerms(["连云港"])));
  assert.ok(ftsHits("连云港/苏州/乌鲁木齐", cityFtsTerms(["乌鲁木齐"])));
  assert.equal(ftsHits(MULTI, cityFtsTerms(["杭州"])), false);
});

test("候选 where 的 location ilike：每个城市的词都是子串", () => {
  for (const city of ["北京", "深圳", "上海", "广东"]) {
    const tokens = citySqlLikeTokens([city]);
    assert.ok(tokens.some((t) => MULTI.toLowerCase().includes(t.toLowerCase())), city);
  }
});

test("打分的城市 +20：多城市地点里的每个城市都拿得到，目标写成别名也一样", () => {
  for (const target of ["北京", "深圳", "上海", "深圳市", "Shenzhen", "上海市", "广东"]) {
    assert.equal(locationBonus(MULTI, target), true, target);
  }
  assert.equal(locationBonus(MULTI, "杭州"), false);
  assert.equal(locationBonus(MULTI, "Hangzhou"), false);
});

test("打分的城市 +20：单城市地点的判定与改前相同", () => {
  assert.equal(locationBonus("上海", "Shanghai"), true);
  assert.equal(locationBonus("Shanghai, China", "上海"), true);
  assert.equal(locationBonus("上海", "北京"), false);
  assert.equal(locationBonus("未知园区-α", "未知园区-β"), false);
  // 城市群目标维持改前口径（只认字面），这次不动它。
  assert.equal(locationBonus("上海", "长三角"), false);
});

// 折错城市的纠正（2026-10-12，crawler/normalizer.clean_location）：「黑龙江省·牡丹江市·西安区」此前入库成「西安」，
// 现在是「牡丹江市」。读侧每条路径都得认它真正所在的城市，且不再认西安。
test("折错纠正后的写法：每条读路径都认真正所在的城市，不再认折错的那个", () => {
  const loc = "牡丹江市";
  for (const city of ["牡丹江", "牡丹江市", "黑龙江", "黑龙江省"]) {
    assert.ok(matchLocationTargets(loc, [city]), `/today ${city}`);
    assert.equal(locationMatchesCityFilter(loc, [city]), true, `/jobs ${city}`);
    assert.ok(ftsHits(loc, cityFtsTerms([city])), `/jobs 全文 ${city}`);
    assert.ok(ftsHits(loc, locationTargetSqlTerms(city)), `/today 召回 ${city}`);
    assert.ok(citySqlLikeTokens([city]).some((t) => loc.toLowerCase().includes(t.toLowerCase())), `ilike ${city}`);
    assert.equal(locationBonus(loc, city), true, `打分 ${city}`);
  }
  for (const city of ["西安", "西安市", "陕西", "Xi'an"]) {
    assert.equal(matchLocationTargets(loc, [city]), null, `/today ${city}`);
    assert.equal(locationMatchesCityFilter(loc, [city]), false, `/jobs ${city}`);
    assert.equal(ftsHits(loc, cityFtsTerms([city])), false, `/jobs 全文 ${city}`);
    assert.equal(locationBonus(loc, city), false, `打分 ${city}`);
  }
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs: [{ title: "2027届校园招聘-销售", city: loc }] }]);
  assert.deepEqual(options.cityOptions, ["牡丹江"]);
  const pick = (city) => selectFacetIndexes({ city, education: "", jobFunction: "", gradClass: null }, options);
  assert.equal(countMatchingFacets(byPattern.get("%x%"), pick("牡丹江")), 1);
  assert.equal(countMatchingFacets(byPattern.get("%x%"), pick("西安")), 0);
});

// 拼音别名按整词认之后，「Changzhou, Jiangsu, China」不再入库成「杭州」，而是原样入库。
// 今日推荐的两条路径（城市门 + 召回）和岗位库的全文候选门按整词 / 中文匹配，不会再把它当成杭州。
// ⚠️ 岗位库城市筛选的 JS 判定、location ilike、打分 +20、校招看板分面是按拼音子串比的（hangzhou ⊂ changzhou），
//    对这类行仍会认成杭州——读侧的既有缺口，这里不钉。
test("拼音地点原样入库后：今日推荐与全文候选门不再把常州认成杭州", () => {
  const loc = "Changzhou, Jiangsu, China";
  for (const city of ["杭州", "杭州市", "浙江", "Hangzhou"]) {
    assert.equal(matchLocationTargets(loc, [city]), null, `/today ${city}`);
    assert.equal(ftsHits(loc, locationTargetSqlTerms(city)), false, `/today 召回 ${city}`);
    assert.equal(ftsHits(loc, cityFtsTerms([city])), false, `/jobs 全文 ${city}`);
  }
});

// 必投看板的城市筛选是分面计数（lib/campus-facets），不走上面那几个判定：一个岗一个城市下标、按相等比。
// 多城市岗如果当成「北京/上海」这一个取值，选「北京」就筛不到它，下拉里还会多出一堆组合项。
test("校招必投看板：多城市岗算进它列的每个城市，下拉里只有单个城市", () => {
  assert.equal(normalizeCampusCity(MULTI), MULTI);
  const jobs = [
    { title: "2027届校园招聘-产品经理", city: "北京/上海" },
    { title: "2027届校园招聘-产品经理", city: "上海" },
    { title: "2027届校园招聘-产品经理", city: "石家庄市/上海/阿坝藏族羌族自治州" },
    { title: "2027届校园招聘-产品经理", city: "" }, // 没写城市：任何城市筛选下都放行
  ];
  const { options, byPattern } = buildCampusFacets([{ pattern: "%x%", jobs }]);
  assert.deepEqual(options.cityOptions, ["上海", "北京", "石家庄", "阿坝"]);
  const rows = jobs.map((job) => ({ ...job, fn: campusFacetKey(job).fn }));
  for (const [city, want] of [["上海", 4], ["北京", 2], ["石家庄", 2], ["阿坝", 2], ["", 4], ["杭州", 0]]) {
    const filters = { city, education: "", jobFunction: "", gradClass: null };
    const selected = selectFacetIndexes(filters, options);
    assert.equal(countMatchingFacets(byPattern.get("%x%"), selected), want, `卡面计数 ${city}`);
    const expanded = city === "杭州" ? 0 : rows.filter((row) => campusRowMatches(row, filters)).length;
    assert.equal(expanded, want, `展开列表 ${city}`);
  }
  // 「对你有货」用的是同一套城市下标
  const fit = selectFitIndexes([], ["北京"], options);
  const fitCount = (byPattern.get("%x%") || []).reduce((n, f) => n + (facetMatchesFit(f, fit) ? f[4] : 0), 0);
  assert.equal(fitCount, 2);
});

test("校招必投看板：上线那一小段缓存里是旧形状的选项表（没有 cityKeys），照样筛得对", () => {
  const options = { cityOptions: ["上海", "北京/上海"], educationOptions: [], functionOptions: [], gradClassOptions: [] };
  const facets = [[0, -1, -1, null, 2], [1, -1, -1, null, 3]];
  const pick = (city) => selectFacetIndexes({ city, education: "", jobFunction: "", gradClass: null }, options);
  assert.equal(countMatchingFacets(facets, pick("上海")), 5);
  assert.equal(countMatchingFacets(facets, pick("北京")), 3);
  assert.equal(countMatchingFacets(facets, pick("杭州")), 0);
});
