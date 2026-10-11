// 建公司画像的唯一入口（网站侧）。爬虫侧同口径：crawler/company_profile_resolve.py。
//
// ❌ 2026-10-11 全库对拍：136 家公司各有 2~5 个画像。每个入口都写 `upsert({ company }, { onConflict: "company" })`，
//    去重键只有正名，别名列从不参与——源叫「知乎 Zhihu」、画像叫「知乎」，就再建一个。
// ✅ 建之前先按「正名 → 别名 → 归一名唯一」找（lib/insight-profile-resolve），找不到才建。
//    加源、后台录入洞察都走这里；抽屉现查早先已改成用画像规范名（app/api/insights/route.ts）。

import { fetchAllPages, type PaginatableClient } from "@/lib/supabase-paginate";
import {
  buildProfileNameIndex,
  resolveProfileByName,
  type ProfileNameRow,
} from "@/lib/insight-profile-resolve";

/**
 * 这个名字归哪个画像；不归任何画像返回 null。
 * 每次现读全表（两页轻列），不走 10 分钟的画像缓存：写路径上读到旧表，会把刚并掉的名字又建出来。
 */
export async function findProfileByAnyName(
  service: PaginatableClient,
  name: string,
): Promise<ProfileNameRow | null> {
  const profiles = await fetchAllPages<ProfileNameRow>((from, to) =>
    service
      .from("company_profiles")
      .select("id, company, aliases")
      .order("id", { ascending: true })
      .range(from, to),
  );
  return resolveProfileByName(buildProfileNameIndex(profiles), name);
}

/**
 * 取这家公司的画像，没有才新建。patch 里的列在两种情况下都会写。
 * ⚠️ 返回的 company 可能不是传进来的 name（name 是别名时）。出错直接抛，由调用方决定要不要阻断。
 */
export async function ensureCompanyProfile(
  service: PaginatableClient,
  name: string,
  patch: Record<string, unknown> = {},
): Promise<{ id: string; company: string; created: boolean }> {
  const company = String(name || "").trim();
  if (!company) throw new Error("company_required");

  const existing = await findProfileByAnyName(service, company);
  if (existing) {
    if (Object.keys(patch).length > 0) {
      const { error } = await service.from("company_profiles").update(patch).eq("id", existing.id);
      if (error) throw new Error(error.message);
    }
    return { id: existing.id, company: existing.company, created: false };
  }

  const { data, error } = await service
    .from("company_profiles")
    .upsert({ company, ...patch }, { onConflict: "company" })
    .select("id, company")
    .single();
  if (error) throw new Error(error.message);
  if (!data?.id) throw new Error("profile_upsert_empty");
  return { id: data.id, company: data.company, created: true };
}
