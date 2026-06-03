"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, PencilSimple, Trash, ArrowCounterClockwise, X, Flag, Warning } from "@phosphor-icons/react";
import { INSIGHT_DIMENSIONS } from "@/lib/insight-bundle";
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
}
interface AdminDispute {
  id: string;
  item_id: string;
  reason: string | null;
  contact: string | null;
  status: string;
  created_at: string;
}

const DIM_LABELS: Record<InsightDimension, string> = {
  timing: "招聘时机",
  compensation_intensity: "薪资 / 强度",
  path: "进入路径",
  culture: "公司文化 / 温馨提示",
};
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
};

const EMPTY_FORM: FormState = {
  id: null,
  company: "",
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
};

const inputCls =
  "w-full rounded-lg border border-white/12 bg-white/[0.04] px-3 py-2 text-sm text-white/85 outline-none placeholder:text-white/30 focus:border-white/25";

export default function InsightsAdminClient() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [companies, setCompanies] = useState<AdminCompany[]>([]);
  const [items, setItems] = useState<AdminItem[]>([]);
  const [disputes, setDisputes] = useState<AdminDispute[]>([]);

  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [formOpen, setFormOpen] = useState(false);
  const [formError, setFormError] = useState("");
  const [formGate, setFormGate] = useState("");
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");

  async function load() {
    setLoading(true);
    try {
      const res = await fetch("/api/insights/admin");
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "加载失败");
      setCompanies(data.companies || []);
      setItems(data.items || []);
      setDisputes(data.disputes || []);
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
      const payload = {
        id: form.id,
        company: form.company,
        dimension: form.dimension,
        grade: form.grade,
        title: form.title,
        content: form.content,
        sample_size: form.sample_size,
        time_window: form.time_window,
        valid_until: form.valid_until,
        deidentified: form.deidentified,
        status: form.status,
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

  if (loading) return <p className="mt-8 text-sm text-white/50">正在加载洞察后台…</p>;
  if (error)
    return (
      <p className="mt-8 rounded-xl border border-white/10 bg-white/[0.04] p-4 text-sm text-white/60">
        {error}
      </p>
    );

  return (
    <div className="mt-8 space-y-8 text-white">
      <div className="flex flex-wrap items-center gap-3">
        {!formOpen && (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-4 py-2 text-sm font-semibold text-sky-950 transition hover:bg-sky-200 active:scale-[0.98]"
          >
            <Plus size={16} weight="bold" /> 新增洞察条目
          </button>
        )}
        <span className="text-sm text-white/45">
          共 {items.length} 条洞察 · {companies.length} 家公司 · {disputes.length} 条待处理申诉
        </span>
      </div>

      {formOpen && (
        <ItemForm
          form={form}
          companies={companies}
          formError={formError}
          formGate={formGate}
          saving={saving}
          setField={setField}
          setSource={setSource}
          addSource={addSource}
          removeSource={removeSource}
          onSubmit={save}
          onCancel={() => setFormOpen(false)}
        />
      )}

      {/* 待处理申诉 */}
      {disputes.length > 0 && (
        <section>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-amber-200/90">
            <Flag size={16} weight="fill" /> 待处理申诉（{disputes.length}）
          </h2>
          <div className="space-y-3">
            {disputes.map((d) => {
              const it = itemById.get(d.item_id);
              return (
                <article
                  key={d.id}
                  className="rounded-xl border border-amber-300/20 bg-amber-300/[0.06] p-4 text-sm"
                >
                  <p className="text-white/85">
                    {it ? (
                      <>
                        <span className="font-medium">
                          {companyById.get(it.company_id)?.display_name ||
                            companyById.get(it.company_id)?.company}
                        </span>{" "}
                        · {DIM_LABELS[it.dimension]} · {it.title || it.content.slice(0, 24)}
                      </>
                    ) : (
                      <span className="text-white/50">条目已不存在（item_id: {d.item_id.slice(0, 8)}）</span>
                    )}
                  </p>
                  {it && <p className="mt-1 leading-6 text-white/60">{it.content}</p>}
                  <p className="mt-2 text-xs text-white/50">
                    申诉理由：{d.reason || "（未填写）"} · {new Date(d.created_at).toLocaleString("zh-CN")}
                  </p>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      disabled={busyId === d.id}
                      onClick={() => resolveDispute(d, "upheld")}
                      className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#08090c] transition hover:bg-white/85 disabled:opacity-50"
                    >
                      <Trash size={13} weight="bold" /> 成立并下架
                    </button>
                    <button
                      type="button"
                      disabled={busyId === d.id}
                      onClick={() => resolveDispute(d, "rejected")}
                      className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-medium text-white/70 transition hover:bg-white/10 hover:text-white disabled:opacity-50"
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

      {/* 全部条目（按公司分组） */}
      <section className="space-y-6">
        {grouped.map((g) => (
          <div key={g.name}>
            <h3 className="mb-2 text-sm font-semibold text-white/80">{g.name}</h3>
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
          <p className="rounded-xl border border-white/10 bg-white/[0.04] p-4 text-sm text-white/55">
            还没有任何洞察条目。点「新增洞察条目」开始录入。
          </p>
        )}
      </section>
    </div>
  );
}

function statusChip(status: string) {
  if (status === "active") return "border-emerald-300/25 bg-emerald-300/12 text-emerald-200";
  if (status === "disputed") return "border-amber-300/25 bg-amber-300/12 text-amber-200";
  return "border-white/15 bg-white/10 text-white/55";
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
    <article className="rounded-xl border border-white/10 bg-white/[0.04] p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-white/12 bg-white/[0.06] px-2 py-0.5 text-[11px] text-white/65">
          {DIM_LABELS[item.dimension]}
        </span>
        <span className="rounded-full border border-white/12 bg-white/[0.06] px-2 py-0.5 text-[11px] text-white/65">
          {GRADE_LABELS[item.grade]}
        </span>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", statusChip(item.status))}>
          {STATUS_LABELS[item.status] || item.status}
        </span>
        {!item.deidentified && (
          <span className="inline-flex items-center gap-1 rounded-full border border-red-400/25 bg-red-400/10 px-2 py-0.5 text-[11px] text-red-200">
            <Warning size={11} weight="fill" /> 未去标识
          </span>
        )}
        <div className="ml-auto flex gap-1.5">
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-white/60 transition hover:bg-white/10 hover:text-white"
          >
            <PencilSimple size={13} /> 编辑
          </button>
          {item.status === "active" ? (
            <button
              type="button"
              disabled={busy}
              onClick={onRetire}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-white/60 transition hover:bg-white/10 hover:text-white disabled:opacity-50"
            >
              <Trash size={13} /> 下架
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={onActivate}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-emerald-200/80 transition hover:bg-white/10 hover:text-emerald-200 disabled:opacity-50"
            >
              <ArrowCounterClockwise size={13} /> 上架
            </button>
          )}
        </div>
      </div>
      {item.title && <p className="mt-2 font-semibold text-white/90">{item.title}</p>}
      <p className="mt-1 leading-6 text-white/70">{item.content}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-white/45">
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
  setField,
  setSource,
  addSource,
  removeSource,
  onSubmit,
  onCancel,
}: {
  form: FormState;
  companies: AdminCompany[];
  formError: string;
  formGate: string;
  saving: boolean;
  setField: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  setSource: (i: number, patch: Partial<SourceDraft>) => void;
  addSource: () => void;
  removeSource: (i: number) => void;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-5 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">{form.id ? "编辑洞察条目" : "新增洞察条目"}</h3>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full bg-white/10 p-1.5 text-white/70 transition hover:bg-white/16 hover:text-white"
        >
          <X size={16} weight="bold" />
        </button>
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

        <FormField label="维度">
          <select value={form.dimension} onChange={(e) => setField("dimension", e.target.value as InsightDimension)} className={inputCls}>
            {INSIGHT_DIMENSIONS.map((d) => (
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
          <label className="inline-flex items-center gap-2 text-sm text-white/75">
            <input
              type="checkbox"
              checked={form.deidentified}
              onChange={(e) => setField("deidentified", e.target.checked)}
              className="size-4 accent-sky-300"
            />
            内容已去标识，不指向具体个人
          </label>
        </FormField>
      </div>

      {/* 来源 */}
      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium text-white/50">来源（链接 + 短摘要，禁整段原文）</span>
          <button type="button" onClick={addSource} className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] text-sky-200 transition hover:bg-white/10">
            <Plus size={12} weight="bold" /> 加一条来源
          </button>
        </div>
        <div className="space-y-3">
          {form.sources.map((s, i) => (
            <div key={i} className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
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
                <label className="inline-flex items-center gap-2 text-xs text-white/65">
                  <input type="checkbox" checked={s.deidentified} onChange={(e) => setSource(i, { deidentified: e.target.checked })} className="size-3.5 accent-sky-300" />
                  已去标识
                </label>
                {form.sources.length > 1 && (
                  <button type="button" onClick={() => removeSource(i)} className="text-[11px] text-white/40 transition hover:text-red-200">
                    删除
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {formGate && (
        <p className="mt-4 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-xs leading-5 text-amber-100/90">
          {formGate}
        </p>
      )}
      {formError && (
        <p className="mt-3 rounded-lg bg-red-400/10 px-3 py-2 text-sm text-red-200">{formError}</p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-semibold text-[#08090c] transition hover:bg-white/85 active:scale-[0.98] disabled:opacity-50"
        >
          {saving ? "保存中…" : form.id ? "保存修改" : "创建条目"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-full px-4 py-2 text-sm font-medium text-white/55 transition hover:bg-white/10 hover:text-white">
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
      <label className="mb-1.5 block text-xs font-medium text-white/50">{label}</label>
      {children}
    </div>
  );
}
