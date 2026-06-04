"use client";

import { useEffect, useState } from "react";
import { FloppyDisk, IdentificationBadge, UserCircle } from "@phosphor-icons/react";

const MAX_BIO = 200;

export default function ProfileEditor({ email }: { email?: string }) {
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    try {
      const resp = await fetch("/api/profile");
      const data = await resp.json();
      if (data.ok && data.profile) {
        setDisplayName(data.profile.display_name || "");
        setBio(data.profile.bio || "");
      }
    } catch {
      /* 静默：保留空表单 */
    } finally {
      setLoading(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const resp = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName, bio }),
      });
      const data = await resp.json();
      setMessage(data.ok ? "已保存。" : "保存失败，请重试。");
    } catch {
      setMessage("保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-5 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex items-center gap-2">
        <div className="grid size-9 place-items-center rounded-xl bg-sky-300 text-sky-950">
          <UserCircle size={18} weight="fill" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">个人资料</h2>
      </div>

      <form onSubmit={save} className="mt-4 space-y-3">
        <div>
          <label htmlFor="display_name" className="inline-flex items-center gap-1.5 text-sm font-medium text-white/76">
            <IdentificationBadge size={16} weight="bold" aria-hidden="true" />
            昵称
          </label>
          <input
            id="display_name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={40}
            placeholder={loading ? "加载中…" : "给自己起个昵称"}
            className="mt-1 block w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white transition duration-200 placeholder:text-white/32 focus:border-sky-300 focus:outline-none"
          />
        </div>

        <div>
          <label htmlFor="bio" className="text-sm font-medium text-white/76">
            个性签名
          </label>
          <textarea
            id="bio"
            value={bio}
            onChange={(e) => setBio(e.target.value.slice(0, MAX_BIO))}
            rows={2}
            placeholder="一句话介绍自己（选填）"
            className="mt-1 block w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white transition duration-200 placeholder:text-white/32 focus:border-sky-300 focus:outline-none"
          />
          <div className="mt-1 text-right text-xs text-white/35">
            {bio.length}/{MAX_BIO}
          </div>
        </div>

        {email && <p className="text-xs text-white/40">登录邮箱：{email}</p>}

        {message && (
          <p className={`rounded-full px-3 py-2 text-sm ${message.includes("失败") ? "bg-red-400/10 text-red-200" : "bg-sky-300/10 text-sky-200"}`}>
            {message}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-5 py-2 text-sm font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98] disabled:opacity-50"
        >
          <FloppyDisk size={16} weight="bold" aria-hidden="true" />
          {saving ? "保存中…" : "保存资料"}
        </button>
      </form>
    </section>
  );
}
