// 公告制招聘（/programs）入口的取数层。表极小（2026-09-07 实测 18 行、15 行 enabled，
// 长期也就几十行），跨实例缓存 10 分钟。
import { unstable_cache } from "next/cache";
import { createServiceClient } from "./supabaseService";
import { toApplyPrograms, type ApplyProgram } from "./apply-programs";

// ⚠️ 缓存函数体内不得读 cookies()/headers()（unstable_cache 限制）；
// 这份数据不含任何用户私有信息，所以能安全地跨请求共享。
export const getApplyPrograms = unstable_cache(
  async (): Promise<ApplyProgram[]> => {
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .from("apply_programs")
      .select("id, company, program_name, program_type, entry_url, description, window_text, industry, verified_at, enabled")
      .eq("enabled", true)
      .not("verified_at", "is", null)
      .order("program_type", { ascending: true })
      .order("company", { ascending: true });
    if (error) {
      // 不吞错：入口页空着比报错更难查。记录后返回空，页面走空状态。
      console.error("[apply-programs] 取数失败:", error.message);
      return [];
    }
    return toApplyPrograms(data);
  },
  ["apply-programs-v1"],
  { revalidate: 600 },
);
