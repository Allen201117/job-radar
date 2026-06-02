"use client";

import {
  Buildings,
  Briefcase,
  GlobeHemisphereEast,
  MapPin,
  MagnifyingGlass,
  SortAscending,
  Sparkle,
} from "@phosphor-icons/react";

interface Filters {
  company: string;
  city: string;
  jobType: string;
  keyword: string;
  showIgnored: boolean;
  showApplied: boolean;
  showNewOnly: boolean;
  sortBy: "match" | "newest";
  capitalOrigin: string;
  salaryOnly: boolean;
}

interface Props {
  filters: Filters;
  onChange: (filters: Filters) => void;
  companies: string[];
}

const ORIGINS = ["全部", "中国", "外企", "美企", "德企", "日企", "欧企"];

export default function JobFilters({ filters, onChange, companies }: Props) {
  function set(key: keyof Filters, value: string | boolean) {
    onChange({ ...filters, [key]: value });
  }

  const inputClass = "mt-1 w-full rounded-xl border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition duration-200 placeholder:text-white/32 focus:border-sky-300 focus:outline-none";
  const selectClass = "mt-1 w-full rounded-xl border border-white/10 bg-[#17191f] px-3 py-2 text-sm text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition duration-200 focus:border-sky-300 focus:outline-none";

  return (
    <div className="space-y-5 rounded-[1.35rem] border border-white/10 bg-white/[0.055] p-4 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] sm:p-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <FilterLabel icon={Buildings} label="公司" />
          <select value={filters.company} onChange={(e) => set("company", e.target.value)} className={selectClass}>
            <option value="">全部</option>
            {companies.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <FilterLabel icon={MapPin} label="城市" />
          <input value={filters.city} onChange={(e) => set("city", e.target.value)} placeholder="如 北京" className={inputClass} />
        </div>
        <div>
          <FilterLabel icon={Briefcase} label="岗位类型" />
          <select value={filters.jobType} onChange={(e) => set("jobType", e.target.value)} className={selectClass}>
            <option value="">全部</option>
            <option value="校招">校招</option>
            <option value="社招">社招</option>
            <option value="实习">实习</option>
          </select>
        </div>
        <div>
          <FilterLabel icon={MagnifyingGlass} label="关键词" />
          <input value={filters.keyword} onChange={(e) => set("keyword", e.target.value)} placeholder="如 算法" className={inputClass} />
        </div>
        <div>
          <FilterLabel icon={SortAscending} label="排序" />
          <select value={filters.sortBy} onChange={(e) => set("sortBy", e.target.value)} className={selectClass}>
            <option value="match">按匹配度</option>
            <option value="newest">按发布时间</option>
          </select>
        </div>
        <div>
          <FilterLabel icon={GlobeHemisphereEast} label="资本来源" />
          <select
            value={filters.capitalOrigin || "全部"}
            onChange={(e) => set("capitalOrigin", e.target.value === "全部" ? "" : e.target.value)}
            className={selectClass}
          >
            {ORIGINS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Check label="仅新岗位" checked={filters.showNewOnly} onChange={(v) => set("showNewOnly", v)} />
        <Check label="仅薪资公开" checked={filters.salaryOnly} onChange={(v) => set("salaryOnly", v)} />
        <Check label="显示已忽略" checked={filters.showIgnored} onChange={(v) => set("showIgnored", v)} />
        <Check label="显示已投递" checked={filters.showApplied} onChange={(v) => set("showApplied", v)} />
      </div>
    </div>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-2 text-sm text-white/76 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition duration-200 hover:bg-white/16 hover:text-white active:scale-[0.98]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 rounded border-white/20 bg-white/10 text-sky-300"
      />
      {label}
    </label>
  );
}

function FilterLabel({
  icon: Icon,
  label,
}: {
  icon: typeof Sparkle;
  label: string;
}) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs font-medium text-white/50">
      <Icon size={14} weight="fill" aria-hidden="true" />
      {label}
    </label>
  );
}
