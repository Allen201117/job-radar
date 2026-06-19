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
    <section className="surface p-5 text-[#1a1714] dark:text-[#f3ecdf]">
      <div className="flex items-center gap-2">
        <div className="grid size-9 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
          <UserCircle size={18} weight="fill" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">个人资料</h2>
      </div>

      <form onSubmit={save} className="mt-4 space-y-3">
        <div>
          <label htmlFor="display_name" className="inline-flex items-center gap-1.5 text-sm font-medium text-[#5f594e] dark:text-[#b6ad9d]">
            <IdentificationBadge size={16} weight="bold" aria-hidden="true" />
            昵称
          </label>
          <input
            id="display_name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={40}
            placeholder={loading ? "加载中…" : "给自己起个昵称"}
            className="mt-1 field-soft"
          />
        </div>

        <div>
          <label htmlFor="bio" className="text-sm font-medium text-[#5f594e] dark:text-[#b6ad9d]">
            个性签名
          </label>
          <textarea
            id="bio"
            value={bio}
            onChange={(e) => setBio(e.target.value.slice(0, MAX_BIO))}
            rows={2}
            placeholder="一句话介绍自己（选填）"
            className="mt-1 field-soft"
          />
          <div className="mt-1 text-right text-xs text-[#a39a8c] dark:text-[#8b8478]">
            {bio.length}/{MAX_BIO}
          </div>
        </div>

        {email && <p className="text-xs text-[#8a8275] dark:text-[#9a9184]">登录邮箱：{email}</p>}

        {message && (
          <p className={`rounded-full border px-3 py-2 text-sm ${message.includes("失败") ? "border-[#e0b4ac] dark:border-[#7a392e]/60 bg-[#f7e6e1] dark:bg-[#3a201a] text-[#9c4a3c] dark:text-[#e6a99f]" : "border-[#bcd2ed] dark:border-[#7fb2e8]/30 bg-[#e8f1fc] dark:bg-[#7fb2e8]/15 text-[#2f6299] dark:text-[#7fb2e8]"}`}>
            {message}
          </p>
        )}

        <button
          type="submit"
          disabled={saving}
          className="btn-ink"
        >
          <FloppyDisk size={16} weight="bold" aria-hidden="true" />
          {saving ? "保存中…" : "保存资料"}
        </button>
      </form>
    </section>
  );
}
