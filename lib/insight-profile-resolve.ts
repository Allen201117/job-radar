// 公司名 → 公司画像（纯函数）。建画像之前用它判「这家公司是不是已经有画像了」。
//
// 与 crawler/bu_extract.py 的 build_profile_index / resolve_profile 逐条同口径
// （共用夹具 tests/fixtures/profile-resolve-cases.json，两端各有一条测试读它）：
//   ① 正名完全相等 → ② 别名完全相等 → ③ 归一名（先去招聘渠道后缀，再走 lib/company-normalize）相等且全库只有一个画像是这个归一名。
// 正名优先于任何别名：A 的别名恰好是 B 的正名时，这个名字归 B。
//
// ⚠️ 它不是 lib/insight-match.ts 的归属门。那个门回答「这个岗位的抽屉该打开哪个画像」，允许有资格的子串命中
//    （「中国电建集团江西省水电工程局」→ 中国电建）；这里回答「要不要新建一个画像」，只认上面三步，
//    子公司不会因为名字里含集团名就被并进集团。

import { normalizeCompany } from "./company-normalize";

// 源名末尾的招聘渠道后缀（「云尖信息 校招」「TCL 实习」）是渠道，不是公司名的一部分。必须有空白隔开才算
// （「实习僧」不动）。与 crawler/bu_extract.py 的 _CHANNEL_SUFFIX_RE / profile_name_key 同口径。
// 刻意不折叠「中文 + 英文尾巴」：那样会把「沃尔沃 Volvo Cars」「沃尔沃 Volvo Group」这种同名不同公司的也并掉。
const CHANNEL_SUFFIX_RE = /\s+(?:校招|实习|社招)$/;

export function profileNameKey(name: string | null | undefined): string {
  return normalizeCompany(String(name || "").trim().replace(CHANNEL_SUFFIX_RE, ""));
}

export interface ProfileNameRow {
  id: string;
  company: string;
  aliases?: string[] | null;
}

export interface ProfileNameIndex<T extends ProfileNameRow> {
  exact: Map<string, T>;
  normalized: Map<string, T>;
}

/** profiles 的顺序有意义：两个画像登记了同一个别名时先出现的那个得（调用方按 id 排好再传）。 */
export function buildProfileNameIndex<T extends ProfileNameRow>(profiles: T[]): ProfileNameIndex<T> {
  const usable = (profiles || []).filter((p) => p && p.id && String(p.company || "").trim());
  const exact = new Map<string, T>();
  const byNormalized = new Map<string, T[]>();

  for (const profile of usable) {
    const company = String(profile.company).trim();
    if (!exact.has(company)) exact.set(company, profile);
  }
  for (const profile of usable) {
    const company = String(profile.company).trim();
    for (const value of [company, ...(profile.aliases || [])]) {
      const name = String(value || "").trim();
      if (!name) continue;
      if (name !== company && !exact.has(name)) exact.set(name, profile);
      const key = profileNameKey(name);
      if (!key) continue;
      const rows = byNormalized.get(key);
      if (rows) rows.push(profile);
      else byNormalized.set(key, [profile]);
    }
  }

  const normalized = new Map<string, T>();
  for (const [key, rows] of byNormalized) {
    if (new Set(rows.map((row) => row.id)).size === 1) normalized.set(key, rows[0]);
  }
  return { exact, normalized };
}

export function resolveProfileByName<T extends ProfileNameRow>(
  index: ProfileNameIndex<T>,
  name: string | null | undefined,
): T | null {
  const value = String(name || "").trim();
  if (!value) return null;
  return index.exact.get(value) || index.normalized.get(profileNameKey(value)) || null;
}
