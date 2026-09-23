// 画像卫生（2026-09-17 立）：**脏画像进不来、已进来的能被发现**。
//
// 为什么要有这一层：2026-09-17 的体验走查里 44 个真实用户有 7 个推荐页 0 岗，
// 根因之一不是检索也不是供给，而是**画像本身是脏的**——
//   target_roles 里躺着「英文相关」「技术岗位」「项目专员/助理」「办公室文员」「销售；采购」，
//   target_locations 里躺着「杭州 深圳 无锡 宁波」这种一格塞四个城市的写法，
//   job_scope 是 overseas 但目标城市全在国内、也没有英文简历。
// 这些值同时来自两条路（简历解析 LLM + 偏好页手填），所以归一必须放在**两条路共同的落库口**上：
//   · 手填 → lib/opportunities/preferences-input.parsePreferencesInput
//   · 简历 → lib/resume-extract.normalizeResumeProfile
// 本文件只放纯函数（单测不打网络、不连库），归一与体检共用同一份判据——
// 判据两端漂了，体检报出来的数字就会和线上实际行为对不上。
//
// 🚫 一条红线：**这里只归一、只报数，绝不丢用户的值**。认不出的写法一律原样保留
// （宁可漏判，不可错杀：把「马来西亚」当成不认识的城市删掉，用户就再也搜不到了）。
const {
  CITY_ALIASES,
  CHINA_CITY_REGION_EXPANSIONS,
  classifyJobFunction,
  normalizeRolePhrases,
} = require("./china-keyword-expansion");
const { INDUSTRY_CATEGORIES, canonicalizeUserIndustry } = require("./company-industry");

// 与 normalizeRolePhrases 同口径的硬分隔符；城市侧额外允许「纯中文 + 空格」拆分
//（"杭州 深圳 无锡 宁波"），但含拉丁字母的写法不拆（"new york" / "Hong Kong"）。
const HARD_SEPARATOR_RE = /[/／|｜、，,；;]/;
const HAS_LATIN_RE = /[A-Za-z0-9]/;
const INDUSTRY_CATEGORY_SET = new Set(INDUSTRY_CATEGORIES);
/** 证书 / 等级考试写法：它们是资质不是岗位词，进 target_keywords 只会把召回压死。只报数，不删。 */
const CERTIFICATE_RE = /(证书|资格证|等级考试|计算机[一二三四]级|CET-?[46]|TEM-?[48]|普通话.*[甲乙]|雅思|托福|IELTS|TOEFL|CPA|CFA|FRM)/i;

function splitCityCandidates(value) {
  const out = [];
  for (const chunk of String(value || "").split(HARD_SEPARATOR_RE)) {
    const piece = chunk.trim();
    if (!piece) continue;
    const spaced = piece.split(/\s+/);
    const useSpace =
      spaced.length > 1 && !HAS_LATIN_RE.test(piece) && spaced.every((s) => s.length >= 2);
    for (const seg of useSpace ? spaced : [piece]) if (seg) out.push(seg);
  }
  return out;
}

/**
 * 城市写法的识别档位：
 *   "city"    —— CITY_ALIASES 登记过的规范城市（含拼音/英文别名），可安全归一成规范名；
 *   "region"  —— 省 / 城市群（"广东" "长三角"）。/today 把省按全省地级市解析（lib/opportunities/location-targets），
 *                /jobs 仍由 expandChinaCityTargets 展开成主城市；
 *   "unknown" —— 两张表都不认。**不代表它坏**：库里 location 常写「浙江省宁波市」，
 *                裸「宁波」做子串照样命中。真正坏的是「一格多值」，那个由 normalizeCityPhrases 拆掉。
 */
function cityRecognition(value) {
  const raw = String(value || "").trim();
  if (!raw) return "unknown";
  const lower = raw.toLowerCase();
  if (CITY_ALIASES.has(raw) || CITY_ALIASES.has(lower)) return "city";
  if (CHINA_CITY_REGION_EXPANSIONS.has(raw) || CHINA_CITY_REGION_EXPANSIONS.has(lower)) return "region";
  return "unknown";
}

/** 拆多值 + 把认识的城市归一成规范名；认不出的原样保留。 */
function normalizeCityPhrases(locations) {
  const out = [];
  for (const raw of Array.isArray(locations) ? locations : [locations]) {
    for (const piece of splitCityCandidates(raw)) {
      const lower = piece.toLowerCase();
      const canonical =
        CITY_ALIASES.get(piece) || CITY_ALIASES.get(lower) || piece;
      if (!out.includes(canonical)) out.push(canonical);
    }
  }
  return out;
}

/**
 * 目标行业：认识的归一成权威类目（"互联网" → "互联网/科技"），认不出的**原样保留**。
 * 为什么不删：target_industries 是跨行业硬门，但 jobIndustryAllowed 只认权威类目、
 * 认不出的值它本来就当作「没填」放行——删掉不会让门更准，只会让用户看不见自己填过什么。
 */
function canonicalizeIndustryList(industries) {
  const out = [];
  const push = (v) => {
    if (v && !out.includes(v)) out.push(v);
  };
  for (const raw of Array.isArray(industries) ? industries : [industries]) {
    const whole = String(raw || "").trim();
    if (!whole) continue;
    // ⚠️ **先整条试，再拆**：权威类目本身就带斜杠（"制造/工业" "消费/零售" "互联网/科技"），
    // 无脑按分隔符拆会把合法类目劈成两半。整条认得出就直接用，认不出才当成「一格多填」去拆。
    if (INDUSTRY_CATEGORY_SET.has(whole)) {
      push(whole);
      continue;
    }
    // ⚠️ 只有「整条没有分隔符」时才允许整条归一。canonicalizeUserIndustry 内部是**子串正则**，
    // 拿整条去问会吞掉后半截：「互联网、金融」会被第一条规则认成互联网/科技，金融当场丢失。
    if (!HARD_SEPARATOR_RE.test(whole) && !/\s/.test(whole)) {
      push(canonicalizeUserIndustry(whole) || whole);
      continue;
    }
    for (const piece of splitCityCandidates(whole)) {
      push(canonicalizeUserIndustry(piece) || piece);
    }
  }
  return out;
}

const VALID_STAGES = new Set(["", "实习", "校招", "社招"]);

/**
 * 单份画像的只读体检。返回 issue code 列表 + 逐字段明细。
 * ⚠️ 判据必须与上面的归一函数同源：体检说「脏」的写法，归一必须真的能收拾它，否则报出来的数字没用。
 */
function auditProfile(input) {
  const prefs = input && input.preferences ? input.preferences : {};
  const cand = input && input.candidate ? input.candidate : null;
  const issues = [];
  const details = {};

  const roles = (prefs.target_roles || []).filter(Boolean);
  const normalizedRoles = normalizeRolePhrases(roles);
  const dirtyRoles = roles.filter((r) => {
    const one = normalizeRolePhrases([r]);
    return one.length !== 1 || one[0] !== r;
  });
  const unclassifiedRoles = normalizedRoles.filter((r) => {
    const fn = classifyJobFunction({ title: r });
    return !fn || fn === "其他";
  });
  details.roles = {
    count: roles.length,
    normalized: normalizedRoles,
    dirty: dirtyRoles,
    unclassified: unclassifiedRoles,
  };
  if (dirtyRoles.length) issues.push("role_dirty_phrase");
  // ⚠️ 「classifyJobFunction 判为其他」**不等于**用户填得脏，它是两件事混在一起，自动分不开：
  //   ① 职能表缺口 —— 2026-09-17 全量 64 份画像里 32 个未分类方向，绝大多数是**合法且具体**的岗位名
  //      （有机合成研究员 / 实验员 / 资料员 / 招投标 / 外贸 / 电商 / 美工 / 网络安全 / IC 验证）；
  //   ② 真的笼统 —— 「英文」「技术」「整理资料」「数据驱动」「产品落地」这一类。
  // 所以这两个码**只作为体检信号**，不向用户弹提示（弹了就是在骂填得很具体的那批人）。
  if (roles.length && unclassifiedRoles.length === normalizedRoles.length) issues.push("role_all_unclassified");
  else if (unclassifiedRoles.length) issues.push("role_partly_unclassified");
  if (!roles.length) issues.push("role_empty");

  const keywords = (prefs.target_keywords || []).filter(Boolean);
  const certKeywords = keywords.filter((k) => CERTIFICATE_RE.test(k));
  details.keywords = { count: keywords.length, certificates: certKeywords };
  if (certKeywords.length) issues.push("keyword_certificate");

  const locations = (prefs.target_locations || []).filter(Boolean);
  const normalizedCities = normalizeCityPhrases(locations);
  const multiValueCities = locations.filter((l) => normalizeCityPhrases([l]).length > 1);
  const unknownCities = normalizedCities.filter((c) => cityRecognition(c) === "unknown");
  const regionCities = normalizedCities.filter((c) => cityRecognition(c) === "region");
  details.locations = {
    count: locations.length,
    normalized: normalizedCities,
    multiValue: multiValueCities,
    unknown: unknownCities,
    region: regionCities,
  };
  if (multiValueCities.length) issues.push("location_multi_value");
  // ⚠️ 同上，这个码是**我们的别名表缺口**，不是用户写错：2026-09-17 全量体检里 17 个「不认识的城市」
  // 全是真实地级市（无锡 / 合肥 / 宁波 / 东莞 / 惠州 / 连云港 / 泰州 / 绍兴 …），只是没登记进 CITY_ALIASES。
  // 它们做子串仍能命中岗位 location（库里常写「浙江省宁波市」），所以不向用户弹提示，只报给我们自己看。
  if (unknownCities.length) issues.push("location_unregistered_city");
  if (!locations.length) issues.push("location_empty");

  const industries = (prefs.target_industries || []).filter(Boolean);
  const unrecognizedIndustries = industries.filter(
    (i) => !INDUSTRY_CATEGORY_SET.has(i) && !canonicalizeUserIndustry(i),
  );
  details.industries = { count: industries.length, unrecognized: unrecognizedIndustries };
  // 认不出的行业 = 跨行业门对它完全无效（jobIndustryAllowed 只认权威类目）。
  // 用户以为自己设了行业门，其实没设——这是「静默不生效」，必须报出来。
  if (unrecognizedIndustries.length) issues.push("industry_unrecognized");

  const stage = prefs.experience_stage == null ? "" : String(prefs.experience_stage).trim();
  const candStage = cand && cand.experience_stage != null ? String(cand.experience_stage).trim() : "";
  details.stage = { preference: stage, candidate: candStage };
  if (!VALID_STAGES.has(stage)) issues.push("stage_invalid");
  if (stage && candStage && stage !== candStage) issues.push("stage_conflict");

  const scope = prefs.job_scope || "domestic";
  const hasEnResume = Boolean(prefs.has_en_resume || (cand && cand.has_en_resume));
  const allDomesticCities =
    normalizedCities.length > 0 && normalizedCities.every((c) => cityRecognition(c) !== "unknown");
  details.scope = { job_scope: scope, has_en_resume: hasEnResume, all_domestic_cities: allDomesticCities };
  // 「顶栏点了海外 + 目标城市全在国内 + 没有英文简历」三条同时成立 = 海外池必然 0 岗，
  // 而页面只会空着不说为什么（2026-09-17 走查：全库 8 人中招）。
  if (scope !== "domestic" && !hasEnResume && allDomesticCities) issues.push("scope_overseas_mismatch");

  return { issues, details };
}

// issue code → 给用户看的一句可操作提示（不是阻断，不替他改）。
// 🚫 **只有「能证明确实有问题」的码才配一句提示**：值被归一改动过（证据=改动本身）、
// 行业筛选静默不生效（证据=jobIndustryAllowed 只认权威类目）、海外三条件同时成立（证据=池子必然为空）。
// 「职能认不出」「城市没登记」是我们自己的词表缺口，配提示就是把锅甩给用户，故意不给。
const HYGIENE_HINTS = Object.freeze({
  role_dirty_phrase:
    "有的岗位方向写在一格里（如「项目专员/助理」「销售；采购」），保存时已按「或」拆开；想更准可以自己分成两个标签。",
  location_multi_value: "有的城市写在一格里，保存时已拆成多个城市标签。",
  industry_unrecognized:
    "有的目标行业不在系统的行业类目里，这条行业筛选不会生效——换成「互联网/科技」「金融」这类类目才会过滤。",
  keyword_certificate:
    "补充搜索词里有证书/等级考试（如 CET-6），岗位标题极少写这些，建议换成岗位方向词。",
  scope_overseas_mismatch:
    "求职范围选了海外，但目标城市都在国内、也还没传英文简历——海外岗会很少甚至为 0。要么把范围切回国内，要么补上英文简历和海外城市。",
  stage_conflict: "偏好里的求职阶段和简历解析出的阶段不一致，以偏好为准；确认一下哪个是你想要的。",
});

/** 给前端用：返回按严重度排好的提示（最多 n 条，默认 3）。纯函数，不读 DOM、不发请求。 */
function profileHygieneHints(input, max = 3) {
  const { issues } = auditProfile(input);
  const order = [
    "scope_overseas_mismatch",
    "industry_unrecognized",
    "keyword_certificate",
    "role_dirty_phrase",
    "location_multi_value",
    "stage_conflict",
  ];
  return order
    .filter((code) => issues.includes(code) && HYGIENE_HINTS[code])
    .slice(0, max)
    .map((code) => ({ code, text: HYGIENE_HINTS[code] }));
}

module.exports = {
  HYGIENE_HINTS,
  auditProfile,
  canonicalizeIndustryList,
  cityRecognition,
  normalizeCityPhrases,
  profileHygieneHints,
};
