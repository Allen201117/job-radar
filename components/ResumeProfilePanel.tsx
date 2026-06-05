"use client";

import { useEffect, useState } from "react";
import {
  ArrowCounterClockwise,
  FileText,
  FloppyDisk,
  IdentificationCard,
  Sparkle,
  UploadSimple,
} from "@phosphor-icons/react";
import TagInput from "./TagInput";

type EduItem = { school: string; degree: string; major: string; start: string; end: string };
type InternItem = { company: string; role: string; start: string; end: string; summary: string };
type ProjectItem = { name: string; role: string; stack: string; outcome: string };

type StructuredProfile = {
  headline: string;
  basic_info: { name: string; city: string; contact: string };
  target_roles: string[];
  target_locations: string[];
  skills: string[];
  industries: string[];
  experience_stage: string;
  education: EduItem[];
  internships: InternItem[];
  projects: ProjectItem[];
};

const EMPTY: StructuredProfile = {
  headline: "",
  basic_info: { name: "", city: "", contact: "" },
  target_roles: [],
  target_locations: [],
  skills: [],
  industries: [],
  experience_stage: "",
  education: [],
  internships: [],
  projects: [],
};

const EMPTY_EDU: EduItem = { school: "", degree: "", major: "", start: "", end: "" };
const EMPTY_INTERN: InternItem = { company: "", role: "", start: "", end: "", summary: "" };
const EMPTY_PROJECT: ProjectItem = { name: "", role: "", stack: "", outcome: "" };

const STAGES = ["", "实习", "校招", "社招"];

function coerce(p: any): StructuredProfile {
  return {
    ...EMPTY,
    ...p,
    basic_info: { ...EMPTY.basic_info, ...(p?.basic_info || {}) },
    target_roles: p?.target_roles || [],
    target_locations: p?.target_locations || [],
    skills: p?.skills || [],
    industries: p?.industries || [],
    education: p?.education || [],
    internships: p?.internships || [],
    projects: p?.projects || [],
  };
}

export default function ResumeProfilePanel() {
  const [step, setStep] = useState<"input" | "preview">("input");
  const [resumeText, setResumeText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [applyToPreferences, setApplyToPreferences] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState<StructuredProfile>(EMPTY);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [saved, setSaved] = useState<any | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(true);
  const [llmReady, setLlmReady] = useState<boolean | null>(null);
  const [llmModel, setLlmModel] = useState("");

  useEffect(() => {
    loadSaved();
  }, []);

  async function loadSaved() {
    setLoadingSaved(true);
    try {
      const resp = await fetch("/api/resume");
      const data = await resp.json();
      if (data.ok && data.profile) setSaved(data.profile);
      if (data.llm) {
        setLlmReady(Boolean(data.llm.configured));
        setLlmModel(data.llm.model || "");
      }
    } catch {
      /* 静默 */
    } finally {
      setLoadingSaved(false);
    }
  }

  async function handleParse(e: React.FormEvent) {
    e.preventDefault();
    setParsing(true);
    setMessage("");
    try {
      const form = new FormData();
      form.set("intent", "parse");
      if (file) form.set("resume", file);
      else form.set("resumeText", resumeText);

      const resp = await fetch("/api/resume", { method: "POST", body: form });
      const data = await resp.json();
      if (!data.ok) {
        setMessage(formatError(data.error));
        return;
      }
      setDraft(coerce(data.profile));
      setResumeId(data.resume_id || null);
      setStep("preview");
      setMessage(
        data.source === "rule"
          ? `AI 解析暂不可用（原因：${data.llm_error || "未知"}${data.llm_detail ? "｜" + data.llm_detail : ""}），已用规则给出草稿，请核对补全后再保存。`
          : "AI 已解析，请核对 / 编辑后点「确认保存」。",
      );
    } catch {
      setMessage("解析失败，请稍后重试。");
    } finally {
      setParsing(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setMessage("");
    try {
      const resp = await fetch("/api/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intent: "save", profile: draft, resumeId, applyToPreferences }),
      });
      const data = await resp.json();
      if (!data.ok) {
        setMessage("保存失败，请重试。");
        return;
      }
      setSaved(data.profile);
      setStep("input");
      setFile(null);
      setResumeText("");
      setMessage(data.preferences_applied ? "已保存画像并回填求职偏好。" : "已保存画像。");
      if (data.preferences_applied) {
        window.dispatchEvent(new Event("resume-preferences-updated"));
      }
    } catch {
      setMessage("保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  // —— draft 不可变更新 ——
  const setField = (k: keyof StructuredProfile, v: any) => setDraft((p) => ({ ...p, [k]: v }));
  const setBasic = (k: keyof StructuredProfile["basic_info"], v: string) =>
    setDraft((p) => ({ ...p, basic_info: { ...p.basic_info, [k]: v } }));
  const updateItem = (listKey: keyof StructuredProfile, idx: number, key: string, val: string) =>
    setDraft((p) => {
      const arr = [...(p[listKey] as any[])];
      arr[idx] = { ...arr[idx], [key]: val };
      return { ...p, [listKey]: arr };
    });
  const addItem = (listKey: keyof StructuredProfile, empty: any) =>
    setDraft((p) => ({ ...p, [listKey]: [...(p[listKey] as any[]), { ...empty }] }));
  const removeItem = (listKey: keyof StructuredProfile, idx: number) =>
    setDraft((p) => ({ ...p, [listKey]: (p[listKey] as any[]).filter((_, i) => i !== idx) }));

  function renderList(
    title: string,
    listKey: "education" | "internships" | "projects",
    fields: [string, string][],
    empty: any,
  ) {
    const items = draft[listKey] as any[];
    return (
      <div>
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-white/76">{title}</span>
          <button
            type="button"
            onClick={() => addItem(listKey, empty)}
            className="rounded-full border border-white/10 bg-white/10 px-2.5 py-1 text-xs text-white/72 transition hover:bg-white/16 hover:text-white"
          >
            + 添加
          </button>
        </div>
        <div className="mt-2 space-y-2">
          {items.length === 0 && <p className="text-xs text-white/40">（暂无，可点「添加」补充）</p>}
          {items.map((it, idx) => (
            <div key={idx} className="rounded-xl border border-white/10 bg-white/[0.05] p-3">
              <div className="grid gap-2 sm:grid-cols-2">
                {fields.map(([k, label]) => (
                  <label key={k} className="block text-xs text-white/50">
                    {label}
                    <input
                      value={it[k] || ""}
                      onChange={(e) => updateItem(listKey, idx, k, e.target.value)}
                      className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.07] px-2.5 py-1.5 text-sm text-white outline-none transition focus:border-sky-300"
                    />
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={() => removeItem(listKey, idx)}
                className="mt-2 text-xs text-white/45 transition-colors hover:text-red-200"
              >
                移除
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <section className="rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-5 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-center gap-2">
        <div className="grid size-9 place-items-center rounded-xl bg-lime-300 text-lime-950">
          <IdentificationCard size={18} weight="fill" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">简历画像</h2>
      </div>
      <p className="mt-2 text-sm text-white/50">
        上传或粘贴简历，AI 结构化抽取教育 / 实习 / 项目 / 技能；可预览、编辑后再确认保存，只写入你的账号。
      </p>

      {message && (
        <p className={`mt-3 rounded-xl px-3 py-2 text-sm ${message.includes("失败") || message.includes("暂不") ? "bg-red-400/10 text-red-200" : "bg-sky-300/10 text-sky-200"}`}>
          {message}
        </p>
      )}

      {step === "input" ? (
        <>
          <form onSubmit={handleParse} className="mt-4 space-y-3">
            <div>
              <label className="inline-flex items-center gap-1.5 text-sm font-medium text-white/76">
                <UploadSimple size={16} weight="bold" aria-hidden="true" />
                上传简历（.txt / .md / PDF / Word / 图片）
              </label>
              <input
                type="file"
                accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="mt-1 block w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white file:mr-3 file:rounded-full file:border-0 file:bg-white file:px-3 file:py-1 file:text-xs file:font-semibold file:text-[#08090c] transition duration-200 focus:border-sky-300 focus:outline-none"
              />
            </div>

            <div>
              <label className="inline-flex items-center gap-1.5 text-sm font-medium text-white/76">
                <FileText size={16} weight="bold" aria-hidden="true" />
                或粘贴简历内容
              </label>
              <textarea
                value={resumeText}
                onChange={(e) => setResumeText(e.target.value)}
                placeholder="粘贴教育经历、实习经历、项目经历、技能等"
                rows={6}
                className="mt-1 block w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white transition duration-200 placeholder:text-white/32 focus:border-sky-300 focus:outline-none"
              />
            </div>

            {llmReady === false && (
              <p className="rounded-xl bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
                未检测到 SILICONFLOW_API_KEY，AI 解析会降级为规则草稿。请在 Vercel → Settings →
                Environment Variables 添加（勾 Production，禁加 NEXT_PUBLIC_ 前缀），保存后 Redeploy。
              </p>
            )}
            {llmReady === true && (
              <p className="text-xs text-white/40">AI 解析已就绪{llmModel ? `（模型 ${llmModel}）` : ""}。</p>
            )}

            <button
              type="submit"
              disabled={parsing || (!file && !resumeText.trim())}
              className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-5 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98] disabled:opacity-50"
            >
              <Sparkle size={16} weight="fill" aria-hidden="true" />
              {parsing ? "AI 解析中…" : "AI 解析简历"}
            </button>
          </form>

          <div className="mt-5 border-t border-white/10 pt-4">
            {loadingSaved ? (
              <p className="text-sm text-white/50">加载画像中…</p>
            ) : saved ? (
              <SavedSummary profile={saved} />
            ) : (
              <p className="text-sm text-white/50">还没有简历画像，先上传或粘贴简历开始。</p>
            )}
          </div>
        </>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm text-white/76">
              一句话定位
              <input
                value={draft.headline}
                onChange={(e) => setField("headline", e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white outline-none transition focus:border-sky-300"
              />
            </label>
            <label className="block text-sm text-white/76">
              求职阶段
              <select
                value={draft.experience_stage}
                onChange={(e) => setField("experience_stage", e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white outline-none transition focus:border-sky-300"
              >
                {STAGES.map((s) => (
                  <option key={s} value={s} className="bg-[#15161a]">
                    {s || "未判断"}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block text-sm text-white/76">
              姓名
              <input
                value={draft.basic_info.name}
                onChange={(e) => setBasic("name", e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white outline-none transition focus:border-sky-300"
              />
            </label>
            <label className="block text-sm text-white/76">
              城市
              <input
                value={draft.basic_info.city}
                onChange={(e) => setBasic("city", e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white outline-none transition focus:border-sky-300"
              />
            </label>
            <label className="block text-sm text-white/76">
              联系方式（已脱敏）
              <input
                value={draft.basic_info.contact}
                onChange={(e) => setBasic("contact", e.target.value)}
                className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white outline-none transition focus:border-sky-300"
              />
            </label>
          </div>

          <div className="space-y-3">
            <div>
              <span className="text-sm font-medium text-white/76">目标岗位方向</span>
              <TagInput values={draft.target_roles} onChange={(v) => setField("target_roles", v)} placeholder="回车添加，如 数据分析" />
            </div>
            <div>
              <span className="text-sm font-medium text-white/76">期望城市</span>
              <TagInput values={draft.target_locations} onChange={(v) => setField("target_locations", v)} placeholder="如 上海" />
            </div>
            <div>
              <span className="text-sm font-medium text-white/76">技能标签</span>
              <TagInput values={draft.skills} onChange={(v) => setField("skills", v)} placeholder="如 Python、SQL" />
            </div>
            <div>
              <span className="text-sm font-medium text-white/76">行业</span>
              <TagInput values={draft.industries} onChange={(v) => setField("industries", v)} placeholder="如 互联网、金融" />
            </div>
          </div>

          {renderList("教育经历", "education", [["school", "学校"], ["degree", "学历"], ["major", "专业"], ["start", "开始"], ["end", "结束"]], EMPTY_EDU)}
          {renderList("实习经历", "internships", [["company", "公司"], ["role", "岗位"], ["start", "开始"], ["end", "结束"], ["summary", "职责 / 成果"]], EMPTY_INTERN)}
          {renderList("工作 / 项目经历", "projects", [["name", "项目"], ["role", "角色"], ["stack", "技术栈"], ["outcome", "成果"]], EMPTY_PROJECT)}

          <label className="flex cursor-pointer items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-2 text-sm text-white/74 transition duration-200 hover:bg-white/16 hover:text-white">
            <input type="checkbox" checked={applyToPreferences} onChange={(e) => setApplyToPreferences(e.target.checked)} />
            同步到求职偏好（方向 / 城市 / 技能）
          </label>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-5 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98] disabled:opacity-50"
            >
              <FloppyDisk size={16} weight="bold" aria-hidden="true" />
              {saving ? "保存中…" : "确认保存"}
            </button>
            <button
              type="button"
              onClick={() => {
                setStep("input");
                setMessage("");
              }}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-5 py-2 text-sm font-medium text-white/78 transition duration-200 hover:bg-white/16 hover:text-white active:scale-[0.98]"
            >
              <ArrowCounterClockwise size={16} weight="bold" aria-hidden="true" />
              重新上传
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function SavedSummary({ profile }: { profile: any }) {
  const eduCount = (profile.education || []).length;
  const internCount = (profile.internships || []).length;
  const projectCount = (profile.projects || []).length;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-xs text-white/42">当前画像</div>
        <div className="mt-1 text-sm font-medium text-white">{profile.headline || "未命名画像"}</div>
      </div>
      <ChipGroup label="方向" values={profile.target_roles || []} />
      <ChipGroup label="城市" values={profile.target_locations || []} />
      <ChipGroup label="技能" values={profile.skills || []} />
      <div className="flex flex-wrap gap-2 text-xs text-white/50">
        <span className="rounded-full border border-white/10 bg-white/10 px-2.5 py-1">教育 {eduCount}</span>
        <span className="rounded-full border border-white/10 bg-white/10 px-2.5 py-1">实习 {internCount}</span>
        <span className="rounded-full border border-white/10 bg-white/10 px-2.5 py-1">项目 {projectCount}</span>
        {(profile.experience_stage || profile.seniority) && (
          <span className="rounded-full border border-white/10 bg-white/10 px-2.5 py-1">
            阶段 {profile.experience_stage || profile.seniority}
          </span>
        )}
      </div>
    </div>
  );
}

function ChipGroup({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div>
      <div className="text-xs text-white/42">{label}</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span
            key={value}
            className="rounded-full border border-white/10 bg-white/10 px-2.5 py-1 text-xs font-medium text-white/76"
          >
            {value}
          </span>
        ))}
      </div>
    </div>
  );
}

function formatError(error: string) {
  if (error === "unsupported_file_type") return "暂不支持该文件类型，请上传 .txt/.md/PDF/Word/图片，或粘贴文本。";
  if (error === "file_too_large") return "文件过大，请控制在 10MB 内。";
  if (error === "empty_resume_text") return "没有解析到文字内容，请换文件或直接粘贴文本。";
  return "解析失败，请稍后重试。";
}
