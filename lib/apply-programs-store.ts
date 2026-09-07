// 公告制招聘（/programs）入口的取数层。表极小（2026-09-07 实测 18 行、15 行 enabled，
// 长期也就几十行），跨实例缓存 10 分钟。
import { unstable_cache } from "next/cache";
import { createServiceClient } from "./supabaseService";
import { needsDeeperAnnouncementLink, toApplyPrograms, type ApplyProgram } from "./apply-programs";

/** 缓存时长。这张表只由人工核实后改动，10 分钟滞后用户感知不到。 */
const TTL_SECONDS = 600;

// ⚠️ 缓存函数体内不得读 cookies()/headers()（unstable_cache 限制）；
// 这份数据不含任何用户私有信息，所以能安全地跨请求共享。
const getCached = unstable_cache(
  async (_bucket: number): Promise<ApplyProgram[]> => {
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
  ["apply-programs-v2"],
  { revalidate: TTL_SECONDS * 2 },
);

/**
 * ⚠️ 缓存键里**带一个时间桶**，不要只靠 `revalidate` 的后台重验证 ——
 * 这是本仓库已经立过碑的坑（见 lib/insight-library-store 同名注释），2026-09-07 在这张表上
 * **原样复现**：迁移 243 落库 16 分钟后，/programs 上华能那条仍是改前的内容
 * （核实日期还写着 9/5、新加的时间窗提示没出现），而同一页里迁移 242 改的几行早就生效了 ——
 * 也就是说它发的是「某个更早时刻的整表快照」，`revalidate:600` 根本没触发重建，且不报错。
 *
 * 这一页的全部价值就是「入口是人工核实过的、最新的」，缓存陈旧几小时正好打在要害上：
 * 公告过期了、链接换了，用户看到的还是旧的。
 *
 * 时间桶让每个 10 分钟窗口成为**不同的缓存条目**：窗口内第一个请求同步取一次（15 行的查询，
 * 毫秒级），其余全部命中，不依赖任何后台任务跑完。
 */
export async function getApplyPrograms(): Promise<ApplyProgram[]> {
  return getCached(Math.floor(Date.now() / (TTL_SECONDS * 1000)));
}
