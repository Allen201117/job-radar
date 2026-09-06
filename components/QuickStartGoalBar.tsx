"use client";

// 热门兜底位上的两步转化条：选了行业 → 问「设为目标行业吗」→ 存下后接着选岗位方向 → 当场切成精筛。
//
// 为什么必须走完第二步：`profileReadiness` 只看 **目标岗位 / 关键词 / 关注公司** 三样，
// `target_industries` **不在其中**（见 lib/opportunities/profile.ts）。只存行业的话，用户点完
// 页面一点变化都没有——一个「点了没反应」的按钮比不放更伤信任。所以行业存完立刻进方向选择，
// 两步各自都有真实产出（行业会被记住并用于后续排序，方向则直接把画像变成「就绪」）。
//
// ⚠️ 方向词只能来自 lib/quick-start-roles（词库规范词），别改成职能桶名：
// 实测 keywordMatchTier("研发","后台开发") = null，桶名写进偏好会让看板更空。
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import SaveToast, { type SaveState } from "@/components/SaveToast";
import { Button } from "@/components/ui";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import { QUICK_START_MAX_ROLES, quickStartRolesByBucket } from "@/lib/quick-start-roles";

type Step = "askIndustry" | "pickRoles" | "hidden";

export default function QuickStartGoalBar({
  industry,
  savedIndustries,
}: {
  /** 当前选中的行业；选「全部」时为 null（无从追问「设成哪个行业」）。 */
  industry: string | null;
  /** 用户已经存过的目标行业，用来避免对同一个行业重复追问。 */
  savedIndustries: string[];
}) {
  const router = useRouter();
  const [savedLocal, setSavedLocal] = useState<string[]>(savedIndustries);
  const [dismissed, setDismissed] = useState(false);
  const [forcePickRoles, setForcePickRoles] = useState(false);
  const [roles, setRoles] = useState<string[]>([]);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);

  const buckets = useMemo(() => quickStartRolesByBucket(), []);
  const alreadySaved = !!industry && savedLocal.some((i) => i === industry);

  const step: Step = dismissed
    ? "hidden"
    : forcePickRoles || alreadySaved
      ? "pickRoles"
      : industry
        ? "askIndustry"
        : "hidden";

  if (step === "hidden") return null;

  async function post(payload: Record<string, unknown>) {
    setError(null);
    setSaveState("saving");
    try {
      const resp = await fetch("/api/preferences/quick-start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
      setSaveState("done");
      return data as { profile_ready?: boolean };
    } catch (e) {
      // 失败绝不静默：这是「重提交」档，用户正等着结果（见 CLAUDE.md 点击反馈分档）。
      setSaveState("error");
      setError(e instanceof Error ? e.message : "save_failed");
      return null;
    }
  }

  async function saveIndustry() {
    if (!industry) return;
    track("radar_quickstart_industry", { industry });
    const data = await post({ industry });
    if (!data) return;
    setSavedLocal((prev) => (prev.includes(industry) ? prev : [...prev, industry]));
    setForcePickRoles(true);
  }

  async function saveRoles() {
    if (!roles.length) return;
    track("radar_quickstart_roles", { count: roles.length, industry: industry ?? "all" });
    const data = await post({ roles, ...(industry ? { industry } : {}) });
    if (!data) return;
    // 画像就绪 → 重新渲染 /today，服务端这次会走个人召回而不是热门兜底。
    if (data.profile_ready) router.refresh();
  }

  function toggleRole(value: string) {
    setRoles((prev) =>
      prev.includes(value)
        ? prev.filter((v) => v !== value)
        : prev.length >= QUICK_START_MAX_ROLES
          ? prev
          : [...prev, value],
    );
  }

  const busy = saveState === "saving";

  return (
    <div className="rounded-[1.25rem] border border-tone-sky-border bg-tone-sky-bg px-5 py-4">
      {step === "askIndustry" ? (
        <div className="sm:flex sm:items-center sm:justify-between sm:gap-4">
          <p className="t-body-sm min-w-0 ink-1">
            你在看「{industry}」——把它设为你的求职行业？之后这里会优先给你这个方向的机会。
          </p>
          <div className="mt-3 flex shrink-0 gap-2 sm:mt-0">
            <Button size="sm" variant="ink" onClick={saveIndustry} disabled={busy}>
              设为我的行业
            </Button>
            <Button size="sm" variant="soft" onClick={() => setDismissed(true)} disabled={busy}>
              以后再说
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <p className="t-body-sm ink-1">
            {industry && savedLocal.includes(industry) ? `已记住「${industry}」。` : ""}
            再选 1–{QUICK_START_MAX_ROLES} 个想找的岗位方向，这里立刻换成为你精筛的机会。
          </p>
          {/* ⚠️ 扁平换行，**不要**改回「一个职能一行 + 左侧栏标签」那种版式：
              live 实测那样排出来 667px 高，在 720px 视口里把整屏岗位全挤到折叠线以下——
              而这个兜底位存在的理由就是「先给东西看」。方向词按职能桶顺序排列，
              相关的词自然挨在一起，不靠左侧栏也扫得动。 */}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {buckets.flatMap(({ roles: list }) => list).map((role) => {
              const on = roles.includes(role.value);
              return (
                <button
                  key={role.value}
                  type="button"
                  aria-pressed={on}
                  title={role.bucket}
                  onClick={() => toggleRole(role.value)}
                  disabled={busy || (!on && roles.length >= QUICK_START_MAX_ROLES)}
                  className={cn(
                    "press-feedback rounded-full border px-2.5 py-1 text-[0.8125rem] disabled:opacity-45",
                    on
                      ? "border-transparent bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                      : "border-black/[0.12] bg-white/60 ink-2 dark:border-white/[0.12] dark:bg-white/[0.06]",
                  )}
                >
                  {role.label}
                </button>
              );
            })}
          </div>
          {roles.length >= QUICK_START_MAX_ROLES && (
            // 到上限时其余 chip 全灰，不说一句会读成「点不动 = 坏了」。
            <p className="t-caption mt-2 ink-3">最多选 {QUICK_START_MAX_ROLES} 个；想换的话先取消一个。</p>
          )}
          <div className="mt-3 flex items-center gap-2">
            <Button size="sm" variant="ink" onClick={saveRoles} disabled={busy || roles.length === 0}>
              {roles.length ? `开始精筛（已选 ${roles.length} 个）` : "先选一个方向"}
            </Button>
            <Button size="sm" variant="soft" onClick={() => setDismissed(true)} disabled={busy}>
              以后再说
            </Button>
          </div>
          {error && (
            <p className="t-caption mt-2 text-tone-rose-fg">没保存成功，请再试一次。</p>
          )}
        </div>
      )}
      <SaveToast
        state={saveState}
        savingText="保存中…"
        doneText="已保存"
        errorText="保存失败"
        onDismiss={() => setSaveState("idle")}
      />
    </div>
  );
}
