"use client";

import { useState, useEffect } from "react";
import type { UserPreferences } from "@/lib/types";
import { track } from "@/lib/track";
import { normalizeCompany } from "@/lib/company-normalize";
import TagInput from "./TagInput";
import SaveToast, { type SaveState } from "@/components/SaveToast";
import { Buildings, CaretDown, CheckCircle, SlidersHorizontal } from "@phosphor-icons/react";

type Coverage = { company: string; status: string; matched_sources: number; resolution_note?: string | null };

// §10.1 覆盖状态文案（不暴露 adapter/parser/source URL/抓取细节）
const COVERAGE_LABEL: Record<string, { label: string; tone: string }> = {
  covered: { label: "已纳入持续监控", tone: "bg-[#e6f2d3] text-[#5a7a2f] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]" },
  queued: { label: "已记录，等待接入官方招聘源", tone: "bg-[#dbe9fa] text-[#2f6299] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8]" },
  researching: { label: "正在确认官方招聘入口", tone: "bg-[#fbe6d1] text-[#9a6326] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]" },
  unsupported: { label: "暂时无法稳定监控", tone: "bg-[#ece7dd] text-[#6b655a] dark:bg-white/[0.08] dark:text-[#b6ad9d]" },
};

export default function PreferenceForm() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [coverage, setCoverage] = useState<Coverage[]>([]);
  const [coverageAvailable, setCoverageAvailable] = useState(true);
  const [message, setMessage] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveErr, setSaveErr] = useState("");

  useEffect(() => {
    loadPrefs();
    function handlePreferencesUpdated() {
      loadPrefs();
    }
    window.addEventListener("resume-preferences-updated", handlePreferencesUpdated);
    window.addEventListener("preferences-scope-updated", handlePreferencesUpdated);
    return () => {
      window.removeEventListener("resume-preferences-updated", handlePreferencesUpdated);
      window.removeEventListener("preferences-scope-updated", handlePreferencesUpdated);
    };
  }, []);

  async function loadPrefs() {
    try {
      const resp = await fetch("/api/preferences");
      if (resp.status === 401) {
        setMessage("请先登录。");
        return;
      }
      const data = await resp.json();
      if (data?.ok) {
        setPrefs(data.preferences ? withDefaults(data.preferences) : createEmptyPrefs());
        setCoverage(Array.isArray(data.coverage) ? data.coverage : []);
        setCoverageAvailable(data.coverage_available !== false);
      } else {
        setMessage("加载失败：" + (data?.error || "未知错误"));
      }
    } catch (e) {
      setMessage("加载失败：" + (e as Error).message);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!prefs) return;
    setSaveState("saving");
    const prevCompanies = coverage.map((c) => c.company);
    try {
      const resp = await fetch("/api/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_locations: prefs.target_locations,
          target_roles: prefs.target_roles,
          target_keywords: prefs.target_keywords,
          exclude_keywords: prefs.exclude_keywords,
          target_companies: prefs.target_companies,
          target_industries: prefs.target_industries || [],
          job_scope: prefs.job_scope ?? "domestic",
          target_regions: prefs.target_regions ?? [],
          daily_limit: prefs.daily_limit,
          radar_intensity: prefs.radar_intensity ?? "active",
          experience_stage: prefs.experience_stage ?? "",
        }),
      });
      const data = await resp.json();
      // 偏好本体都没存（5xx / 非部分成功）→ 真失败
      if (!data?.ok && !data?.preferences_saved) {
        throw new Error(data?.error || `HTTP ${resp.status}`);
      }
      if (data.preferences) setPrefs(withDefaults({ ...prefs, ...data.preferences }));
      if (data.ok) {
        const newCoverage: Coverage[] = data.coverage || [];
        setCoverage(newCoverage);
        setCoverageAvailable(true);
        emitWatchEvents(prevCompanies, newCoverage);
        setSaveState("done");
      } else {
        // 偏好已存、关注公司覆盖同步失败 → 诚实部分成功，不显示成功 badge、不伪造 coverage
        setSaveErr("求职目标已保存，但关注公司状态同步失败，请重试。");
        setSaveState("error");
      }
    } catch (err) {
      setSaveErr("保存失败：" + (err as Error).message);
      setSaveState("error");
    }
  }

  // 关注公司新增/移除埋点（§13.1）：按归一公司名 diff，仅去标识计数信息。
  function emitWatchEvents(prevCompanies: string[], newCoverage: Coverage[]) {
    const prevByNorm = new Map<string, Coverage>();
    coverage.forEach((c) => prevByNorm.set(normalizeCompany(c.company), c));
    const prevNorms = new Set(prevCompanies.map(normalizeCompany));
    const newNorms = new Set(newCoverage.map((c) => normalizeCompany(c.company)));
    for (const c of newCoverage) {
      if (!prevNorms.has(normalizeCompany(c.company))) {
        track("company_watch_added", { coverage_status: c.status });
      }
    }
    for (const norm of Array.from(prevNorms)) {
      if (!newNorms.has(norm)) {
        track("company_watch_removed", { previous_status: prevByNorm.get(norm)?.status ?? "queued" });
      }
    }
  }

  function setArray(field: keyof UserPreferences, arr: string[]) {
    if (!prefs) return;
    setPrefs({ ...prefs, [field]: arr } as UserPreferences);
  }

  if (!prefs) {
    return (
      <div className="surface p-5 text-sm text-[#5f594e] dark:text-[#b6ad9d]">
        {message || "加载中..."}
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="surface space-y-5 p-5 text-[#1a1714] dark:text-[#f3ecdf]">
      <div className="flex items-center gap-2">
        <div className="grid size-9 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
          <SlidersHorizontal size={18} weight="fill" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-base font-semibold">求职目标</h2>
          <p className="text-sm text-[#8a8275] dark:text-[#9a9184]">系统据此每天替你筛官方机会；改完记得保存。</p>
        </div>
      </div>
      <section className="rounded-2xl border border-black/[0.07] bg-white/55 p-4 dark:border-white/[0.1] dark:bg-white/[0.05]">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
          <h3 className="text-sm font-semibold">核心</h3>
          <p className="text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">填这三项就能开始，其它可稍后完善</p>
        </div>
        <div className="mt-4 space-y-4">
          <Field label="目标城市">
            <TagInput
              values={prefs.target_locations || []}
              onChange={(v) => setArray("target_locations", v)}
              placeholder="北京、上海、深圳…（回车或逗号添加）"
            />
          </Field>
          <Field label="目标岗位方向">
            <TagInput
              values={prefs.target_roles || []}
              onChange={(v) => setArray("target_roles", v)}
              placeholder="算法、产品经理、数据分析…"
            />
          </Field>
          <Field label="求职阶段">
            <div className="mt-1 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {([
                { v: "", label: "不限" },
                { v: "实习", label: "实习" },
                { v: "校招", label: "校招" },
                { v: "社招", label: "社招" },
              ] as const).map((opt) => {
                const selected = (prefs.experience_stage ?? "") === opt.v;
                return (
                  <button
                    key={opt.v || "all"}
                    type="button"
                    onClick={() => setPrefs({ ...prefs, experience_stage: opt.v })}
                    aria-pressed={selected}
                    className={
                      selected
                        ? "rounded-xl border border-[#1a1714] bg-[#1a1714] px-3 py-2 text-sm font-semibold text-[#f7f1e6] dark:border-[#f3ecdf] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                        : "rounded-xl border border-black/[0.1] bg-white/55 px-3 py-2 text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]"
                    }
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>
      </section>

      {/* §10.1 关注公司：保存后立即出现状态，不等待抓取 */}
      <div className="rounded-2xl border border-black/[0.07] bg-white/45 p-4 dark:border-white/[0.1] dark:bg-white/[0.04]">
        <div className="flex items-center gap-2">
          <Buildings size={18} weight="fill" className="text-[#5f594e] dark:text-[#b6ad9d]" aria-hidden="true" />
          <h3 className="text-sm font-semibold">关注公司</h3>
        </div>
        <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
          加入你想持续盯的公司，保存后系统会替你监控它们的官方招聘页。未覆盖的会先记录、再接入。
        </p>
        <div className="mt-3">
          <TagInput
            values={prefs.target_companies || []}
            onChange={(v) => setArray("target_companies", v)}
            placeholder="Apple、百度、京东、字节…"
          />
        </div>
        {!coverageAvailable && (
          <p className="mt-3 rounded-lg border border-[#e0b4ac] bg-[#f7e6e1] px-3 py-2 text-xs text-[#9c4a3c] dark:border-[#7a392e]/[0.6] dark:bg-[#3a201a] dark:text-[#e6a99f]">
            关注公司状态暂时无法获取，请稍后刷新。
          </p>
        )}
        {coverageAvailable && coverage.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {coverage.map((c) => {
              const meta = COVERAGE_LABEL[c.status] || COVERAGE_LABEL.queued;
              return (
                <li key={c.company} className="text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate font-medium text-[#3f3a33] dark:text-[#d9d0c2]">{c.company}</span>
                    <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${meta.tone}`}>{meta.label}</span>
                  </div>
                  {c.resolution_note && (
                    <p className="mt-1 text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">{c.resolution_note}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <details className="group rounded-2xl border border-black/[0.07] bg-white/35 p-4 dark:border-white/[0.1] dark:bg-white/[0.03]">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 [&::-webkit-details-marker]:hidden">
          <span>
            <span className="block text-sm font-semibold">进阶设置（可选）</span>
            <span className="mt-0.5 block text-xs leading-5 text-[#8a8275] dark:text-[#9a9184]">
              关键词、排除项、行业和推荐频率
            </span>
          </span>
          <CaretDown
            size={16}
            weight="bold"
            className="shrink-0 text-[#8a8275] transition-transform group-open:rotate-180 dark:text-[#9a9184]"
            aria-hidden="true"
          />
        </summary>
        <div className="mt-4 space-y-4 border-t border-black/[0.06] pt-4 dark:border-white/[0.08]">
          <Field label="命中关键词">
            <TagInput
              values={prefs.target_keywords || []}
              onChange={(v) => setArray("target_keywords", v)}
              placeholder="Python、机器学习、LLM…"
            />
          </Field>
          <Field label="排除关键词">
            <TagInput
              values={prefs.exclude_keywords || []}
              onChange={(v) => setArray("exclude_keywords", v)}
              placeholder="销售、客服…"
            />
          </Field>
          <Field label="目标行业">
            <TagInput
              values={prefs.target_industries || []}
              onChange={(v) => setArray("target_industries", v)}
              placeholder="互联网、金融、消费…（跨行业岗位会被挡掉）"
            />
          </Field>
          <Field label="雷达强度">
            <div className="mt-1 flex gap-2">
              {([
                { v: "active", label: "积极找", hint: "每天多推、含拓展" },
                { v: "passive", label: "先看看", hint: "只推高价值与大事" },
              ] as const).map((opt) => {
                const selected = (prefs.radar_intensity ?? "active") === opt.v;
                return (
                  <button
                    key={opt.v}
                    type="button"
                    onClick={() => setPrefs({ ...prefs, radar_intensity: opt.v })}
                    aria-pressed={selected}
                    className={
                      selected
                        ? "flex-1 rounded-xl border border-[#1a1714] bg-[#1a1714] px-3 py-2 text-left text-sm font-semibold text-[#f7f1e6] dark:border-[#f3ecdf] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                        : "flex-1 rounded-xl border border-black/[0.1] bg-white/55 px-3 py-2 text-left text-sm font-medium text-[#3f3a33] transition hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:text-[#d9d0c2]"
                    }
                  >
                    {opt.label}
                    <span className={`mt-0.5 block text-[11px] font-normal ${selected ? "opacity-80" : "text-[#8a8275] dark:text-[#9a9184]"}`}>
                      {opt.hint}
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 text-[11px] leading-5 text-[#8a8275] dark:text-[#9a9184]">
              强度只调日常推荐的多少与频率；关键提醒（收藏岗截止/关闭）始终会提醒你。系统也会按你的活跃度自动校准。
            </p>
          </Field>
          <Field label="每日机会上限">
            <input
              type="number"
              min={5}
              max={30}
              value={prefs.daily_limit}
              onChange={(e) => setPrefs({ ...prefs, daily_limit: Number(e.target.value) || 20 })}
              className="mt-1 field-soft"
            />
          </Field>
        </div>
      </details>

      {message && (
        <p className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm ${message.includes("失败") ? "border-[#e0b4ac] dark:border-[#7a392e]/[0.60] bg-[#f7e6e1] dark:bg-[#3a201a] text-[#9c4a3c] dark:text-[#e6a99f]" : "border-[#bcd2ed] dark:border-[#7fb2e8]/[0.30] bg-[#e8f1fc] dark:bg-[#7fb2e8]/[0.15] text-[#2f6299] dark:text-[#7fb2e8]"}`}>
          {!message.includes("失败") && <CheckCircle size={16} weight="fill" aria-hidden="true" />}
          {message}
        </p>
      )}

      <button type="submit" disabled={saveState === "saving"} className="btn-ink">
        {saveState === "saving" ? "保存中..." : "保存目标"}
      </button>

      <SaveToast
        state={saveState}
        doneText="已保存目标"
        errorText={saveErr || "保存失败"}
        onDismiss={() => setSaveState("idle")}
      />
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-sm font-medium text-[#5f594e] dark:text-[#b6ad9d]">{label}</label>
      {children}
    </div>
  );
}

function withDefaults(p: Partial<UserPreferences>): UserPreferences {
  return {
    id: p.id ?? "",
    user_id: p.user_id ?? "",
    target_locations: p.target_locations ?? [],
    target_roles: p.target_roles ?? [],
    target_keywords: p.target_keywords ?? [],
    exclude_keywords: p.exclude_keywords ?? [],
    target_companies: p.target_companies ?? [],
    target_industries: p.target_industries ?? [],
    experience_stage: p.experience_stage ?? null,
    job_scope: p.job_scope ?? "domestic",
    target_regions: p.target_regions ?? [],
    en_target_roles: p.en_target_roles ?? [],
    en_skills: p.en_skills ?? [],
    en_target_keywords: p.en_target_keywords ?? [],
    has_en_resume: p.has_en_resume ?? false,
    daily_limit: p.daily_limit ?? 20,
    radar_intensity: p.radar_intensity ?? "active",
    radar_intensity_source: p.radar_intensity_source,
    radar_intensity_updated_at: p.radar_intensity_updated_at,
  };
}

function createEmptyPrefs(): UserPreferences {
  return withDefaults({});
}
