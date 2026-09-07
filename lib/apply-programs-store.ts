// 公告制招聘（/programs）入口的取数层。表极小（2026-09-07 实测 18 行、15 行 enabled，
// 长期也就几十行），跨实例缓存 10 分钟。
import { unstable_cache } from "next/cache";
import { createServiceClient } from "./supabaseService";
import { needsDeeperAnnouncementLink, toApplyPrograms, type ApplyProgram } from "./apply-programs";

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
    const programs = toApplyPrograms(data);
    // 公告制入口停在门户首页 = 用户点开看不到公告（见 needsDeeperAnnouncementLink 的注释）。
    // 不丢行（丢了连门户都进不去），但必须出声——上一版正是安静地这样上线了 6 条。
    const shallow = programs.filter(needsDeeperAnnouncementLink).map((p) => p.company);
    if (shallow.length > 0) {
      console.warn(
        `[apply-programs] 这些公告制入口只指到门户首页，点开看不到公告，需要补更深的公告页：${shallow.join("、")}`,
      );
    }
    return programs;
  },
  ["apply-programs-v1"],
  { revalidate: 600 },
);
