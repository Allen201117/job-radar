// 跨请求缓存：company_profiles 轻列 + activeJobCountsByCompany 聚合。
//
// 两者是 availability / career-path 接口里最重的共享读，且对所有用户一样（无用户私有数据）。
// ⚠️ unstable_cache 函数体内不能读 cookies()/headers()；supabase 客户端必须在函数内部用
//    service-role 新建（createServiceClient），不能从外部传入请求级客户端。

import { unstable_cache } from "next/cache";
import { createServiceClient } from "@/lib/supabaseService";
import { fetchAllPages } from "@/lib/supabase-paginate";
import { activeJobCountsByCompany, jobsStoreEnabled } from "@/lib/jobs-store/read";

/** company_profiles 轻列（供 findCompanyProfile / companyMatches / career-path 使用）。*/
export interface CompanyProfileLight {
  id: string;
  company: string;
  aliases: string[];
  display_name: string | null;
  headcount_band: string | null;
}

const REVALIDATE = 600; // 10 分钟

/**
 * 取全部 company_profiles 轻列（id / company / aliases / display_name / headcount_band），
 * 跨请求缓存 10 分钟。函数体内用 service-role client 新建。
 */
export const getCachedCompanyProfilesLight = unstable_cache(
  async (): Promise<CompanyProfileLight[]> => {
    const service = createServiceClient();
    return fetchAllPages<CompanyProfileLight>(
      (from, to) =>
        service
          .from("company_profiles")
          .select("id, company, aliases, display_name, headcount_band")
          .order("id", { ascending: true })
          .range(from, to),
    );
  },
  ["insight-company-profiles-light-v1"],
  { revalidate: REVALIDATE },
);

/**
 * 取 active 岗位按公司聚合计数，跨请求缓存 10 分钟。
 * 走 jobs-store（香港库）或 Supabase RPC，取决于环境配置。
 */
export const getCachedActiveJobCounts = unstable_cache(
  async (): Promise<Array<{ company: string; job_count: number }>> => {
    if (jobsStoreEnabled()) {
      return activeJobCountsByCompany();
    }
    // 无香港库配置时走 Supabase RPC
    const service = createServiceClient();
    const { data, error } = await service.rpc("active_job_counts_by_company");
    if (error) throw new Error(error.message);
    return (data || []) as Array<{ company: string; job_count: number }>;
  },
  ["insight-active-job-counts-v1"],
  { revalidate: REVALIDATE },
);
