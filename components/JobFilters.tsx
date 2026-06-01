"use client";

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

  const inputClass = "rounded-md border px-3 py-1.5 text-sm w-full";
  const selectClass = "rounded-md border px-3 py-1.5 text-sm w-full bg-background";

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground">公司</label>
          <select value={filters.company} onChange={(e) => set("company", e.target.value)} className={selectClass}>
            <option value="">全部</option>
            {companies.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">城市</label>
          <input value={filters.city} onChange={(e) => set("city", e.target.value)} placeholder="如 北京" className={inputClass} />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">岗位类型</label>
          <select value={filters.jobType} onChange={(e) => set("jobType", e.target.value)} className={selectClass}>
            <option value="">全部</option>
            <option value="校招">校招</option>
            <option value="社招">社招</option>
            <option value="实习">实习</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">关键词</label>
          <input value={filters.keyword} onChange={(e) => set("keyword", e.target.value)} placeholder="如 算法" className={inputClass} />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">排序</label>
          <select value={filters.sortBy} onChange={(e) => set("sortBy", e.target.value)} className={selectClass}>
            <option value="match">按匹配度</option>
            <option value="newest">按最新发现</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">资本来源</label>
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
      <div className="flex flex-wrap gap-3">
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
    <label className="flex items-center gap-1.5 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="rounded" />
      {label}
    </label>
  );
}
