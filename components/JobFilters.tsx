"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { splitMultiValue } from "@/lib/job-filter";
import {
  Buildings,
  Briefcase,
  CaretDown,
  Funnel,
  GlobeHemisphereEast,
  GraduationCap,
  MapPin,
  MagnifyingGlass,
  SortAscending,
  Sparkle,
  X,
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
  region: string;
  salaryOnly: boolean;
  sponsorshipOnly: boolean;
  education: string;
}

interface Props {
  filters: Filters;
  onChange: (filters: Filters) => void;
  companies: string[];
  jobScope?: string | null;
}

const ORIGINS = ["全部", "中国", "外企", "美企", "德企", "日企", "欧企"];
const REGIONS = [
  { value: "", label: "全部海外" },
  { value: "US", label: "美国" },
  { value: "SG", label: "新加坡" },
  { value: "Remote", label: "远程" },
];

export default function JobFilters({ filters, onChange, companies, jobScope = "domestic" }: Props) {
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
    filters.education,
    filters.keyword,
    jobScope !== "domestic" ? filters.region : "",
    filters.capitalOrigin,
    filters.showNewOnly ? "仅新岗位" : "",
    filters.salaryOnly ? "仅薪资公开" : "",
    filters.sponsorshipOnly ? "排除无 Sponsorship" : "",
    filters.showIgnored ? "含已忽略" : "",
    filters.showApplied ? "含已投递" : "",
  ].filter(Boolean) as string[];
  const moreActiveBits = [
    filters.education,
    filters.sortBy === "newest" ? "按发布时间" : "",
    filters.capitalOrigin,
    jobScope !== "domestic" ? filters.region : "",
  ].filter(Boolean) as string[];

  const inputClass = "mt-1 w-full rounded-xl border border-black/[0.09] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-3 py-2 text-sm text-[#1a1714] dark:text-[#f3ecdf] transition duration-200 placeholder:text-[#a39a8c] dark:placeholder:text-[#8b8478] focus:border-[#1a1714]/55 dark:focus:border-white/55 focus:bg-white dark:focus:bg-[#1e1a15] focus:outline-none";
  const selectClass = "mt-1 w-full rounded-xl border border-black/[0.09] dark:border-white/[0.1] bg-white dark:bg-[#1e1a15] px-3 py-2 text-sm text-[#1a1714] dark:text-[#f3ecdf] transition duration-200 focus:border-[#1a1714]/55 dark:focus:border-white/55 focus:outline-none";

  return (
    <div className="surface p-4 text-[#1a1714] dark:text-[#f3ecdf] sm:p-5">
      {/* 移动端折叠开关（lg 以下） */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="-m-1 flex w-full items-center gap-2 rounded-xl p-1 text-left lg:hidden"
      >
        <Funnel size={18} weight="fill" className="shrink-0 text-[#5f594e] dark:text-[#b6ad9d]" aria-hidden="true" />
        <span className="shrink-0 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">筛选</span>
        {activeBits.length > 0 && (
          <span className="grid size-5 shrink-0 place-items-center rounded-full bg-[#1a1714] dark:bg-[#f3ecdf] text-[11px] font-semibold tabular-nums text-[#f7f1e6] dark:text-[#16130f]">
            {activeBits.length}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-xs text-[#9a9184] dark:text-[#837c70]">
          {activeBits.length > 0 ? activeBits.join(" · ") : "全部岗位"}
        </span>
        <CaretDown
          size={16}
          weight="bold"
          className={cn("shrink-0 text-[#8a8275] dark:text-[#9a9184] transition-transform", open && "rotate-180")}
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
            <FilterLabel icon={MapPin} label="城市（可多选）" />
            <ChipsInput
              value={filters.city}
              onChange={(v) => set("city", v)}
              placeholder="如 北京，空格或回车分隔，可多选"
              ariaLabel="城市，可多选"
            />
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
            <FilterLabel icon={MagnifyingGlass} label="关键词（可多选）" />
            <ChipsInput
              value={filters.keyword}
              onChange={(v) => set("keyword", v)}
              placeholder="如 算法，空格或回车分隔，可多选"
              ariaLabel="关键词，可多选"
            />
          </div>
        </div>

        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl border border-black/[0.08] bg-white/45 px-3 py-2 dark:border-white/[0.1] dark:bg-white/[0.04] [&::-webkit-details-marker]:hidden">
            <span className="shrink-0 text-sm font-semibold text-[#3f3a33] dark:text-[#d9d0c2]">更多筛选</span>
            {moreActiveBits.length > 0 && (
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-[#1a1714] text-[11px] font-semibold tabular-nums text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
                {moreActiveBits.length}
              </span>
            )}
            <span className="min-w-0 flex-1 truncate text-xs text-[#9a9184] dark:text-[#837c70]">
              {moreActiveBits.length > 0 ? moreActiveBits.join(" · ") : "学历、排序、资本来源"}
            </span>
            <CaretDown
              size={16}
              weight="bold"
              className="shrink-0 text-[#8a8275] transition-transform group-open:rotate-180 dark:text-[#9a9184]"
              aria-hidden="true"
            />
          </summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <FilterLabel icon={GraduationCap} label="学历" />
              {/* 门槛语义：选某学历=显示「该学历及以下要求」的岗位（用户够格投）；要求更高的筛掉。"学历不限"=不筛。 */}
              <select value={filters.education} onChange={(e) => set("education", e.target.value)} className={selectClass}>
                <option value="">学历不限</option>
                <option value="博士">博士</option>
                <option value="硕士">硕士</option>
                <option value="本科">本科</option>
                <option value="大专">大专</option>
              </select>
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
            {jobScope !== "domestic" && (
              <div>
                <FilterLabel icon={MapPin} label="地区" />
                <select
                  value={filters.region || ""}
                  onChange={(e) => set("region", e.target.value)}
                  className={selectClass}
                >
                  {REGIONS.map((r) => (
                    <option key={r.value || "all"} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </details>

        <div className="flex flex-wrap gap-2">
          <Check label="仅新岗位" checked={filters.showNewOnly} onChange={(v) => set("showNewOnly", v)} />
          {/* 薪资/Sponsorship 只在海外范围显示：国内岗薪资字段稀疏、且无签证概念。 */}
          {jobScope !== "domestic" && (
            <>
              <Check label="仅薪资公开" checked={filters.salaryOnly} onChange={(v) => set("salaryOnly", v)} />
              <Check label="排除不提供 Sponsorship 的岗" checked={filters.sponsorshipOnly} onChange={(v) => set("sponsorshipOnly", v)} />
            </>
          )}
          <Check label="显示已忽略" checked={filters.showIgnored} onChange={(v) => set("showIgnored", v)} />
          <Check label="显示已投递" checked={filters.showApplied} onChange={(v) => set("showApplied", v)} />
        </div>
      </div>
    </div>
  );
}

// 多选输入（城市 / 关键词）：内部以英文逗号存储的字符串 <-> 芯片。回车 / 逗号提交，退格删末项。
// 值展示为可删除芯片；沿用暖调输入框样式（focus-within 提亮）。
function ChipsInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
}) {
  const [draft, setDraft] = useState("");
  const chips = splitMultiValue(value);

  // 提交草稿：按空白/逗号拆成多枚芯片（用户常用空格分隔多城市，如「上海 杭州 深圳」→ 三枚）。
  function commit(raw: string) {
    setDraft("");
    const next = [...chips];
    for (const part of splitMultiValue(raw)) {
      if (!next.includes(part)) next.push(part);
    }
    if (next.length !== chips.length) onChange(next.join(","));
  }
  function removeAt(index: number) {
    onChange(chips.filter((_, i) => i !== index).join(","));
  }

  return (
    <div className="mt-1 flex w-full flex-wrap items-center gap-1.5 rounded-xl border border-black/[0.09] bg-white/70 px-2 py-1.5 text-sm transition duration-200 focus-within:border-[#1a1714]/55 focus-within:bg-white dark:border-white/[0.1] dark:bg-white/[0.05] dark:focus-within:border-white/55 dark:focus-within:bg-[#1e1a15]">
      {chips.map((chip, i) => (
        <span
          key={chip}
          className="inline-flex items-center gap-1 rounded-lg bg-black/[0.06] py-0.5 pl-2 pr-1 text-[13px] font-medium text-[#3f3a33] dark:bg-white/[0.1] dark:text-[#e7ddca]"
        >
          {chip}
          <button
            type="button"
            onClick={() => removeAt(i)}
            aria-label={`移除 ${chip}`}
            className="grid size-4 place-items-center rounded text-[#8a8275] transition hover:bg-black/[0.08] hover:text-[#1a1714] dark:text-[#9a9184] dark:hover:bg-white/[0.12] dark:hover:text-[#f3ecdf]"
          >
            <X size={11} weight="bold" aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        aria-label={ariaLabel}
        placeholder={chips.length ? "" : placeholder}
        onChange={(e) => {
          const v = e.target.value;
          // 输入 / 粘贴含分隔符（中英文逗号）→ 逐段提交，末段留在草稿。
          if (/[,，]/.test(v)) {
            const parts = v.split(/[,，]/);
            const last = parts.pop() ?? "";
            parts.forEach((p) => commit(p));
            setDraft(last);
          } else {
            setDraft(v);
          }
        }}
        onKeyDown={(e) => {
          // 中文输入法组字中回车是「确认候选」，不能当作提交（否则吞掉半截拼音）。
          if ((e.nativeEvent as any).isComposing) return;
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && !draft && chips.length) {
            e.preventDefault();
            removeAt(chips.length - 1);
          }
        }}
        onBlur={() => commit(draft)}
        className="min-w-[6rem] flex-1 bg-transparent px-1 py-1 text-sm text-[#1a1714] placeholder:text-[#a39a8c] focus:outline-none dark:text-[#f3ecdf] dark:placeholder:text-[#8b8478]"
      />
    </div>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-full border border-black/[0.08] dark:border-white/[0.1] bg-white/70 dark:bg-white/[0.05] px-3 py-2 text-sm text-[#5f594e] dark:text-[#b6ad9d] transition duration-200 hover:bg-white dark:hover:bg-[#1e1a15] hover:text-[#1a1714] dark:hover:text-[#f3ecdf] active:scale-[0.98]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 rounded border-black/20 dark:border-white/20 accent-[#1a1714] dark:accent-[#f3ecdf]"
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
    <label className="inline-flex items-center gap-1.5 text-xs font-medium text-[#8a8275] dark:text-[#9a9184]">
      <Icon size={14} weight="fill" aria-hidden="true" />
      {label}
    </label>
  );
}
