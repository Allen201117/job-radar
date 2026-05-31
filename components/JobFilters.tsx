"use client";

interface Filters {
  company: string;
  city: string;
  jobType: string;
  keyword: string;
  showIgnored: boolean;
  showApplied: boolean;
  showNewOnly: boolean;
}

interface Props {
  filters: Filters;
  onChange: (filters: Filters) => void;
  companies: string[];
}

export default function JobFilters({ filters, onChange, companies }: Props) {
  function set(key: keyof Filters, value: string | boolean) {
    onChange({ ...filters, [key]: value });
  }

  const inputClass =
    "rounded-md border px-3 py-1.5 text-sm w-full";
  const selectClass =
    "rounded-md border px-3 py-1.5 text-sm w-full bg-background";

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground">
            公司
          </label>
          <select
            value={filters.company}
            onChange={(e) => set("company", e.target.value)}
            className={selectClass}
          >
            <option value="">全部</option>
            {companies.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">
            城市
          </label>
          <input
            value={filters.city}
            onChange={(e) => set("city", e.target.value)}
            placeholder="如 北京"
            className={inputClass}
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">
            岗位类型
          </label>
          <select
            value={filters.jobType}
            onChange={(e) => set("jobType", e.target.value)}
            className={selectClass}
          >
            <option value="">全部</option>
            <option value="校招">校招</option>
            <option value="社招">社招</option>
            <option value="实习">实习</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">
            关键词
          </label>
          <input
            value={filters.keyword}
            onChange={(e) => set("keyword", e.target.value)}
            placeholder="如 算法"
            className={inputClass}
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={filters.showNewOnly}
            onChange={(e) => set("showNewOnly", e.target.checked)}
            className="rounded"
          />
          仅新岗位
        </label>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={filters.showIgnored}
            onChange={(e) => set("showIgnored", e.target.checked)}
            className="rounded"
          />
          显示已忽略
        </label>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={filters.showApplied}
            onChange={(e) => set("showApplied", e.target.checked)}
            className="rounded"
          />
          显示已投递
        </label>
      </div>
    </div>
  );
}
