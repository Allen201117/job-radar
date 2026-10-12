// ============================================================
// 模块 B — 公司匹配（纯函数）
// 把 jobs.company 的自由写法（苹果 / Apple、字节 / 字节跳动 / ByteDance、
// 微软（中国）/ Microsoft）对齐到 company_profiles 的画像（company + aliases）。
// ============================================================

import type { CompanyProfile } from "./types";
import { CHINA_CJK_PLACE_MARKERS } from "./geo";
import distinctCompanies from "./insight-distinct-companies.json";

// 归一化：小写、去空白与常见公司后缀/地域装饰，便于宽松比对
const STRIP_PATTERNS: RegExp[] = [
  /（中国）|\(china\)|（大中华区）|中国区|大中华区/gi,
  /有限公司|股份有限公司|科技有限公司|集团|公司|股份|控股/g,
  /\b(inc|ltd|llc|co|corp|corporation|company|technologies|technology|holdings|group)\b/gi,
  /[\s.,，。、_\-—·&'"’]/g,
];

export function normalizeCompany(input: string | null | undefined): string {
  if (!input) return "";
  let s = String(input).toLowerCase().trim();
  for (const re of STRIP_PATTERNS) {
    s = s.replace(re, "");
  }
  return s;
}

function hasCJK(s: string): boolean {
  return /[一-鿿]/.test(s);
}

// ── 中文名子串命中的资格门（2026-09-17 立，全集对拍 1,383 画像 × 1,537 家在招公司名后定的规则）──
// 旧判据「含汉字就许子串命中」把「京东方」算进京东、「中国银行业协会」算进中国银行、「腾讯音乐」算进腾讯。
// 但库里公司名的写法也真实存在这几种「同一家」：
//   · 画像名带招聘活动/拼音后缀：「云南白药 YNBY 校招」「地平线 Horizon Robotics 实习」；
//   · 子公司名末尾括号标集团：「北京奔驰汽车有限公司（北汽集团）」「中铁十七局集团有限公司（中国铁建）」；
//   · 央企子公司 = 集团名 + 地区 + 组织单元：「中国电建集团江西省水电工程局有限公司」「中国电建集团北京勘测设计研究院」；
//   · 品牌括号：「好未来（学而思）」。
// 所以规则不是「多出的部分必须全是装饰词」，而是三层：
//   ⓪ 括号外的主体就是短名本身 → 命中（括号只是品牌注记：「好未来（学而思）」）。
//   ① 末尾括号里写的就是集团名 → 命中；括号里写的是**另一个**集团名 → 直接不命中（数据自己声明了归属，
//      「中国建筑科学研究院有限公司…（中国建研院）」不是中国建筑）。
//   ② 括号外的主体去掉短名后，剩下的全是装饰（拼音/字母、科技/集团/分公司…、地名、校招/实习）→ 命中。
//   ③ 剩下的含「地名 + 组织单元词（局/院/所/中心/分行/厂…）」→ 央企子公司写法，命中。
//   其余（京东**方** / 腾讯**音乐** / 网易**有道** / 东软**医疗** / 中国银行**业协会**）一律不命中。
//   子公司要归到集团画像的其它写法，靠 company_profiles.aliases 显式登记，不靠子串猜——归属准确性高于一切。
const COMPANY_UNIT_TOKENS = [
  "股份有限公司", "有限责任公司", "有限公司", "科技", "技术", "网络", "信息", "软件", "互联网", "计算机系统",
  "计算机", "系统", "电子", "实业", "国际", "投资", "发展", "产业", "贸易", "商业", "控股", "集团", "股份", "公司",
  "中国区", "大中华区", "中国", "总部", "事业部", "事业群", "分公司", "子公司", "分行", "支行", "研发中心", "技术中心",
  "校招", "校园招聘", "社招", "实习", "招聘",
  // 品牌 + 行业描述词 = 同一家（全集对拍里真实存在：大疆创新 / 滴滴出行 / 申通快递 / 斗鱼直播 / 极兔速递 / 万科企业 /
  // 蒙牛乳业 / 贝壳找房 / 深圳前海微众银行）。⚠️ 刻意不收「物流 / 音乐 / 云 / 金融 / 证券 / 汽车」——
  // 京东物流 / 腾讯音乐 / 阿里云 / 中信证券 是独立法人，要归集团靠 aliases。
  // 📌 2026-10-11 移出「饮料」：当初收它的依据是「东鹏饮料 = 东鹏」，而那条源抓的其实是东鹏控股（瓷砖卫浴）。
  //    全集回放：移出后只拆开「东鹏 / 东鹏饮料」这一对，其余 1,725 个在招公司名的归属一个没变。
  "创新", "出行", "快递", "速递", "直播", "企业", "乳业", "找房", "前海",
  // normalizeCompany 会把「公司」从串**中间**剥掉，「分公司 / 子公司 / 有限责任公司」因此剩下残尾，这里一并认。
  "有限责任", "有限", "分", "子",
];
const PLACE_SUFFIX_TOKENS = ["特别行政区", "自治区", "自治州", "省", "市", "区", "县", "盟"];
const EXTRA_PLACE_TOKENS = ["北京", "上海", "天津", "重庆", "香港", "澳门", "深圳", "广州", "杭州", "南京", "成都", "武汉", "西安", "苏州"];
const PLACE_TOKENS: string[] = Array.from(new Set<string>([...EXTRA_PLACE_TOKENS, ...(CHINA_CJK_PLACE_MARKERS as string[])]));
// 长词优先，避免「有限公司」被先吃掉「公司」剩下「有限」。
const DECORATION_TOKENS: string[] = Array.from(
  new Set<string>([...COMPANY_UNIT_TOKENS, ...PLACE_SUFFIX_TOKENS, ...PLACE_TOKENS]),
).sort((a, b) => b.length - a.length);
// 组织单元词：央企/大集团子公司名里跟在「集团名 + 地区」后面的那类词。⚠️ 协会/学会/商会/基金会不算——它们是另一个法人。
const ORG_UNIT_RE = /局|院|所|中心|厂|基地|园区|支公司|分公司|分行|支行|事业部|部|处|站|矿|场|队|公司|集团/;
const NOT_A_COMPANY_RE = /协会|学会|商会|基金会|联合会|促进会|研究会/;
const DECORATION_PUNCT_RE = /[()（）\[\]【】《》\s·、,，.。\-—_/&]/g;
const TRAILING_PAREN_RE = /(?:（([^（）]+)）|\(([^()]+)\))$/;

// 剥掉所有装饰词/地名/拼音后还剩什么（左到右贪心，长词优先）。
function stripDecoration(text: string): string {
  let s = text.replace(DECORATION_PUNCT_RE, "").replace(/[a-z0-9]+/g, "");
  let guard = 0;
  while (s.length && guard++ < 64) {
    const tok = DECORATION_TOKENS.find((t) => s.startsWith(t));
    if (!tok) break;
    s = s.slice(tok.length);
  }
  return s;
}

function hasPlaceToken(text: string): boolean {
  return PLACE_TOKENS.some((p) => text.includes(p));
}

// 多出来的那一截能否被解释成「同一家的装饰」。
function remainderIsSameCompany(remainder: string): boolean {
  if (NOT_A_COMPANY_RE.test(remainder)) return false;
  const rest = stripDecoration(remainder);
  if (!rest.length) return true;
  // 央企子公司写法：地区 + 组织单元（「江西省水电工程局」「北京勘测设计研究院」）；光有「科学研究院」没有地区不算。
  return hasPlaceToken(remainder) && ORG_UNIT_RE.test(rest);
}

// 子串匹配的资格门。
//   · 拉丁短名：长度 >= 5 才许做「被包含方」，防「RED」「xhs」误命中「reddit」。
//   · 中文名：按文件头的三层规则。
function containedNameOk(short: string, long: string): boolean {
  if (!short) return false;
  if (!hasCJK(short)) return short.length >= 5;
  const paren = long.match(TRAILING_PAREN_RE);
  const parenBrand = paren ? (paren[1] || paren[2] || "").trim() : "";
  const main = paren ? long.slice(0, long.length - paren[0].length) : long;
  // 括号外的主体就是这家 → 括号只是品牌注记（「好未来（学而思）」），直接命中
  if (main === short) return true;
  if (parenBrand) {
    if (parenBrand === short) return true; // ① 括号里就是这家
    // 括号写的是另一个集团（不是纯地名、也不是短名的装饰变体）→ 数据自己声明了归属，不命中
    if (hasCJK(parenBrand) && !remainderIsSameCompany(parenBrand) && !parenBrand.includes(short)) return false;
  }
  const idx = main.indexOf(short);
  if (idx < 0) return false;
  const remainder = main.slice(0, idx) + main.slice(idx + short.length);
  // 短名自己带英文时，多出来的英文是另一个名字，不是拼音尾巴：「沃尔沃 Volvo」+「Cars」是沃尔沃汽车，
  // 不是沃尔沃集团（2026-10-11 全集回放：只拆开这一对，其余归属不变）。纯中文短名的英文尾巴照旧算装饰。
  if (/[a-z]/.test(short) && /[a-z]/.test(remainder)) return false;
  return remainderIsSameCompany(remainder); // ②③
}

// n、q 均为归一化后的非空串：全等，或「被包含方有资格」的子串命中
function nameMatches(n: string, q: string): boolean {
  if (n === q) return true;
  if (n.includes(q)) return containedNameOk(q, n);
  if (q.includes(n)) return containedNameOk(n, q);
  return false;
}

function profileRawNames(p: Pick<CompanyProfile, "company" | "aliases">): string[] {
  return [p.company, ...(p.aliases || [])].filter(Boolean) as string[];
}

function profileNames(p: Pick<CompanyProfile, "company" | "aliases">): string[] {
  return profileRawNames(p).map(normalizeCompany).filter(Boolean);
}

// ── 名字分不开、但确实是两家公司的（lib/insight-distinct-companies.json，2026-10-11 立）──
// 「大华集团」（上海，地产）与「浙江大华技术」（安防）去掉装饰词都只剩「大华」，上面的规则没有任何东西可以区分。
// 平时靠「两个画像都在 + 精确优先」各归各；哪天其中一个画像没了，它名下的岗会整批落到另一家头上。
// 名单按「含这个核心词的名字里，带哪个标记词的是哪一家」登记；两边的名字互不放行，判不出是哪一边的不拦。
type DistinctEntry = { core: string; sides: Array<{ label: string; markers: string[] }> };
const DISTINCT_ENTRIES = distinctCompanies as DistinctEntry[];

// 这个名字在某条登记里属于哪一边；不含核心词、或标记词指向不止一边 → -1（判不出）
function distinctSideOf(entry: DistinctEntry, raw: string): number {
  const low = raw.toLowerCase();
  if (!low.includes(entry.core)) return -1;
  let side = -1;
  for (let i = 0; i < entry.sides.length; i++) {
    if (!entry.sides[i].markers.some((m) => low.includes(m))) continue;
    if (side >= 0) return -1;
    side = i;
  }
  return side;
}

// query 在每条登记里属于哪一边；全都判不出（绝大多数名字）返回 null，调用方整段跳过。
function distinctSidesOf(query: string): number[] | null {
  const sides = DISTINCT_ENTRIES.map((entry) => distinctSideOf(entry, query));
  return sides.some((s) => s >= 0) ? sides : null;
}

function knownDistinct(profile: Pick<CompanyProfile, "company" | "aliases">, querySides: number[] | null): boolean {
  if (!querySides) return false;
  return DISTINCT_ENTRIES.some((entry, i) => {
    if (querySides[i] < 0) return false;
    const profileSides = profileRawNames(profile).map((n) => distinctSideOf(entry, n)).filter((s) => s >= 0);
    return profileSides.length > 0 && !profileSides.includes(querySides[i]);
  });
}

// query 是否命中某个画像的 company 或任一 alias
export function companyMatches(
  profile: Pick<CompanyProfile, "company" | "aliases">,
  query: string,
): boolean {
  const q = normalizeCompany(query);
  if (!q) return false;
  if (knownDistinct(profile, distinctSidesOf(query))) return false;
  return profileNames(profile).some((n) => nameMatches(n, q));
}

// ── 精确优先（2026-10-11 立）──
// companyMatches 是一对一的判断，不知道别的画像存在：「京东科技」自己有画像，照样被「京东」放行
// （「科技」是装饰词）。findCompanyProfile 有「全等优先」兜着；直接拿 companyMatches 逐个比的调用方没有——
// 校招专区的时间线就这么把京东的 2 条挂到了京东科技卡上。要回答「这个名字归不归这个画像」，用下面两个。

type ProfileKey = Pick<CompanyProfile, "id" | "company" | "aliases">;
export type ExactProfileIndex = Map<string, ProfileKey[]>;

/** 归一名 → 精确登记了它（正名或别名）的画像。 */
export function buildExactProfileIndex(profiles: ProfileKey[]): ExactProfileIndex {
  const index: ExactProfileIndex = new Map();
  for (const p of profiles) {
    for (const n of profileNames(p)) {
      const owners = index.get(n);
      if (!owners) index.set(n, [p]);
      else if (!owners.includes(p)) owners.push(p);
    }
  }
  return index;
}

/** 这个名字归不归这个画像：门放行，且名字没有被别的画像精确登记。 */
export function companyOwnsName(profile: ProfileKey, query: string, exactIndex: ExactProfileIndex): boolean {
  if (!companyMatches(profile, query)) return false;
  // 「大华股份」归一后是「大华」，精确登记它的是大华集团的画像——而名单说那是另一家，不能让它把名字占住。
  const querySides = distinctSidesOf(query);
  const owners = (exactIndex.get(normalizeCompany(query)) || []).filter((o) => !knownDistinct(o, querySides));
  return owners.length === 0 || owners.some((o) => o.id === profile.id);
}

/** 画像名下的在招岗数（按 companyOwnsName 归属）。 */
export function ownedJobCount(
  profile: ProfileKey,
  counts: Array<{ company: string; job_count: number }>,
  exactIndex: ExactProfileIndex,
): number {
  let sum = 0;
  for (const row of counts) {
    if (companyOwnsName(profile, row.company, exactIndex)) sum += row.job_count || 0;
  }
  return sum;
}

// 在画像列表中找最佳匹配：优先归一化全等，其次（有资格的）子串包含
export function findCompanyProfile(
  profiles: CompanyProfile[],
  query: string,
): CompanyProfile | null {
  const q = normalizeCompany(query);
  if (!q) return null;

  const querySides = distinctSidesOf(query);
  let substringHit: CompanyProfile | null = null;
  for (const p of profiles) {
    if (knownDistinct(p, querySides)) continue;
    const names = profileNames(p);
    if (names.some((n) => n === q)) return p; // 全等优先
    if (!substringHit && names.some((n) => nameMatches(n, q))) {
      substringHit = p;
    }
  }
  return substringHit;
}
