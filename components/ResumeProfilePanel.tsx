"use client";

import { useEffect, useState } from "react";
import { FileText, IdentificationCard, UploadSimple } from "@phosphor-icons/react";

type CandidateProfile = {
  headline: string | null;
  target_roles: string[] | null;
  target_locations: string[] | null;
  skills: string[] | null;
  industries: string[] | null;
  seniority: string | null;
  experience_stage?: string | null;
  education: string[] | null;
  experience: string[] | null;
  education_summary?: string | null;
  experience_summary?: string | null;
};

export default function ResumeProfilePanel() {
  const [resumeText, setResumeText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [applyToPreferences, setApplyToPreferences] = useState(false);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    loadProfile();
  }, []);

  async function loadProfile() {
    setLoading(true);
    try {
      const resp = await fetch("/api/resume");
      const data = await resp.json();
      if (data.ok && data.profile) {
        setProfile(data.profile);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage("");

    try {
      const form = new FormData();
      form.set("applyToPreferences", String(applyToPreferences));
      if (file) {
        form.set("resume", file);
      } else {
        form.set("resumeText", resumeText);
      }

      const resp = await fetch("/api/resume", {
        method: "POST",
        body: form,
      });
      const data = await resp.json();

      if (!data.ok) {
        setMessage(formatError(data.error));
        return;
      }

      setProfile(data.profile);
      setMessage(
        data.preferences_applied ? "已解析并回填求职偏好。" : "已解析用户画像。",
      );
      if (data.preferences_applied) {
        window.dispatchEvent(new Event("resume-preferences-updated"));
      }
    } catch (error) {
      setMessage("解析失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-5 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div>
        <div className="flex items-center gap-2">
          <div className="grid size-9 place-items-center rounded-xl bg-lime-300 text-lime-950">
            <IdentificationCard size={18} weight="fill" aria-hidden="true" />
          </div>
          <h2 className="text-base font-semibold">简历画像</h2>
        </div>
        <p className="mt-2 text-sm text-white/50">
          支持 .txt / .md 或直接粘贴文本，解析结果只写入你的账号。
        </p>
      </div>

      <form onSubmit={handleSubmit} className="mt-4 space-y-3">
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

        <label className="flex cursor-pointer items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-2 text-sm text-white/74 transition duration-200 hover:bg-white/16 hover:text-white">
          <input
            type="checkbox"
            checked={applyToPreferences}
            onChange={(e) => setApplyToPreferences(e.target.checked)}
          />
          同步到求职偏好
        </label>

        {message && (
          <p className={`rounded-full px-3 py-2 text-sm ${message.includes("失败") || message.includes("暂不") ? "bg-red-400/10 text-red-200" : "bg-sky-300/10 text-sky-200"}`}>
            {message}
          </p>
        )}

        <button
          type="submit"
          disabled={saving || (!file && !resumeText.trim())}
          className="rounded-full bg-sky-300 px-5 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98] disabled:opacity-50"
        >
          {saving ? "解析中..." : "解析简历"}
        </button>
      </form>

      <div className="mt-5 border-t border-white/10 pt-4">
        {loading ? (
          <p className="text-sm text-white/50">加载画像中...</p>
        ) : profile ? (
          <ProfileSummary profile={profile} />
        ) : (
          <p className="text-sm text-white/50">还没有简历画像。</p>
        )}
      </div>
    </section>
  );
}

function ProfileSummary({ profile }: { profile: CandidateProfile }) {
  return (
    <div className="space-y-3">
      <div>
        <div className="text-xs text-white/42">画像摘要</div>
        <div className="mt-1 text-sm font-medium text-white">
          {profile.headline || "未命名画像"}
        </div>
      </div>
      <ChipGroup label="方向" values={profile.target_roles || []} />
      <ChipGroup label="城市" values={profile.target_locations || []} />
      <ChipGroup label="技能" values={profile.skills || []} />
      <ChipGroup label="行业" values={profile.industries || []} />
      {(profile.experience_stage || profile.seniority) && (
      <div className="text-sm text-white/50">
          阶段：<span className="text-white">{profile.experience_stage || profile.seniority}</span>
        </div>
      )}
      {profile.education_summary && (
        <SummaryLine label="教育" value={profile.education_summary} />
      )}
      {profile.experience_summary && (
        <SummaryLine label="经历" value={profile.experience_summary} />
      )}
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

function SummaryLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-sm text-white/50">
      {label}：<span className="text-white">{value}</span>
    </div>
  );
}

function formatError(error: string) {
  if (error === "unsupported_file_type") {
    return "暂不支持直接解析 PDF/DOCX，请上传 .txt/.md 或粘贴文本。";
  }
  if (error === "file_too_large") return "文件过大，请控制在 1MB 内。";
  if (error === "empty_resume_text") return "简历内容为空。";
  return "解析失败，请稍后重试。";
}
