"use client";

import { useMemo, useState } from "react";
import { CheckCircle, PaperPlaneTilt } from "@phosphor-icons/react";
import {
  FIRST_PARTY_CONTENT_MAX,
  FIRST_PARTY_TOPICS,
  TOPIC_DEFAULT_DIMENSION,
  type FirstPartyTopic,
} from "@/lib/insight-submission";
import { cn } from "@/lib/utils";
import { LEGACY_INPUT_CLASS as inputCls } from "@/components/ui/deprecated/legacy-input-class";

interface Props {
  company: string;
  onSubmitted?: () => void;
}


const TOPIC_OPTIONS = Object.entries(FIRST_PARTY_TOPICS).map(([value, label]) => ({
  value: value as FirstPartyTopic,
  label,
}));

function errorText(error: string): string {
  const map: Record<string, string> = {
    consent_required: "请先确认知情同意。",
    content_required: "请填写分享内容。",
    content_too_long: "内容最多 200 字。",
    pii_detected: "内容包含可识别信息，请删除姓名、手机号、身份证或 @ 信息。",
    invalid_rating: "请选择 1-5 分评分。",
    invalid_topic: "请选择分享主题。",
    invalid_dimension: "分享主题暂不可提交。",
  };
  return map[error] || error || "提交失败";
}

export default function InsightSubmitForm({ company, onSubmitted }: Props) {
  const [topic, setTopic] = useState<FirstPartyTopic>("culture");
  const [rating, setRating] = useState(4);
  const [content, setContent] = useState("");
  const [consent, setConsent] = useState(false);
  const [bonusMonths, setBonusMonths] = useState("");
  const [interviewRounds, setInterviewRounds] = useState("");
  const [interviewResult, setInterviewResult] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [saving, setSaving] = useState(false);

  const payload = useMemo(() => {
    if (topic === "bonus") {
      return bonusMonths ? { bonus_months: Number(bonusMonths) } : {};
    }
    if (topic === "interview") {
      return Object.fromEntries(
        Object.entries({
          rounds: interviewRounds ? Number(interviewRounds) : undefined,
          result: interviewResult || undefined,
        }).filter(([, value]) => value != null && value !== ""),
      );
    }
    return {};
  }, [bonusMonths, interviewResult, interviewRounds, topic]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/insights/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company,
          dimension: TOPIC_DEFAULT_DIMENSION[topic],
          topic,
          rating,
          content,
          payload,
          consent,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setError(errorText(data.error));
        return;
      }
      setSent(true);
      setContent("");
      setConsent(false);
      onSubmitted?.();
    } catch (err) {
      setError((err as Error).message || "提交失败");
    } finally {
      setSaving(false);
    }
  }

  if (sent) {
    return (
      <div className="rounded-xl border border-tone-green-border bg-tone-green-bg p-4 text-sm leading-6 text-tone-green-fg">
        <span className="inline-flex items-center gap-2 font-semibold">
          <CheckCircle size={17} weight="fill" />
          已提交，审核后匿名展示
        </span>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-black/[0.06] bg-white/55 p-4 text-sm dark:border-white/[0.1] dark:bg-white/[0.05]"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1.5">
          <span className="text-xs font-medium ink-3">主题</span>
          <select
            value={topic}
            onChange={(e) => setTopic(e.target.value as FirstPartyTopic)}
            className={inputCls}
          >
            {TOPIC_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-1.5">
          <span className="text-xs font-medium ink-3">评分</span>
          <div className="grid grid-cols-5 gap-1.5">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRating(value)}
                className={cn(
                  "h-9 rounded-lg border text-sm font-semibold transition",
                  rating === value
                    ? "border-[#1a1714] bg-[#1a1714] text-[#f7f1e6] dark:border-[#f3ecdf] dark:bg-[#f3ecdf] dark:text-[#16130f]"
                    : "border-black/[0.08] bg-white/60 ink-2 hover:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:hover:bg-white/[0.08]",
                )}
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        {topic === "bonus" && (
          <label className="space-y-1.5">
            <span className="text-xs font-medium ink-3">年终奖月数</span>
            <input
              type="number"
              min="0"
              step="0.5"
              value={bonusMonths}
              onChange={(e) => setBonusMonths(e.target.value)}
              className={inputCls}
            />
          </label>
        )}

        {topic === "interview" && (
          <>
            <label className="space-y-1.5">
              <span className="text-xs font-medium ink-3">面试轮数</span>
              <input
                type="number"
                min="1"
                value={interviewRounds}
                onChange={(e) => setInterviewRounds(e.target.value)}
                className={inputCls}
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium ink-3">结果</span>
              <select
                value={interviewResult}
                onChange={(e) => setInterviewResult(e.target.value)}
                className={inputCls}
              >
                <option value="">未填写</option>
                <option value="offer">拿到 offer</option>
                <option value="rejected">未通过</option>
                <option value="pending">等待中</option>
              </select>
            </label>
          </>
        )}

        <label className="space-y-1.5 sm:col-span-2">
          <span className="flex items-center justify-between gap-3 text-xs font-medium ink-3">
            <span>内容</span>
            <span>{content.length}/{FIRST_PARTY_CONTENT_MAX}</span>
          </span>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value.slice(0, FIRST_PARTY_CONTENT_MAX))}
            rows={4}
            placeholder="不写姓名、手机号、身份证或具体个人信息"
            className={inputCls}
          />
        </label>
      </div>

      <label className="mt-3 flex items-start gap-2 text-xs leading-5 ink-2">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5 size-3.5 accent-[#1a1714]"
        />
        我确认这是我的亲身经历、不含他人可识别信息，同意匿名展示。
      </label>

      {error && (
        <p className="mt-3 rounded-lg border border-tone-rose-border bg-tone-rose-bg px-3 py-2 text-xs text-tone-rose-fg">
          {error}
        </p>
      )}

      <div className="mt-4 flex justify-end">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] disabled:opacity-50 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
        >
          <PaperPlaneTilt size={15} weight="bold" />
          {saving ? "提交中…" : "提交"}
        </button>
      </div>
    </form>
  );
}
