"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, PencilSimple, Trash, ArrowCounterClockwise, X, Flag, Warning, Sparkle, CheckCircle, XCircle } from "@phosphor-icons/react";
import { INSIGHT_DIMENSIONS } from "@/lib/insight-bundle";
import { INDUSTRIES } from "@/lib/industries";
import type {
  InsightDimension,
  InsightGrade,
  InsightSource,
  InsightStatus,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface AdminItem {
  id: string;
  company_id: string;
  dimension: InsightDimension;
  grade: InsightGrade;
  title: string | null;
  content: string;
  sample_size: number | null;
  payload: Record<string, unknown>;
  time_window: string | null;
  valid_from: string | null;
  valid_until: string | null;
  deidentified: boolean;
  status: InsightStatus;
  last_verified_at: string;
  sources: InsightSource[];
}
interface AdminCompany {
  id: string;
  company: string;
  display_name: string | null;
  aliases: string[];
  industry: string | null;
}
interface AdminDispute {
  id: string;
  item_id: string;
  reason: string | null;
  contact: string | null;
  status: string;
  created_at: string;
}
interface AdminSubmission {
  id: string;
  company: string;
  company_id: string | null;
  user_id: string;
  dimension: InsightDimension;
  topic: string;
  rating: number | null;
  content: string;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "retired";
  moderation: Record<string, unknown>;
  employment_verified: boolean;
  created_at: string;
  updated_at: string;
}
interface AdminCycle {
  id: string;
  company_id: string;
  grad_class: string;
  season: string;
  batch: string;
  event: string;
  time_expr_type: string;
  value_text: string;
  month_start: number | null;
  month_end: number | null;
  confidence: string | null;
  evidence_url: string | null;
  evidence_excerpt: string | null;
  verify_status: string;
  valid_until: string | null;
  created_by: string | null;
  updated_at: string;
  company_profiles: { company: string; display_name: string | null } | null;
}

const DIM_LABELS: Record<InsightDimension, string> = {
  timing: "招聘时机",
  hiring: "招聘动态",
  listing: "上市 / 股票",
  compensation_intensity: "薪资 / 强度",
  path: "进入路径",
  culture: "公司文化 / 温馨提示",
};
// hiring 是 T1 派生维度（由岗位数据读时算出），不走人工录入
const ADMIN_CREATABLE_DIMENSIONS = INSIGHT_DIMENSIONS.filter((d) => d !== "hiring");
const GRADE_LABELS: Record<InsightGrade, string> = {
  fact: "事实",
  experience: "经验",
  rumor: "传闻",
};
const STATUS_LABELS: Record<string, string> = {
  active: "展示中",
  retired: "已下架",
  disputed: "争议中",
};
const SUBMISSION_TOPIC_LABELS: Record<string, string> = {
  internship: "实习体验",
  onboarding: "入职体验",
  bonus: "年终奖",
  interview: "面试难度",
  promotion: "晋升",
  culture: "文化",
};
const CYCLE_STATUS_LABELS: Record<string, string> = {
  draft: "草稿待核验",
  verified: "已核验展示中",
  rejected: "已驳回",
};
function cycleStatusChip(status: string) {
  if (status === "verified")
    return "border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]";
  if (status === "rejected")
    return "border-[#e0b4ac] bg-[#f7e6e1] text-[#9c4a3c] dark:border-[#7a392e]/[0.60] dark:bg-[#3a201a] dark:text-[#e6a99f]";
  return "border-black/[0.08] bg-[#f4efe6] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]";
}
const GATE_HELP: Record<string, string> = {
  deidentified: "去标识门未过：请勾选「已去标识」，且每个来源也必须勾选「已去标识」。",
  grade:
    "分级门未过：fact 至少 1 个有效来源；experience 需样本量 ≥5 且 ≥2 个不同来源 publisher。",
  assertion:
    "归因门未过：experience 正文须含归因措辞（据 / 根据 / 反馈 / 公开…），且不得用产品口吻断言。",
  time_window: "时效门未过：请至少填写「时间窗口」或「有效期至」其一。",
};

type SourceDraft = {
  url: string;
  publisher: string;
  source_kind: string;
  excerpt: string;
  deidentified: boolean;
};
type FormState = {
  id: string | null;
  company: string;
  industry: string;
  dimension: InsightDimension;
  grade: InsightGrade;
  title: string;
  content: string;
  sample_size: string;
  time_window: string;
  valid_until: string;
  deidentified: boolean;
  status: InsightStatus;
  sources: SourceDraft[];
  // listing 维度专属：上市状态 + 交易所 + 代码 + 行情页链接（写进 payload）
  listing_status: string;
  exchange: string;
  ticker: string;
  quote_url: string;
};

const EMPTY_FORM: FormState = {
  id: null,
  company: "",
  industry: "",
  dimension: "timing",
  grade: "fact",
  title: "",
  content: "",
  sample_size: "",
  time_window: "",
  valid_until: "",
  deidentified: true,
  status: "active",
  sources: [{ url: "", publisher: "", source_kind: "official_site", excerpt: "", deidentified: true }],
  listing_status: "listed",
  exchange: "",
  ticker: "",
  quote_url: "",
};

const inputCls =
  "w-full rounded-lg border border-black/[0.09] bg-white/70 px-3 py-2 text-sm text-[#1a1714] outline-none placeholder:text-[#a39a8c] focus:border-[#1a1714]/55 focus:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#f3ecdf] dark:placeholder:text-[#8b8478] dark:focus:border-white/40 dark:focus:bg-[#1e1a15]";

// 从 payload 安全取字符串字段
function pstr(payload: Record<string, unknown> | null | undefined, key: string): string {
  const v = payload?.[key];
  return typeof v === "string" ? v : "";
}

export default function InsightsAdminClient() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [companies, setCompanies] = useState<AdminCompany[]>([]);
  const [items, setItems] = useState<AdminItem[]>([]);
  const [disputes, setDisputes] = useState<AdminDispute[]>([]);
  const [submissions, setSubmissions] = useState<AdminSubmission[]>([]);
  const [cycles, setCycles] = useState<AdminCycle[]>([]);

  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [formOpen, setFormOpen] = useState(false);
  const [formError, setFormError] = useState("");
  const [formGate, setFormGate] = useState("");
  const [saving, setSaving] = useState(false);
  const [aiDrafting, setAiDrafting] = useState(false);
  const [busyId, setBusyId] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [res, submissionsRes, cyclesRes] = await Promise.all([
        fetch("/api/insights/admin"),
        fetch("/api/insights/admin/submissions"),
        fetch("/api/insights/admin/cycles"),
      ]);
      const data = await res.json();
      const submissionsData = await submissionsRes.json();
      const cyclesData = await cyclesRes.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "加载失败");
      if (!submissionsRes.ok || !submissionsData.ok) {
        throw new Error(submissionsData.error || "待审提交加载失败");
      }
      if (!cyclesRes.ok || !cyclesData.ok) {
        throw new Error(cyclesData.error || "招聘周期加载失败");
      }
      setCompanies(data.companies || []);
      setItems(data.items || []);
      setDisputes(data.disputes || []);
      setSubmissions(submissionsData.submissions || []);
      setCycles(cyclesData.cycles || []);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const companyById = useMemo(() => {
    const m = new Map<string, AdminCompany>();
    for (const c of companies) m.set(c.id, c);
    return m;
  }, [companies]);
  const itemById = useMemo(() => {
    const m = new Map<string, AdminItem>();
    for (const it of items) m.set(it.id, it);
    return m;
  }, [items]);

  // 按公司分组（公司名取画像；找不到则用占位）
  const grouped = useMemo(() => {
    const groups = new Map<string, { name: string; items: AdminItem[] }>();
    for (const it of items) {
      const c = companyById.get(it.company_id);
      const name = c?.display_name || c?.company || "（未知公司）";
      const g = groups.get(it.company_id) || { name, items: [] };
      g.items.push(it);
      groups.set(it.company_id, g);
    }
    return Array.from(groups.values()).sort((a, b) => a.name.localeCompare(b.name, "zh"));
  }, [items, companyById]);

  // 行业覆盖 worklist：每个行业下的公司 + 已录入洞察数（缺口一目了然，点击直接补录）
  const industryCoverage = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of items) counts.set(it.company_id, (counts.get(it.company_id) || 0) + 1);
    const byIndustry = new Map<string, { company: string; count: number }[]>();
    for (const c of companies) {
      const ind = c.industry || "未分类";
      const list = byIndustry.get(ind) || [];
      list.push({ company: c.display_name || c.company, count: counts.get(c.id) || 0 });
      byIndustry.set(ind, list);
    }
    return Array.from(byIndustry.entries())
      .map(([industry, comps]) => ({
        industry,
        companies: comps.sort((a, b) => b.count - a.count),
        withInsights: comps.filter((x) => x.count > 0).length,
        total: comps.length,
      }))
      .sort((a, b) => b.total - a.total);
  }, [companies, items]);

  function openCreateFor(company: string, industry: string) {
    setForm({
      ...EMPTY_FORM,
      company,
      industry: industry === "未分类" ? "" : industry,
      sources: [{ ...EMPTY_FORM.sources[0] }],
    });
    setFormError("");
    setFormGate("");
    setFormOpen(true);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openCreate() {
    setForm({ ...EMPTY_FORM, sources: [{ ...EMPTY_FORM.sources[0] }] });
    setFormError("");
    setFormGate("");
    setFormOpen(true);
  }

  function openEdit(it: AdminItem) {
    const c = companyById.get(it.company_id);
    setForm({
      id: it.id,
      company: c?.company || "",
      industry: c?.industry || "",
      dimension: it.dimension,
      grade: it.grade,
      title: it.title || "",
      content: it.content,
      sample_size: it.sample_size != null ? String(it.sample_size) : "",
      time_window: it.time_window || "",
      valid_until: it.valid_until || "",
      deidentified: it.deidentified,
      status: it.status,
      sources: it.sources.length
        ? it.sources.map((s) => ({
            url: s.url,
            publisher: s.publisher || "",
            source_kind: s.source_kind || "official_site",
            excerpt: s.excerpt || "",
            deidentified: s.deidentified,
          }))
        : [{ ...EMPTY_FORM.sources[0] }],
      listing_status: pstr(it.payload, "status") || "listed",
      exchange: pstr(it.payload, "exchange"),
      ticker: pstr(it.payload, "ticker"),
      quote_url: pstr(it.payload, "quote_url"),
    });
    setFormError("");
    setFormGate("");
    setFormOpen(true);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }
  function setSource(i: number, patch: Partial<SourceDraft>) {
    setForm((prev) => ({
      ...prev,
      sources: prev.sources.map((s, idx) => (idx === i ? { ...s, ...patch } : s)),
    }));
  }
  function addSource() {
    setForm((prev) => ({
      ...prev,
      sources: [...prev.sources, { url: "", publisher: "", source_kind: "public_aggregate", excerpt: "", deidentified: true }],
    }));
  }
  function removeSource(i: number) {
    setForm((prev) => ({ ...prev, sources: prev.sources.filter((_, idx) => idx !== i) }));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setFormError("");
    setFormGate("");
    try {
      // listing 维度：把上市状态/交易所/代码/行情页拼进 insight payload（其他维度不带）
      const insightPayload: Record<string, string> =
        form.dimension === "listing"
          ? Object.fromEntries(
              Object.entries({
                status: form.listing_status.trim(),
                exchange: form.exchange.trim(),
                ticker: form.ticker.trim(),
                quote_url: form.quote_url.trim(),
              }).filter(([, v]) => v),
            )
          : {};
      const payload = {
        id: form.id,
        company: form.company,
        industry: form.industry,
        dimension: form.dimension,
        grade: form.grade,
        title: form.title,
        content: form.content,
        sample_size: form.sample_size,
        time_window: form.time_window,
        valid_until: form.valid_until,
        deidentified: form.deidentified,
        status: form.status,
        payload: insightPayload,
        sources: form.sources.filter((s) => s.url.trim()),
      };
      const res = await fetch("/api/insights/admin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        if (data.gate && GATE_HELP[data.gate]) setFormGate(GATE_HELP[data.gate]);
        setFormError(
          data.error === "validation_failed"
            ? "未通过校验门，请按提示修正后再保存。"
            : data.error === "missing_required_fields"
              ? "公司、维度、分级、正文为必填。"
              : data.error || "保存失败",
        );
        return;
      }
      setFormOpen(false);
      await load();
    } catch (err) {
      setFormError((err as Error).message || "保存失败");
    } finally {
      setSaving(false);
    }
  }

  // AI 起草：用 company + dimension 让模型出草稿回填表单。仅辅助，必须人工核对 + 补真实来源后才能展示，
  // 故强制 status=retired（草稿态，不过校验门）。账单走 admin 手动点击、单次调用。
  async function aiDraft() {
    if (!form.company.trim()) {
      setFormError("请先填公司名再用 AI 起草。");
      return;
    }
    setAiDrafting(true);
    setFormError("");
    try {
      const res = await fetch("/api/insights/admin/ai-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company: form.company, dimension: form.dimension }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setFormError(
          data.error === "llm_not_configured"
            ? "未配置 SILICONFLOW_API_KEY，无法用 AI 起草。"
            : `AI 起草失败：${data.error || res.status}`,
        );
        return;
      }
      const d = data.draft || {};
      const listing = d.listing && typeof d.listing === "object" ? d.listing : {};
      setForm((prev) => ({
        ...prev,
        title: typeof d.title === "string" ? d.title : prev.title,
        content: typeof d.content === "string" ? d.content : prev.content,
        grade: d.grade === "experience" ? "experience" : d.grade === "fact" ? "fact" : prev.grade,
        time_window: typeof d.time_window === "string" ? d.time_window : prev.time_window,
        sample_size:
          d.sample_size === "" || d.sample_size == null ? prev.sample_size : String(d.sample_size),
        listing_status: typeof listing.status === "string" ? listing.status : prev.listing_status,
        exchange: typeof listing.exchange === "string" ? listing.exchange : prev.exchange,
        ticker: typeof listing.ticker === "string" ? listing.ticker : prev.ticker,
        // 草稿态：必须人工核对 + 补真实来源后再改 active
        status: "retired",
      }));
      setFormError("已生成 AI 草稿，请核对正文、补充真实来源，确认无误后把状态改为「展示中」再保存。");
    } catch (err) {
      setFormError(`AI 起草失败：${(err as Error).message}`);
    } finally {
      setAiDrafting(false);
    }
  }

  async function setStatus(it: AdminItem, status: InsightStatus) {
    setBusyId(it.id);
    try {
      const res = await fetch("/api/insights/admin", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: it.id, status }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        alert(
          data.gate && GATE_HELP[data.gate]
            ? `无法上架：${GATE_HELP[data.gate]}`
            : data.error || "操作失败",
        );
        return;
      }
      await load();
    } finally {
      setBusyId("");
    }
  }

  async function resolveDispute(d: AdminDispute, resolution: "upheld" | "rejected") {
    setBusyId(d.id);
    try {
      const res = await fetch("/api/insights/dispute/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dispute_id: d.id, resolution }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        alert(data.error || "操作失败");
        return;
      }
      await load();
    } finally {
      setBusyId("");
    }
  }

  async function reviewSubmission(submission: AdminSubmission, status: "approved" | "rejected") {
    setBusyId(submission.id);
    try {
      const res = await fetch("/api/insights/admin/submissions", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: submission.id, status }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        alert(data.error || "操作失败");
        return;
      }
      await load();
    } finally {
      setBusyId("");
    }
  }

  async function setCycleStatus(id: string, verify_status: "verified" | "rejected") {
    setBusyId(id);
    try {
      const res = await fetch("/api/insights/admin/cycles", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, verify_status }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        alert(data.error || "操作失败");
        return;
      }
      await load();
    } finally {
      setBusyId("");
    }
  }

  async function submitCycle(form: Record<string, any>) {
    const res = await fetch("/api/insights/admin/cycles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      alert(data.error || "提交失败");
      return;
    }
    await load();
  }

  if (loading) return <p className="mt-8 text-sm text-[#8a8275] dark:text-[#9a9184]">正在加载洞察后台…</p>;
  if (error)
    return (
      <p className="mt-8 rounded-xl border border-black/[0.06] bg-white/55 p-4 text-sm text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
        {error}
      </p>
    );

  return (
    <div className="mt-8 space-y-8 text-[#1a1714] dark:text-[#f3ecdf]">
      <div className="flex flex-wrap items-center gap-3">
        {!formOpen && (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] active:scale-[0.98] dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
          >
            <Plus size={16} weight="bold" /> 新增洞察条目
          </button>
        )}
        <span className="text-sm text-[#8a8275] dark:text-[#9a9184]">
          共 {items.length} 条洞察 · {companies.length} 家公司 · {submissions.length} 条待审提交 · {disputes.length} 条待处理申诉
        </span>
      </div>

      {formOpen && (
        <ItemForm
          form={form}
          companies={companies}
          formError={formError}
          formGate={formGate}
          saving={saving}
          aiDrafting={aiDrafting}
          setField={setField}
          setSource={setSource}
          addSource={addSource}
          removeSource={removeSource}
          onSubmit={save}
          onAiDraft={aiDraft}
          onCancel={() => setFormOpen(false)}
        />
      )}

      {/* 待审第一方提交 */}
      {submissions.length > 0 && (
        <section>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#2f8a63] dark:text-[#6cc99e]">
            <CheckCircle size={16} weight="fill" /> 待审提交（{submissions.length}）
          </h2>
          <div className="space-y-3">
            {submissions.map((submission) => (
              <SubmissionRow
                key={submission.id}
                submission={submission}
                busy={busyId === submission.id}
                onApprove={() => reviewSubmission(submission, "approved")}
                onReject={() => reviewSubmission(submission, "rejected")}
              />
            ))}
          </div>
        </section>
      )}

      {/* 待处理申诉 */}
      {disputes.length > 0 && (
        <section>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#9a6a2a] dark:text-[#e0b15a]">
            <Flag size={16} weight="fill" /> 待处理申诉（{disputes.length}）
          </h2>
          <div className="space-y-3">
            {disputes.map((d) => {
              const it = itemById.get(d.item_id);
              return (
                <article
                  key={d.id}
                  className="rounded-xl border border-[#e7c98a] bg-[#fbf2d8] p-4 text-sm dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15]"
                >
                  <p className="text-[#1a1714] dark:text-[#f3ecdf]">
                    {it ? (
                      <>
                        <span className="font-medium">
                          {companyById.get(it.company_id)?.display_name ||
                            companyById.get(it.company_id)?.company}
                        </span>{" "}
                        · {DIM_LABELS[it.dimension]} · {it.title || it.content.slice(0, 24)}
                      </>
                    ) : (
                      <span className="text-[#8a8275] dark:text-[#9a9184]">条目已不存在（item_id: {d.item_id.slice(0, 8)}）</span>
                    )}
                  </p>
                  {it && <p className="mt-1 leading-6 text-[#5f594e] dark:text-[#b6ad9d]">{it.content}</p>}
                  <p className="mt-2 text-xs text-[#8a8275] dark:text-[#9a9184]">
                    申诉理由：{d.reason || "（未填写）"} · {new Date(d.created_at).toLocaleString("zh-CN")}
                  </p>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      disabled={busyId === d.id}
                      onClick={() => resolveDispute(d, "upheld")}
                      className="inline-flex items-center gap-1.5 rounded-full bg-[#1a1714] px-3 py-1.5 text-xs font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] disabled:opacity-50 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
                    >
                      <Trash size={13} weight="bold" /> 成立并下架
                    </button>
                    <button
                      type="button"
                      disabled={busyId === d.id}
                      onClick={() => resolveDispute(d, "rejected")}
                      className="rounded-full border border-black/[0.1] px-3 py-1.5 text-xs font-medium text-[#5f594e] transition hover:bg-black/[0.05] hover:text-[#1a1714] disabled:opacity-50 dark:border-white/[0.1] dark:text-[#b6ad9d] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]"
                    >
                      驳回
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {/* 招聘周期（据往年 · 校招洞察 P2）：新表结构化事实，独立于上面的 insight_items 洞察条目 */}
      <section>
        <h2 className="mb-3 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">
          招聘周期（据往年 · 校招洞察 P2，{cycles.length} 条观测）
        </h2>
        <div className="space-y-4">
          <CycleForm companies={companies} onSubmit={submitCycle} />
          <div className="space-y-2.5">
            {cycles.map((c) => (
              <CycleRow
                key={c.id}
                cycle={c}
                busy={busyId === c.id}
                onVerify={() => setCycleStatus(c.id, "verified")}
                onReject={() => setCycleStatus(c.id, "rejected")}
              />
            ))}
            {cycles.length === 0 && (
              <p className="rounded-xl border border-black/[0.06] bg-white/55 p-4 text-sm text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
                还没有任何招聘周期观测。用上面的表单新增。
              </p>
            )}
          </div>
        </div>
      </section>

      {/* 行业覆盖 worklist：按行业看缺口，点公司直接补录 */}
      {companies.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">
            行业覆盖（{companies.length} 家公司 · 绿色=已录入，灰色=待补全，点公司直接补录）
          </h2>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {industryCoverage.map((g) => (
              <div key={g.industry} className="surface-soft p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-[#1a1714] dark:text-[#f3ecdf]">{g.industry}</span>
                  <span
                    className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 text-[11px]",
                      g.withInsights ? "bg-[#e6f2d6] text-[#4f6f2a] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]" : "bg-[#f4efe6] text-[#8a8275] dark:bg-white/[0.08] dark:text-[#9a9184]",
                    )}
                  >
                    已录入 {g.withInsights}/{g.total}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {g.companies.map((c) => (
                    <button
                      key={c.company}
                      type="button"
                      onClick={() => openCreateFor(c.company, g.industry)}
                      title={c.count > 0 ? `${c.count} 条洞察 · 点击新增` : "待补全 · 点击新增"}
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[11px] transition",
                        c.count > 0
                          ? "border-[#cfe6b0] bg-[#eef6e0] text-[#4f6f2a] hover:bg-[#e2efce] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a] dark:hover:bg-[#a3d06a]/[0.25]"
                          : "border-black/[0.08] bg-white/60 text-[#8a8275] hover:bg-white hover:text-[#1a1714] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#9a9184] dark:hover:bg-[#1e1a15] dark:hover:text-[#f3ecdf]",
                      )}
                    >
                      {c.company}
                      {c.count > 0 ? ` ·${c.count}` : ""}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 全部条目（按公司分组） */}
      <section className="space-y-6">
        {grouped.map((g) => (
          <div key={g.name}>
            <h3 className="mb-2 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">{g.name}</h3>
            <div className="space-y-2.5">
              {g.items.map((it) => (
                <ItemRow
                  key={it.id}
                  item={it}
                  busy={busyId === it.id}
                  onEdit={() => openEdit(it)}
                  onRetire={() => setStatus(it, "retired")}
                  onActivate={() => setStatus(it, "active")}
                />
              ))}
            </div>
          </div>
        ))}
        {grouped.length === 0 && (
          <p className="rounded-xl border border-black/[0.06] bg-white/55 p-4 text-sm text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
            还没有任何洞察条目。点「新增洞察条目」开始录入。
          </p>
        )}
      </section>
    </div>
  );
}

function SubmissionRow({
  submission,
  busy,
  onApprove,
  onReject,
}: {
  submission: AdminSubmission;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <article className="rounded-xl border border-[#a9d8c4] bg-[#dcf2e8] p-4 text-sm dark:border-[#6cc99e]/[0.30] dark:bg-[#6cc99e]/[0.15]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{submission.company}</span>
        <span className="rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
          {DIM_LABELS[submission.dimension]}
        </span>
        <span className="rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
          {SUBMISSION_TOPIC_LABELS[submission.topic] || submission.topic}
        </span>
        {submission.rating != null && (
          <span className="rounded-full border border-[#e7c98a] bg-[#fbeecb] px-2 py-0.5 text-[11px] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]">
            {submission.rating}/5
          </span>
        )}
        <span className="ml-auto text-[11px] text-[#8a8275] dark:text-[#9a9184]">
          {new Date(submission.created_at).toLocaleString("zh-CN")}
        </span>
      </div>
      <p className="mt-2 leading-6 text-[#3f3a33] dark:text-[#d9d0c2]">{submission.content}</p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onApprove}
          className="inline-flex items-center gap-1.5 rounded-full bg-[#1a1714] px-3 py-1.5 text-xs font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] disabled:opacity-50 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
        >
          <CheckCircle size={13} weight="bold" /> 通过
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onReject}
          className="inline-flex items-center gap-1.5 rounded-full border border-black/[0.1] px-3 py-1.5 text-xs font-medium text-[#5f594e] transition hover:bg-black/[0.05] hover:text-[#1a1714] disabled:opacity-50 dark:border-white/[0.1] dark:text-[#b6ad9d] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]"
        >
          <XCircle size={13} weight="bold" /> 拒绝
        </button>
      </div>
    </article>
  );
}

function statusChip(status: string) {
  if (status === "active") return "border-[#bcdcae] bg-[#e6f2d6] text-[#4f6f2a] dark:border-[#a3d06a]/[0.30] dark:bg-[#a3d06a]/[0.15] dark:text-[#a3d06a]";
  if (status === "disputed") return "border-[#e7c98a] bg-[#fbeecb] text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]";
  return "border-black/[0.08] bg-[#f4efe6] text-[#8a8275] dark:border-white/[0.1] dark:bg-white/[0.08] dark:text-[#9a9184]";
}

function ItemRow({
  item,
  busy,
  onEdit,
  onRetire,
  onActivate,
}: {
  item: AdminItem;
  busy: boolean;
  onEdit: () => void;
  onRetire: () => void;
  onActivate: () => void;
}) {
  return (
    <article className="surface-soft p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
          {DIM_LABELS[item.dimension]}
        </span>
        <span className="rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
          {GRADE_LABELS[item.grade]}
        </span>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", statusChip(item.status))}>
          {STATUS_LABELS[item.status] || item.status}
        </span>
        {!item.deidentified && (
          <span className="inline-flex items-center gap-1 rounded-full border border-[#e0b4ac] bg-[#f7e6e1] px-2 py-0.5 text-[11px] text-[#9c4a3c] dark:border-[#7a392e]/[0.60] dark:bg-[#3a201a] dark:text-[#e6a99f]">
            <Warning size={11} weight="fill" /> 未去标识
          </span>
        )}
        <div className="ml-auto flex gap-1.5">
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[#5f594e] transition hover:bg-black/[0.05] hover:text-[#1a1714] dark:text-[#b6ad9d] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]"
          >
            <PencilSimple size={13} /> 编辑
          </button>
          {item.status === "active" ? (
            <button
              type="button"
              disabled={busy}
              onClick={onRetire}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[#5f594e] transition hover:bg-black/[0.05] hover:text-[#1a1714] disabled:opacity-50 dark:text-[#b6ad9d] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]"
            >
              <Trash size={13} /> 下架
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={onActivate}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[#4f6f2a] transition hover:bg-black/[0.05] hover:text-[#3f5a1c] disabled:opacity-50 dark:text-[#a3d06a] dark:hover:bg-white/[0.05] dark:hover:text-[#b8dd85]"
            >
              <ArrowCounterClockwise size={13} /> 上架
            </button>
          )}
        </div>
      </div>
      {item.title && <p className="mt-2 font-semibold text-[#1a1714] dark:text-[#f3ecdf]">{item.title}</p>}
      <p className="mt-1 leading-6 text-[#3f3a33] dark:text-[#d9d0c2]">{item.content}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#8a8275] dark:text-[#9a9184]">
        {item.sample_size != null && <span>样本 {item.sample_size}</span>}
        {item.time_window && <span>{item.time_window}</span>}
        {item.valid_until && <span>有效期至 {item.valid_until}</span>}
        {item.sources.length > 0 && <span>来源 {item.sources.length} 条</span>}
      </div>
    </article>
  );
}

function ItemForm({
  form,
  companies,
  formError,
  formGate,
  saving,
  aiDrafting,
  setField,
  setSource,
  addSource,
  removeSource,
  onSubmit,
  onAiDraft,
  onCancel,
}: {
  form: FormState;
  companies: AdminCompany[];
  formError: string;
  formGate: string;
  saving: boolean;
  aiDrafting: boolean;
  setField: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  setSource: (i: number, patch: Partial<SourceDraft>) => void;
  addSource: () => void;
  removeSource: (i: number) => void;
  onSubmit: (e: React.FormEvent) => void;
  onAiDraft: () => void;
  onCancel: () => void;
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="surface p-5 text-[#1a1714] dark:text-[#f3ecdf]"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{form.id ? "编辑洞察条目" : "新增洞察条目"}</h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onAiDraft}
            disabled={aiDrafting}
            title="用 AI 按公司+维度生成草稿（仅辅助，需人工核对+补来源）"
            className="inline-flex items-center gap-1.5 rounded-full border border-[#b7d2ee] bg-[#dceafa] px-3 py-1.5 text-[12px] font-semibold text-[#2f6299] transition hover:bg-[#cfe2f7] disabled:opacity-50 dark:border-[#7fb2e8]/[0.30] dark:bg-[#7fb2e8]/[0.15] dark:text-[#7fb2e8] dark:hover:bg-[#7fb2e8]/[0.25]"
          >
            <Sparkle size={13} weight="fill" />
            {aiDrafting ? "AI 起草中…" : "AI 起草"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full bg-black/[0.05] p-1.5 text-[#5f594e] transition hover:bg-black/[0.08] hover:text-[#1a1714] dark:bg-white/[0.05] dark:text-[#b6ad9d] dark:hover:bg-white/[0.08] dark:hover:text-[#f3ecdf]"
          >
            <X size={16} weight="bold" />
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <FormField label="公司（用画像里的标准名，如「字节跳动」）">
          <input
            list="insight-companies"
            value={form.company}
            onChange={(e) => setField("company", e.target.value)}
            placeholder="字节跳动"
            className={inputCls}
          />
          <datalist id="insight-companies">
            {companies.map((c) => (
              <option key={c.id} value={c.company} />
            ))}
          </datalist>
        </FormField>

        <FormField label="行业（选填，便于按行业组织 / 补全覆盖）">
          <input
            list="insight-industries"
            value={form.industry}
            onChange={(e) => setField("industry", e.target.value)}
            placeholder="如 金融 / 制造/工业"
            className={inputCls}
          />
          <datalist id="insight-industries">
            {INDUSTRIES.map((ind) => (
              <option key={ind} value={ind} />
            ))}
          </datalist>
        </FormField>

        <FormField label="维度">
          <select value={form.dimension} onChange={(e) => setField("dimension", e.target.value as InsightDimension)} className={inputCls}>
            {ADMIN_CREATABLE_DIMENSIONS.map((d) => (
              <option key={d} value={d}>
                {DIM_LABELS[d]}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="分级">
          <select value={form.grade} onChange={(e) => setField("grade", e.target.value as InsightGrade)} className={inputCls}>
            <option value="fact">事实（须带来源）</option>
            <option value="experience">经验（样本≥5 且多源）</option>
            <option value="rumor">传闻（默认拦截，不展示）</option>
          </select>
        </FormField>

        <FormField label="状态">
          <select value={form.status} onChange={(e) => setField("status", e.target.value as InsightStatus)} className={inputCls}>
            <option value="active">展示中（须过校验门）</option>
            <option value="retired">已下架（存草稿，不校验）</option>
            <option value="disputed">争议中</option>
          </select>
        </FormField>

        <FormField label="标题（选填）" className="sm:col-span-2">
          <input value={form.title} onChange={(e) => setField("title", e.target.value)} placeholder="如「校招节奏：秋招为主」" className={inputCls} />
        </FormField>

        <FormField label="正文（归因式，如「据公开讨论，…」）" className="sm:col-span-2">
          <textarea
            value={form.content}
            onChange={(e) => setField("content", e.target.value)}
            rows={3}
            placeholder="据公开讨论，…仅供参考。"
            className={inputCls}
          />
        </FormField>

        <FormField label="样本量（experience 需 ≥5）">
          <input
            type="number"
            value={form.sample_size}
            onChange={(e) => setField("sample_size", e.target.value)}
            placeholder="如 12"
            className={inputCls}
          />
        </FormField>

        <FormField label="时间窗口（time_window）">
          <input
            value={form.time_window}
            onChange={(e) => setField("time_window", e.target.value)}
            placeholder="如「每年 8–10 月（秋招）」"
            className={inputCls}
          />
        </FormField>

        <FormField label="有效期至（valid_until，选填）">
          <input type="date" value={form.valid_until} onChange={(e) => setField("valid_until", e.target.value)} className={inputCls} />
        </FormField>

        <FormField label="去标识">
          <label className="inline-flex items-center gap-2 text-sm text-[#5f594e] dark:text-[#b6ad9d]">
            <input
              type="checkbox"
              checked={form.deidentified}
              onChange={(e) => setField("deidentified", e.target.checked)}
              className="size-4 accent-[#1a1714]"
            />
            内容已去标识，不指向具体个人
          </label>
        </FormField>

        {form.dimension === "listing" && (
          <>
            <FormField label="上市状态">
              <select
                value={form.listing_status}
                onChange={(e) => setField("listing_status", e.target.value)}
                className={inputCls}
              >
                <option value="listed">已上市</option>
                <option value="filed">已递交招股书</option>
                <option value="pre_ipo">筹备上市</option>
                <option value="private">未上市（暂无计划）</option>
              </select>
            </FormField>
            <FormField label="交易所（如 港交所 / 纳斯达克）">
              <input value={form.exchange} onChange={(e) => setField("exchange", e.target.value)} placeholder="港交所" className={inputCls} />
            </FormField>
            <FormField label="股票代码（如 0700.HK）">
              <input value={form.ticker} onChange={(e) => setField("ticker", e.target.value)} placeholder="0700.HK" className={inputCls} />
            </FormField>
            <FormField label="行情页链接（公开，易变数据不落库为数字）">
              <input value={form.quote_url} onChange={(e) => setField("quote_url", e.target.value)} placeholder="https://…（雪球 / 交易所行情页）" className={inputCls} />
            </FormField>
          </>
        )}
      </div>

      {/* 来源 */}
      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">来源（链接 + 短摘要，禁整段原文）</span>
          <button type="button" onClick={addSource} className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[#2f6299] transition hover:bg-black/[0.05] dark:text-[#7fb2e8] dark:hover:bg-white/[0.05]">
            <Plus size={12} weight="bold" /> 加一条来源
          </button>
        </div>
        <div className="space-y-3">
          {form.sources.map((s, i) => (
            <div key={i} className="rounded-lg border border-black/[0.06] bg-white/55 p-3 dark:border-white/[0.1] dark:bg-white/[0.05]">
              <div className="grid gap-2.5 sm:grid-cols-2">
                <input value={s.url} onChange={(e) => setSource(i, { url: e.target.value })} placeholder="https://…" className={inputCls} />
                <input value={s.publisher} onChange={(e) => setSource(i, { publisher: e.target.value })} placeholder="来源名，如「界面新闻」" className={inputCls} />
                <select value={s.source_kind} onChange={(e) => setSource(i, { source_kind: e.target.value })} className={inputCls}>
                  <option value="official_filing">官方披露 / 财报</option>
                  <option value="official_site">官方网站</option>
                  <option value="campus_announcement">校招公告</option>
                  <option value="public_aggregate">公开聚合报道</option>
                  <option value="community_deidentified">社区（去标识）</option>
                </select>
                <input value={s.excerpt} onChange={(e) => setSource(i, { excerpt: e.target.value })} placeholder="短摘要（选填）" className={inputCls} />
              </div>
              <div className="mt-2 flex items-center justify-between">
                <label className="inline-flex items-center gap-2 text-xs text-[#5f594e] dark:text-[#b6ad9d]">
                  <input type="checkbox" checked={s.deidentified} onChange={(e) => setSource(i, { deidentified: e.target.checked })} className="size-3.5 accent-[#1a1714]" />
                  已去标识
                </label>
                {form.sources.length > 1 && (
                  <button type="button" onClick={() => removeSource(i)} className="text-[11px] text-[#9a9184] transition hover:text-[#9c4a3c] dark:text-[#837c70] dark:hover:text-[#e6a99f]">
                    删除
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {formGate && (
        <p className="mt-4 rounded-lg border border-[#e7c98a] bg-[#fbf2d8] px-3 py-2 text-xs leading-5 text-[#8a6312] dark:border-[#e0b15a]/[0.30] dark:bg-[#e0b15a]/[0.15] dark:text-[#e0b15a]">
          {formGate}
        </p>
      )}
      {formError && (
        <p className="mt-3 rounded-lg border border-[#e0b4ac] bg-[#f7e6e1] px-3 py-2 text-sm text-[#9c4a3c] dark:border-[#7a392e]/[0.60] dark:bg-[#3a201a] dark:text-[#e6a99f]">{formError}</p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] active:scale-[0.98] disabled:opacity-50 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
        >
          {saving ? "保存中…" : form.id ? "保存修改" : "创建条目"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-full px-4 py-2 text-sm font-medium text-[#8a8275] transition hover:bg-black/[0.05] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]">
          取消
        </button>
      </div>
    </form>
  );
}

function FormField({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={className}>
      <label className="mb-1.5 block text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">{label}</label>
      {children}
    </div>
  );
}

type CycleFormState = {
  company_id: string;
  grad_class: string;
  season: string;
  batch: string;
  event: string;
  time_expr_type: string;
  value_text: string;
  month_start: string;
  month_end: string;
  confidence: string;
  evidence_url: string;
  evidence_excerpt: string;
  valid_until: string;
  verify_status: string;
};

const EMPTY_CYCLE_FORM: CycleFormState = {
  company_id: "",
  grad_class: "2027届",
  season: "秋招",
  batch: "提前批",
  event: "开放",
  time_expr_type: "历史规律",
  value_text: "",
  month_start: "",
  month_end: "",
  confidence: "medium",
  evidence_url: "",
  evidence_excerpt: "",
  valid_until: "",
  verify_status: "draft",
};

function CycleForm({
  companies,
  onSubmit,
}: {
  companies: AdminCompany[];
  onSubmit: (form: Record<string, any>) => Promise<void>;
}) {
  const [form, setForm] = useState<CycleFormState>({ ...EMPTY_CYCLE_FORM });
  const [submitting, setSubmitting] = useState(false);

  function setField<K extends keyof CycleFormState>(key: K, value: CycleFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.company_id || !form.grad_class.trim() || !form.value_text.trim()) {
      alert("公司、毕业届别、展示串为必填");
      return;
    }
    setSubmitting(true);
    try {
      // 空串月份要转 undefined 再提交，否则会撞 validateCycleInput 的 badMonth 类型判定（"" 不是 number）
      await onSubmit({
        company_id: form.company_id,
        grad_class: form.grad_class.trim(),
        season: form.season,
        batch: form.batch,
        event: form.event,
        time_expr_type: form.time_expr_type,
        value_text: form.value_text.trim(),
        month_start: form.month_start === "" ? undefined : Number(form.month_start),
        month_end: form.month_end === "" ? undefined : Number(form.month_end),
        confidence: form.confidence,
        evidence_url: form.evidence_url.trim(),
        evidence_excerpt: form.evidence_excerpt.trim(),
        valid_until: form.valid_until || undefined,
        verify_status: form.verify_status,
      });
      setForm({ ...EMPTY_CYCLE_FORM, company_id: form.company_id });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="surface p-5 text-[#1a1714] dark:text-[#f3ecdf]">
      <h3 className="text-base font-semibold">新增招聘周期观测</h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <FormField label="公司">
          <select value={form.company_id} onChange={(e) => setField("company_id", e.target.value)} className={inputCls}>
            <option value="">选择公司…</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.display_name || c.company}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="毕业届别（如「2027届」，据往年必绑此）">
          <input value={form.grad_class} onChange={(e) => setField("grad_class", e.target.value)} placeholder="2027届" className={inputCls} />
        </FormField>
        <FormField label="季">
          <select value={form.season} onChange={(e) => setField("season", e.target.value)} className={inputCls}>
            <option value="秋招">秋招</option>
            <option value="春招">春招</option>
          </select>
        </FormField>
        <FormField label="批次">
          <select value={form.batch} onChange={(e) => setField("batch", e.target.value)} className={inputCls}>
            <option value="提前批">提前批</option>
            <option value="正式批">正式批</option>
            <option value="补录">补录</option>
            <option value="实习转正">实习转正</option>
          </select>
        </FormField>
        <FormField label="事件">
          <select value={form.event} onChange={(e) => setField("event", e.target.value)} className={inputCls}>
            <option value="开放">开放</option>
            <option value="黄金期">黄金期</option>
            <option value="截止">截止</option>
            <option value="结束">结束</option>
          </select>
        </FormField>
        <FormField label="时间表达类型">
          <select value={form.time_expr_type} onChange={(e) => setField("time_expr_type", e.target.value)} className={inputCls}>
            <option value="历史规律">历史规律</option>
            <option value="月">月</option>
            <option value="日期范围">日期范围</option>
            <option value="精确日期">精确日期（须带证据链接）</option>
          </select>
        </FormField>
        <FormField label="展示串（如「约7月」「8-9月」）">
          <input value={form.value_text} onChange={(e) => setField("value_text", e.target.value)} placeholder="约7月" className={inputCls} />
        </FormField>
        <FormField label="起始月（1-12，选填）">
          <input
            type="number"
            min={1}
            max={12}
            value={form.month_start}
            onChange={(e) => setField("month_start", e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label="结束月（1-12，选填）">
          <input
            type="number"
            min={1}
            max={12}
            value={form.month_end}
            onChange={(e) => setField("month_end", e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label="置信度">
          <select value={form.confidence} onChange={(e) => setField("confidence", e.target.value)} className={inputCls}>
            <option value="high">高</option>
            <option value="medium">中</option>
            <option value="low">低</option>
          </select>
        </FormField>
        <FormField label="证据链接（精确日期必填，其余选填）">
          <input value={form.evidence_url} onChange={(e) => setField("evidence_url", e.target.value)} placeholder="https://…" className={inputCls} />
        </FormField>
        <FormField label="证据短摘要（选填，禁整段原文）">
          <input value={form.evidence_excerpt} onChange={(e) => setField("evidence_excerpt", e.target.value)} className={inputCls} />
        </FormField>
        <FormField label="有效期至（选填）">
          <input type="date" value={form.valid_until} onChange={(e) => setField("valid_until", e.target.value)} className={inputCls} />
        </FormField>
        <FormField label="初始状态">
          <select value={form.verify_status} onChange={(e) => setField("verify_status", e.target.value)} className={inputCls}>
            <option value="draft">草稿（待核验，先不展示）</option>
            <option value="verified">直接核验通过（立即展示）</option>
          </select>
        </FormField>
      </div>
      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-4 py-2 text-sm font-semibold text-[#f7f1e6] transition hover:bg-[#2b2520] active:scale-[0.98] disabled:opacity-50 dark:bg-[#f3ecdf] dark:text-[#16130f] dark:hover:bg-[#e8ddca]"
        >
          {submitting ? "提交中…" : "新增观测"}
        </button>
      </div>
    </form>
  );
}

function CycleRow({
  cycle,
  busy,
  onVerify,
  onReject,
}: {
  cycle: AdminCycle;
  busy: boolean;
  onVerify: () => void;
  onReject: () => void;
}) {
  return (
    <article className="surface-soft p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-[#1a1714] dark:text-[#f3ecdf]">
          {cycle.company_profiles?.display_name || cycle.company_profiles?.company || "（未知公司）"}
        </span>
        <span className="rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
          {cycle.grad_class}
        </span>
        <span className="rounded-full border border-black/[0.08] bg-white/70 px-2 py-0.5 text-[11px] text-[#5f594e] dark:border-white/[0.1] dark:bg-white/[0.05] dark:text-[#b6ad9d]">
          {cycle.season} · {cycle.batch} · {cycle.event}
        </span>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", cycleStatusChip(cycle.verify_status))}>
          {CYCLE_STATUS_LABELS[cycle.verify_status] || cycle.verify_status}
        </span>
        <div className="ml-auto flex gap-1.5">
          {cycle.verify_status !== "verified" && (
            <button
              type="button"
              disabled={busy}
              onClick={onVerify}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[#4f6f2a] transition hover:bg-black/[0.05] hover:text-[#3f5a1c] disabled:opacity-50 dark:text-[#a3d06a] dark:hover:bg-white/[0.05] dark:hover:text-[#b8dd85]"
            >
              <CheckCircle size={13} weight="bold" /> 设为 verified
            </button>
          )}
          {cycle.verify_status !== "rejected" && (
            <button
              type="button"
              disabled={busy}
              onClick={onReject}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-[#5f594e] transition hover:bg-black/[0.05] hover:text-[#1a1714] disabled:opacity-50 dark:text-[#b6ad9d] dark:hover:bg-white/[0.05] dark:hover:text-[#f3ecdf]"
            >
              <XCircle size={13} weight="bold" /> 设为 rejected
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 leading-6 text-[#3f3a33] dark:text-[#d9d0c2]">{cycle.value_text}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#8a8275] dark:text-[#9a9184]">
        {cycle.confidence && <span>置信度 {cycle.confidence}</span>}
        {cycle.valid_until && <span>有效期至 {cycle.valid_until}</span>}
        {cycle.evidence_url && (
          <a
            href={cycle.evidence_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#2f6299] hover:underline dark:text-[#7fb2e8]"
          >
            来源
          </a>
        )}
      </div>
    </article>
  );
}
