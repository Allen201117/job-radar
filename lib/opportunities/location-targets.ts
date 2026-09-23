// /today 的目标城市怎么匹配岗位 location（2026-09-23 立）。
//
// stage-1 召回 SQL 的城市门（lib/jobs-store/opportunities.buildRecallSql）与 stage-2 的 locationState
// （./eligibility）必须读**同一份**展开：SQL 取回而 JS 判不中 = 白占召回名额；JS 判得中而 SQL 根本不取 = 永远看不到。
// 此前两边都是「目标原词 + normalizeChinaCity」的子串匹配：填「陕西」只认 location 里字面写着「陕西」的岗，
// 「西安」「榆林市-神木市」一律 location_mismatch（硬拒）。
//
// 三类目标，行为各不相同：
//   · 省 / 自治区（陕西、广东、广西壮族自治区）→ 按 lib/geo.locationProvinces 解析岗位落在哪个省，全省地级市都算；
//   · 城市群（珠三角 / 长三角 / 京津冀）→ 按 expandChinaCityTargets 已有的定义展开成城市，再逐个子串匹配；
//   · 城市 / 直辖市 / 其它（深圳、北京、新加坡）→ 与改前逐字相同：原词或规范名出现在 location 里。
import { CN_PROVINCE_PREFECTURES, chinaProvincePlaceNames, locationProvinces } from "@/lib/cn-location-provinces";
import { expandChinaCityTargets, normalizeChinaCity } from "@/lib/china-keyword-expansion";

const PROVINCES = CN_PROVINCE_PREFECTURES as Record<string, string[]>;
const PROVINCE_SUFFIX_RE = /(?:省|壮族自治区|回族自治区|维吾尔自治区|自治区)$/;

export interface LocationTarget {
  raw: string;
  /** 目标是省级（直辖市除外）时的省短名，如「陕西」；否则 null。 */
  province: string | null;
  /** 非省目标的子串匹配词（原词 + 规范名 + 城市群展开）。 */
  cities: string[];
  /** 命中时给原因文案用的名字（「目标城市 陕西」）。 */
  label: string;
}

/** 「陕西」「陕西省」「广西壮族自治区」→ 省短名；城市、直辖市、城市群 → null。 */
export function provinceOfTarget(raw: string): string | null {
  const t = String(raw || "").trim();
  if (!t) return null;
  if (PROVINCES[t]) return t;
  const stripped = t.replace(PROVINCE_SUFFIX_RE, "");
  return stripped !== t && PROVINCES[stripped] ? stripped : null;
}

// 纯函数结果按原词缓存：locationState 每个岗位都会问一遍，而 normalizeChinaCity 要扫整张别名表。
const targetCache = new Map<string, LocationTarget>();

export function resolveLocationTarget(raw: string): LocationTarget {
  const t = String(raw || "").trim();
  const hit = targetCache.get(t);
  if (hit) return hit;
  const province = provinceOfTarget(t);
  let target: LocationTarget;
  if (province) {
    target = { raw: t, province, cities: [], label: province };
  } else {
    const cities: string[] = [];
    const expanded = expandChinaCityTargets(t) as string[];
    for (const c of [t, ...expanded.flatMap((x) => [x, normalizeChinaCity(x) as string])]) {
      if (c && !cities.includes(c)) cities.push(c);
    }
    target = { raw: t, province: null, cities, label: normalizeChinaCity(t) || t };
  }
  if (targetCache.size > 500) targetCache.clear();
  targetCache.set(t, target);
  return target;
}

/** 岗位 location 命中哪个目标（按用户填写顺序返回第一个命中的；都不中返回 null）。多个省目标时 location 只解析一次。 */
export function matchLocationTargets(
  location: string,
  targets: readonly string[],
): LocationTarget | null {
  let provinces: string[] | null = null;
  for (const raw of targets) {
    const target = resolveLocationTarget(raw);
    if (target.province) {
      provinces ??= locationProvinces(location) as string[];
      if (provinces.includes(target.province)) return target;
    } else if (target.cities.some((c) => location.includes(c))) {
      return target;
    }
  }
  return null;
}

/** 召回 SQL 城市门的检索词：必须是 matchLocationTargets 判中范围的超集（search_doc 含 location 的全部二元组）。 */
export function locationTargetSqlTerms(raw: string): string[] {
  const target = resolveLocationTarget(raw);
  return target.province ? (chinaProvincePlaceNames(target.province) as string[]) : target.cities;
}
