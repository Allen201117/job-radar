// 必投清单的「独占归属」：库里的一个公司名只归清单里的一家。
//
// ⚠️ 与 crawler/gap_census.py 的 build_owner_index / resolve_owner 是**同一份规则**，
// 两端靠共用夹具 tests/fixtures/must-apply-owner-cases.json 对齐；改这里必须同改爬虫侧。
//
// 为什么要它（2026-10-11 全集实测，1,725 个在招公司名 × 国内 311 + 海外 327 条清单）：
// 同一份清单曾有三套匹配口径，数字互相对不上——
//   ❌ 管理员看板：裸子串（lib/ilike-matcher），一个名字命中两条清单就各算一遍。
//      海外 ABB 显示 6,600 个健康岗、实际 4 个（其余是 AbbVie、雅培 Abbott）；国内京东里混着京东方 1,032 个。
//   ❌ 校招专区：用户所选行业的清单里谁排前面归谁。只选互联网时，京东方的校招岗归到「京东」卡。
//   ✅ 缺口台账（9-17 起）：最长的模式独占 + 英文按整词。现在三处都用这一套。
// 规则：
//   · 中文模式按子串，英文模式按整词（`%ABB%` 不命中 AbbVie）；
//   · 一个名字命中多条清单时，最长的模式胜出（京东方 BOE 归 `%京东方%`，不归 `%京东%`）；
//     同长再比清单名长度，再比模式在名字里出现的位置靠后者；
//   · 清单点名排除的名字（`excludes`）不归这家，但还可以归给别的清单公司。
import { mustApplyByIndustry, mustApplyPatterns, type MustApplyCompany, type MustApplyScope } from "./must-apply-list";

type NameTest = (lowName: string) => boolean;
type OwnerToken = { low: string; length: number; owner: string; ownerLength: number; hits: NameTest };
type OwnerIndex = { tokens: OwnerToken[]; excludes: Map<string, NameTest[]> };

const ASCII_TOKEN_RE = /^[a-z0-9&.'\-\s]+$/;
const codePoints = (s: string) => Array.from(s).length;
const stripWildcards = (pattern: string) => pattern.replace(/%/g, "").trim();

function wholeWordRe(lowToken: string): RegExp {
  return new RegExp(`(?<![a-z0-9])${lowToken.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![a-z0-9])`);
}

/** 清单模式（去掉 `%`、小写）→ 「它是否出现在库里的名字（小写）里」：中文按子串，英文按整词。 */
function nameTest(lowToken: string): NameTest {
  if (!ASCII_TOKEN_RE.test(lowToken)) return (lowName) => lowName.includes(lowToken);
  const re = wholeWordRe(lowToken);
  return (lowName) => re.test(lowName);
}

export function tokenInName(lowToken: string, lowName: string): boolean {
  return nameTest(lowToken)(lowName);
}

/** 同一家公司出现在多个行业里时并成一条（与爬虫侧 load_companies 同序同口径：先出现的定名字和模式）。 */
function mergeByName(entries: MustApplyCompany[]): MustApplyCompany[] {
  const merged = new Map<string, MustApplyCompany>();
  for (const entry of entries) {
    const name = String(entry?.name ?? "").trim();
    const pattern = String(entry?.pattern ?? "").trim();
    if (!name || !pattern) continue;
    let row = merged.get(name);
    if (!row) merged.set(name, (row = { name, pattern }));
    if (entry.aliases?.length) row.aliases = entry.aliases;
    if (entry.excludes?.length) row.excludes = entry.excludes;
  }
  return Array.from(merged.values());
}

function buildOwnerIndex(companies: MustApplyCompany[]): OwnerIndex {
  const tokens: OwnerToken[] = [];
  const excludes = new Map<string, NameTest[]>();
  const seen = new Set<string>();
  for (const company of companies) {
    const owner = company.name;
    for (const pattern of mustApplyPatterns(company)) {
      const low = stripWildcards(pattern).toLowerCase();
      if (!low || seen.has(low)) continue;
      seen.add(low);
      tokens.push({ low, length: codePoints(low), owner, ownerLength: codePoints(owner), hits: nameTest(low) });
    }
    const excluded = (company.excludes || []).map((p) => stripWildcards(String(p)).toLowerCase()).filter(Boolean);
    if (excluded.length) excludes.set(owner, excluded.map(nameTest));
  }
  return { tokens, excludes };
}

function resolveOwner(company: string, index: OwnerIndex): string {
  const low = company.toLowerCase();
  if (!low) return "";
  const trimmed = low.trim();
  let best: OwnerToken | null = null;
  let bestAt = -1;
  for (const token of index.tokens) {
    if (!token.hits(low)) continue;
    const excluded = index.excludes.get(token.owner);
    if (excluded && trimmed && excluded.some((hit) => hit(trimmed))) continue;
    const at = low.lastIndexOf(token.low);
    if (
      !best ||
      token.length > best.length ||
      (token.length === best.length &&
        (token.ownerLength > best.ownerLength || (token.ownerLength === best.ownerLength && at > bestAt)))
    ) {
      best = token;
      bestAt = at;
    }
  }
  return best ? best.owner : "";
}

function scopeCompanies(scope: MustApplyScope): MustApplyCompany[] {
  return mergeByName(Object.values(mustApplyByIndustry(scope)).flat());
}

const canonicalCache = new Map<MustApplyScope, { byName: Map<string, MustApplyCompany>; resolve: (company: string) => string }>();

function memoResolver(index: OwnerIndex): (company: string) => string {
  const memo = new Map<string, string>();
  return (company) => {
    const key = String(company ?? "");
    let owner = memo.get(key);
    if (owner === undefined) memo.set(key, (owner = resolveOwner(key, index)));
    return owner;
  };
}

function canonical(scope: MustApplyScope) {
  let hit = canonicalCache.get(scope);
  if (!hit) {
    const companies = scopeCompanies(scope);
    hit = {
      byName: new Map(companies.map((c) => [c.name, c])),
      resolve: memoResolver(buildOwnerIndex(companies)),
    };
    canonicalCache.set(scope, hit);
  }
  return hit;
}

/**
 * 库里的公司名 → `list` 里的哪一条（归到清单里的别家、或不归任何一家 → null）。
 * 校招专区的卡面计数 / 新鲜度 / 抽屉 / 源覆盖 / 开闸徽章都用它，保证几处归到同一家。校招专区只有国内清单。
 */
export function mustApplyOwnerPicker<T extends { name: string; pattern: string }>(
  list: T[],
): (company: unknown) => T | null {
  const ownerOf = mustApplyOwnerResolver("domestic", list);
  const byName = new Map(list.map((c) => [c.name, c]));
  return (company) => byName.get(ownerOf(String(company ?? ""))) ?? null;
}

/**
 * 公司名 → 它归属的清单规范名（不归任何一家返回 ""）。归属永远对**该范围的全量清单**判：
 * 调用方只关心其中几家（用户选的行业 / 互联网清单）时，别家照样在场竞争，否则「京东方」又会回流到京东。
 *
 * `list` 给的是调用方手里的条目。全是真实清单里的条目（线上的所有调用）→ 直接用全量清单的索引；
 * 里面有真实清单没有的条目（测试 / 临时清单）→ 这些条目排在前面参与归属，真实清单的其余公司仍然在场。
 */
export function mustApplyOwnerResolver(
  scope: MustApplyScope,
  list?: MustApplyCompany[],
): (company: string) => string {
  const base = canonical(scope);
  if (!list || list.every((c) => base.byName.get(c.name)?.pattern === c.pattern)) return base.resolve;
  const given = mergeByName(list);
  const names = new Set(given.map((c) => c.name));
  const rest = Array.from(base.byName.values()).filter((c) => !names.has(c.name));
  return memoResolver(buildOwnerIndex([...given, ...rest]));
}
