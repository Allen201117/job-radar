"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  Buildings,
  Briefcase,
  CaretDown,
  Funnel,
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
  // 移动端默认收起筛选，先让用户看到岗位；点击「筛选」条展开。桌面端（lg+）始终展开。
  const [open, setOpen] = useState(false);

  function set(key: keyof Filters, value: string | boolean) {
    onChange({ ...filters, [key]: value });
  }

  // 收起态在「筛选」条上回显当前生效的筛选，避免折叠后看不出筛了什么。
  const activeBits = [
    filters.company,
    filters.city,
    filters.jobType,
    filters.keyword,
    filters.capitalOrigin,
    filters.showNewOnly ? "仅新岗位" : "",
    filters.salaryOnly ? "仅薪资公开" : "",
    filters.showIgnored ? "含已忽略" : "",
    filters.showApplied ? "含已投递" : "",
  ].filter(Boolean) as string[];

  const inputClass = "mt-1 w-full rounded-xl border border-black/[0.09] bg-white/70 px-3 py-2 text-sm text-[#1a1714] transition duration-200 placeholder:text-[#a39a8c] focus:border-[#1a1714]/55 focus:bg-white focus:outline-none";
  const selectClass = "mt-1 w-full rounded-xl border border-black/[0.09] bg-white px-3 py-2 text-sm text-[#1a1714] transition duration-200 focus:border-[#1a1714]/55 focus:outline-none";

  return (
    <div className="surface p-4 text-[#1a1714] sm:p-5">
      {/* 移动端折叠开关（lg 以下） */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="-m-1 flex w-full items-center gap-2 rounded-xl p-1 text-left lg:hidden"
      >
        <Funnel size={18} weight="fill" className="shrink-0 text-[#5f594e]" aria-hidden="true" />
        <span className="shrink-0 text-sm font-semibold text-[#3f3a33]">筛选</span>
        {activeBits.length > 0 && (
          <span className="grid size-5 shrink-0 place-items-center rounded-full bg-[#1a1714] text-[11px] font-semibold tabular-nums text-[#f7f1e6]">
            {activeBits.length}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-xs text-[#9a9184]">
          {activeBits.length > 0 ? activeBits.join(" · ") : "全部岗位"}
        </span>
        <CaretDown
          size={16}
          weight="bold"
          className={cn("shrink-0 text-[#8a8275] transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>

      <div className={cn("space-y-5", open ? "block pt-4" : "hidden", "lg:block lg:pt-0")}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <FilterLabel icon={Buildings} label="公司" />
          {/* 可输入 combobox：自由输入 + 已知公司自动补全（datalist）；匹配走大小写不敏感子串。 */}
          <input
            value={filters.company}
            onChange={(e) => set("company", e.target.value)}
            list="job-company-options"
            placeholder="输入或选择，如 字节"
            className={inputClass}
          />
          <datalist id="job-company-options">
            {companies.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
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
    </div>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-full border border-black/[0.08] bg-white/70 px-3 py-2 text-sm text-[#5f594e] transition duration-200 hover:bg-white hover:text-[#1a1714] active:scale-[0.98]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 rounded border-black/20 accent-[#1a1714]"
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
    <label className="inline-flex items-center gap-1.5 text-xs font-medium text-[#8a8275]">
      <Icon size={14} weight="fill" aria-hidden="true" />
      {label}
    </label>
  );
}
