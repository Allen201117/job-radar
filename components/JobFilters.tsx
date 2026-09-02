"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type RefObject,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { JOB_FUNCTION_BUCKETS, JOB_FUNCTION_TAXONOMY } from "@/lib/china-keyword-expansion";
import { splitMultiValue, type Filters } from "@/lib/job-filter";
import {
  Buildings,
  CaretDown,
  Check,
  Funnel,
  GraduationCap,
  MagnifyingGlass,
  MapPin,
  SlidersHorizontal,
  X,
} from "@phosphor-icons/react";

interface Props {
  filters: Filters;
  onChange: (filters: Filters) => void;
  onClearAll: () => void;
  onClearOne: (key: keyof Filters, value?: string) => void;
  companies: string[];
  resultTotal: number;
  jobScope?: string | null;
}

type PopoverName = "city" | "jobFunction" | "experience" | "keyword" | "company" | null;

const ORIGINS = ["全部", "中国", "外企", "美企", "德企", "日企", "欧企"];
const REGIONS = [
  { value: "", label: "全部海外" },
  { value: "US", label: "美国" },
  { value: "SG", label: "新加坡" },
  { value: "Remote", label: "远程" },
];
const EXPERIENCE = [
  { value: "", label: "不限" },
  { value: "fresh", label: "应届无经验" },
  { value: "0-3", label: "0–3 年" },
  { value: "3-5", label: "3–5 年" },
  { value: "5-10", label: "5–10 年" },
  { value: "10+", label: "10 年+" },
];
const EDUCATION = ["不限", "大专", "本科", "硕士", "博士"];
const POSTED_WITHIN = [
  { value: "", label: "不限" },
  { value: "1", label: "24 小时内" },
  { value: "3", label: "3 天内" },
  { value: "7", label: "7 天内" },
  { value: "30", label: "30 天内" },
];

// 「全部筛选」按钮被点那一刻的位置，用于让弹窗从它身上放大展开。
type PanelOrigin = { x: number; y: number; w: number; h: number };

// 按压反馈（active:scale）是刻意加的：筛选条上全是「点了才知道有没有生效」的按钮，
// 没有下压反馈时用户分不清「没点中」和「点了没反应」。
const buttonBase = "t-label inline-flex min-h-10 items-center gap-1.5 rounded-full border px-3 transition duration-200 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1a1714]/30 dark:focus-visible:ring-[#f3ecdf]/35";
const buttonIdle = "border-black/[0.1] bg-white/55 hover:border-black/[0.2] hover:bg-white dark:border-white/[0.12] dark:bg-white/[0.05] dark:hover:border-white/[0.22] dark:hover:bg-white/[0.1]";
const buttonActive = "border-[#1a1714]/45 bg-[#eee8dc] dark:border-[#f3ecdf]/45 dark:bg-[#f3ecdf]/[0.12]";

export default function JobFilters({
  filters,
  onChange,
  onClearAll,
  onClearOne,
  companies,
  resultTotal,
  jobScope = "domestic",
}: Props) {
  const [activePopover, setActivePopover] = useState<PopoverName>(null);
  // 存的是「全部筛选」按钮被点那一刻的位置，不只是开关状态——桌面端弹窗要从这颗按钮的位置放大展开。
  const [panelOrigin, setPanelOrigin] = useState<PanelOrigin | null>(null);
  const panelOpen = panelOrigin !== null;
  const openPanel = (event: MouseEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPanelOrigin({ x: rect.left, y: rect.top, w: rect.width, h: rect.height });
  };
  const overseas = jobScope !== "domestic";

  const set = (key: keyof Filters, value: Filters[keyof Filters]) => {
    onChange({ ...filters, [key]: value });
  };
  const togglePopover = (name: PopoverName) => setActivePopover((current) => (current === name ? null : name));

  const activeChips = collectActiveChips(filters, overseas);
  const allFiltersCount = countPanelFilters(filters, overseas);

  return (
    <section aria-label="岗位筛选" className="space-y-2">
      <div className="sticky top-14 z-30 -mx-1 border-b border-black/[0.08] bg-[#f4efe6]/95 px-1 py-2.5 dark:border-white/[0.1] dark:bg-[#16130f]/95">
        <div className="hidden items-center gap-2 overflow-x-auto scrollbar-hide lg:flex">
          <FilterField label="城市" value={compactMultiValue(filters.city)} active={Boolean(filters.city)} open={activePopover === "city"} onToggle={() => togglePopover("city")} icon={<MapPin size={15} weight="fill" aria-hidden="true" />} onClose={() => setActivePopover(null)}><MultiValueEditor value={filters.city} onChange={(value) => set("city", value)} ariaLabel="城市，可多选" placeholder="输入城市后按回车" /></FilterField>
          <RecruitmentType value={filters.jobType} onChange={(value) => set("jobType", value)} />
          <FilterField label="岗位方向" value={compactMultiValue([filters.jobFunction, filters.jobRole].filter(Boolean).join(","))} active={Boolean(filters.jobFunction || filters.jobRole)} open={activePopover === "jobFunction"} onToggle={() => togglePopover("jobFunction")} onClose={() => setActivePopover(null)}><FunctionPicker functionValue={filters.jobFunction} roleValue={filters.jobRole} onChangeFunction={(value) => set("jobFunction", value)} onChangeRole={(value) => set("jobRole", value)} /></FilterField>
          <FilterField label="经验" value={labelFor(EXPERIENCE, filters.experience)} active={Boolean(filters.experience)} open={activePopover === "experience"} onToggle={() => togglePopover("experience")} onClose={() => setActivePopover(null)}><PillGroup options={EXPERIENCE} value={filters.experience} onChange={(value) => set("experience", value)} ariaLabel="工作经验" /></FilterField>
          <FilterField label="关键词" value={compactMultiValue(filters.keyword)} active={Boolean(filters.keyword)} open={activePopover === "keyword"} onToggle={() => togglePopover("keyword")} icon={<MagnifyingGlass size={15} weight="bold" aria-hidden="true" />} onClose={() => setActivePopover(null)}><MultiValueEditor value={filters.keyword} onChange={(value) => set("keyword", value)} ariaLabel="关键词，可多选" placeholder="输入关键词后按回车" /></FilterField>
          <FilterField label="公司" value={filters.company} active={Boolean(filters.company)} open={activePopover === "company"} onToggle={() => togglePopover("company")} icon={<Buildings size={15} weight="fill" aria-hidden="true" />} onClose={() => setActivePopover(null)}><CompanyPicker value={filters.company} onChange={(value) => set("company", value)} companies={companies} /></FilterField>
          <button type="button" onClick={openPanel} className={cn(buttonBase, buttonIdle, "relative shrink-0")} aria-haspopup="dialog">
            <SlidersHorizontal size={16} weight="bold" aria-hidden="true" />
            全部筛选
            {allFiltersCount > 0 && <CountBadge count={allFiltersCount} />}
          </button>
        </div>

        <div className="flex items-center gap-2 lg:hidden">
          <label className="flex min-w-0 flex-1 items-center gap-2 rounded-full border border-black/[0.1] bg-white/65 px-3 py-2 dark:border-white/[0.12] dark:bg-white/[0.06]">
            <MagnifyingGlass size={17} weight="bold" className="ink-3 shrink-0" aria-hidden="true" />
            <input value={filters.keyword} onChange={(event) => set("keyword", event.target.value)} aria-label="关键词" placeholder="关键词……" className="t-body-sm min-w-0 flex-1 bg-transparent outline-none placeholder:ink-4" />
          </label>
          <button type="button" onClick={openPanel} className={cn(buttonBase, buttonIdle, "relative shrink-0")} aria-haspopup="dialog">
            <Funnel size={16} weight="fill" aria-hidden="true" />
            筛选
            {activeChips.length > 0 && <CountBadge count={activeChips.length} />}
          </button>
        </div>
      </div>

      {activeChips.length > 0 && <SelectedChips chips={activeChips} onClearAll={onClearAll} onClearOne={onClearOne} />}

      <AllFiltersPanel
        origin={panelOrigin}
        filters={filters}
        onClose={() => setPanelOrigin(null)}
        onChange={set}
        onClearAll={onClearAll}
        companies={companies}
        resultTotal={resultTotal}
        overseas={overseas}
      />
    </section>
  );
}

function FilterTrigger({ label, value, active, open = false, icon, onClick }: { label: string; value: string; active: boolean; open?: boolean; icon?: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={cn(buttonBase, active || open ? buttonActive : buttonIdle, "shrink-0")} aria-expanded={open}>
      {icon}
      <span>{active ? value : label}</span>
      <CaretDown
        size={14}
        weight="bold"
        aria-hidden="true"
        className={cn("transition-transform duration-200", open && "rotate-180")}
      />
    </button>
  );
}

function RecruitmentType({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div role="group" className="flex shrink-0 rounded-full border border-black/[0.1] bg-white/55 p-0.5 dark:border-white/[0.12] dark:bg-white/[0.05]" aria-label="招聘类型">
      {["", "校招", "社招", "实习"].map((item) => (
        <button key={item || "all"} type="button" onClick={() => onChange(item)} aria-pressed={value === item} className={cn("t-label rounded-full px-3 py-2 transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1a1714]/30 dark:focus-visible:ring-[#f3ecdf]/35", value === item ? "btn-ink-sm !px-3 !py-2" : "ink-3 hover:bg-black/[0.05] dark:hover:bg-white/[0.1]")}>
          {item || "全部"}
        </button>
      ))}
    </div>
  );
}

function Popover({
  open,
  onClose,
  anchorRef,
  children,
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLDivElement>;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    // ⚠️ 必须 portal 到 body：筛选条内层是 overflow-x-auto（移动端要横滑），而滚动容器**两个轴都裁剪**。
    // 旧实现把弹层 absolute 在条里，于是 463px 高的弹层被裁进 42px 高的条里——DOM 里明明打开了，
    // 屏幕上什么都不出现，用户只会得出「这些按钮点不了」的结论（2026-09-02 线上实测确认）。
    // portal 出去后用 fixed 定位手动锚到按钮下方，并在滚动/缩放时重新对位。
    const place = () => {
      const a = anchorRef.current?.getBoundingClientRect();
      if (!a) return;
      const width = Math.min(480, window.innerWidth - 32);
      const left = Math.min(Math.max(16, a.left), Math.max(16, window.innerWidth - width - 16));
      setPos({ left, top: a.bottom + 6 });
    };
    place();
    const onKeyDown = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    const onPointerDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("resize", place);
    // capture=true：页面滚动条 / 任何祖先滚动都要跟着重新对位，否则弹层会飘在原地。
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, onClose, anchorRef]);

  if (!open || !pos) return null;
  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label="筛选选项"
      style={{ left: pos.left, top: pos.top, width: "min(30rem, calc(100vw - 2rem))" }}
      className="job-filter-pop fixed z-[45] max-h-[min(28rem,calc(100vh-8rem))] overflow-y-auto rounded-2xl border border-black/[0.1] bg-[#f4efe6] p-3 shadow-xl dark:border-white/[0.12] dark:bg-[#211b14]"
    >
      {children}
    </div>,
    document.body,
  );
}

// 一个筛选维度 = 触发按钮 + 它的弹层。包一层是为了：① 每个维度各自持有锚点 ref，弹层才知道该
// 贴在哪颗按钮下面；② 统一吃掉 pointerdown——「点外部关闭」挂在 window 上、判据是「目标不在弹层内」，
// 而触发按钮本来就不在弹层里，不拦住就会「先关掉、click 再打开」，净效果是这颗按钮永远关不掉。
function FilterField({
  label,
  value,
  active,
  open,
  icon,
  onToggle,
  onClose,
  children,
}: {
  label: string;
  value: string;
  active: boolean;
  open: boolean;
  icon?: ReactNode;
  onToggle: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const anchorRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={anchorRef} className="relative shrink-0" onPointerDown={(event) => event.stopPropagation()}>
      <FilterTrigger label={label} value={value} active={active} open={open} icon={icon} onClick={onToggle} />
      <Popover open={open} onClose={onClose} anchorRef={anchorRef}>
        {children}
      </Popover>
    </div>
  );
}

function MultiValueEditor({ value, onChange, placeholder, ariaLabel }: { value: string; onChange: (value: string) => void; placeholder: string; ariaLabel: string }) {
  const [draft, setDraft] = useState("");
  const chips = splitMultiValue(value);
  const commit = (raw: string) => {
    const next = [...chips];
    splitMultiValue(raw).forEach((item) => {
      if (!next.includes(item)) next.push(item);
    });
    setDraft("");
    if (next.length !== chips.length) onChange(next.join(","));
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-black/[0.1] bg-white/60 p-2 dark:border-white/[0.12] dark:bg-white/[0.05]">
      {chips.map((chip) => <button key={chip} type="button" onClick={() => onChange(chips.filter((item) => item !== chip).join(","))} aria-label={`移除 ${chip}`} className="chip ink-2 min-h-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1a1714]/30 dark:focus-visible:ring-[#f3ecdf]/35">{chip}<X size={13} weight="bold" aria-hidden="true" /></button>)}
      <input value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={() => commit(draft)} onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Enter" || event.key === ",") { event.preventDefault(); commit(draft); }
        if (event.key === "Backspace" && !draft && chips.length) onChange(chips.slice(0, -1).join(","));
      }} aria-label={ariaLabel} placeholder={chips.length ? "" : placeholder} className="t-body-sm min-w-40 flex-1 bg-transparent px-1 py-1 outline-none placeholder:ink-4" />
    </div>
  );
}

// 二级方向的**展示名**覆盖表（只影响界面文字，不影响匹配）。
// 二级取值是关键词组的代表词——匹配用它没问题，但个别代表词当界面标签不合适：组 23 的代表词是
// "ios"，而该组实际覆盖 ios/android/移动端，直接把 "ios" 摆给用户看既偏窄又像技术黑话。
// 这里只换显示，jobRole 里存的仍是代表词，匹配链路一个字没动。
const ROLE_LABELS: Record<string, string> = { ios: "移动端" };
const roleLabel = (role: string) => ROLE_LABELS[role] ?? role;

// 岗位方向选择器：左「一级职能」/ 右「二级具体岗位」的主从形态（BOSS / 拉勾的通行做法）。
//
// 为什么必须两级：一级只有 17 个大桶（研发 / 产品 / 设计 …），而求职者是按**「测试」「后端」**
// 这个粒度找工作的——只给一级等于「最核心的岗位类型没有」（创始人原话）。二级词表
// (JOB_FUNCTION_TAXONOMY) 从既有关键词组按下标派生，不另维护手写表，词表加组时 UI 自动跟上。
//
// 一级与二级是**并集**不是交集：勾「研发」+「产品经理」= 全部研发岗 ∪ 产品经理岗
// （判定在 lib/job-filter.ts）。所以这里两个值分开存：一级写 jobFunction，二级写 jobRole。
function FunctionPicker({
  functionValue,
  roleValue,
  onChangeFunction,
  onChangeRole,
}: {
  functionValue: string;
  roleValue: string;
  onChangeFunction: (value: string) => void;
  onChangeRole: (value: string) => void;
}) {
  const selectedFunctions = splitMultiValue(functionValue);
  const selectedRoles = splitMultiValue(roleValue);
  // 默认停在第一个「有二级可选」的职能上，避免一打开就是空右栏。
  const [activeFn, setActiveFn] = useState(
    () =>
      JOB_FUNCTION_TAXONOMY.find((entry) => selectedFunctions.includes(entry.function))?.function ??
      JOB_FUNCTION_TAXONOMY.find((entry) => entry.roles.length > 0)?.function ??
      JOB_FUNCTION_BUCKETS[0],
  );
  const active = JOB_FUNCTION_TAXONOMY.find((entry) => entry.function === activeFn);
  const toggle = (list: string[], item: string, apply: (next: string) => void) =>
    apply((list.includes(item) ? list.filter((x) => x !== item) : [...list, item]).join(","));
  const total = selectedFunctions.length + selectedRoles.length;

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="t-h3">岗位方向</p>
        <button
          type="button"
          onClick={() => {
            onChangeFunction("");
            onChangeRole("");
          }}
          className="t-label ink-3 hover:ink-1"
        >
          清空
        </button>
      </div>

      <div className="flex gap-2 rounded-xl border border-black/[0.08] bg-white/45 p-1.5 dark:border-white/[0.1] dark:bg-white/[0.04]">
        {/* 左列：一级职能。徽标显示「该职能下选了几个二级」，一级本身被选中时整项高亮。 */}
        <div role="tablist" aria-label="一级岗位职能" aria-orientation="vertical" className="max-h-64 w-[7.5rem] shrink-0 space-y-0.5 overflow-y-auto pr-1">
          {JOB_FUNCTION_TAXONOMY.map((entry) => {
            const picked = selectedFunctions.includes(entry.function);
            const count = entry.roles.filter((role) => selectedRoles.includes(role)).length;
            const current = entry.function === activeFn;
            return (
              <button
                key={entry.function}
                type="button"
                role="tab"
                aria-selected={current}
                onClick={() => setActiveFn(entry.function)}
                className={cn(
                  "t-body-sm flex w-full items-center justify-between gap-1 rounded-lg px-2.5 py-2 text-left transition duration-150 active:scale-[0.98]",
                  current ? "bg-[#eee8dc] ink-1 dark:bg-white/[0.12]" : "ink-2 hover:bg-black/[0.04] dark:hover:bg-white/[0.06]",
                )}
              >
                <span className="truncate">{entry.function}</span>
                {(picked || count > 0) && (
                  <span className="t-micro t-num rounded-full bg-[#1a1714] px-1.5 py-0.5 text-[#f7f1e6] dark:bg-[#f3ecdf] dark:text-[#16130f]">
                    {picked ? "全" : count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* 右列：该职能的二级方向。key 上挂 activeFn 让切换时重放淡入（reduced-motion 下自动无动效）。 */}
        <div key={activeFn} role="tabpanel" aria-label={`${activeFn} 的岗位方向`} className="job-filter-pop-fade max-h-64 min-w-0 flex-1 space-y-1 overflow-y-auto">
          <label className="t-body-sm flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 hover:bg-black/[0.04] dark:hover:bg-white/[0.06]">
            <input
              type="checkbox"
              checked={selectedFunctions.includes(activeFn)}
              onChange={() => toggle(selectedFunctions, activeFn, onChangeFunction)}
              className="size-4 accent-[#1a1714] dark:accent-[#f3ecdf]"
            />
            <span className="ink-1">全部{activeFn}</span>
          </label>
          {active && active.roles.length > 0 ? (
            <div className="grid grid-cols-2 gap-0.5">
              {active.roles.map((role) => (
                <label key={role} className="t-body-sm flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 hover:bg-black/[0.04] dark:hover:bg-white/[0.06]">
                  <input
                    type="checkbox"
                    checked={selectedRoles.includes(role)}
                    onChange={() => toggle(selectedRoles, role, onChangeRole)}
                    className="size-4 accent-[#1a1714] dark:accent-[#f3ecdf]"
                  />
                  <span className="ink-2">{roleLabel(role)}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className="t-caption px-2.5 py-2">该方向暂无更细分类，勾选上面的「全部{activeFn}」即可。</p>
          )}
        </div>
      </div>

      <p className="t-caption">{total > 0 ? `已选 ${total} 项` : "不选则不限岗位方向"}</p>
    </div>
  );
}

function CompanyPicker({ value, onChange, companies }: { value: string; onChange: (value: string) => void; companies: string[] }) {
  return <div className="space-y-2"><label className="t-h3" htmlFor="job-company-filter">公司</label><input id="job-company-filter" value={value} onChange={(event) => onChange(event.target.value)} list="job-company-options" placeholder="输入公司名称" className="t-body-sm w-full rounded-xl border border-black/[0.1] bg-white/60 px-3 py-2.5 outline-none focus:border-[#1a1714]/45 dark:border-white/[0.12] dark:bg-white/[0.05] dark:focus:border-[#f3ecdf]/45" /><datalist id="job-company-options">{companies.map((company) => <option key={company} value={company} />)}</datalist></div>;
}

function SelectedChips({ chips, onClearAll, onClearOne }: { chips: ActiveChip[]; onClearAll: () => void; onClearOne: (key: keyof Filters, value?: string) => void }) {
  return <div className="flex items-center gap-2 overflow-x-auto px-1 pb-1 scrollbar-hide" aria-label="已选筛选条件"><div className="flex min-w-max gap-1.5">{chips.map((chip) => <button key={chip.id} type="button" onClick={() => onClearOne(chip.key, chip.value)} className="chip ink-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1a1714]/30 dark:focus-visible:ring-[#f3ecdf]/35"><X size={13} weight="bold" aria-hidden="true" />{chip.label}</button>)}</div><button type="button" onClick={onClearAll} className="t-label ink-3 ml-auto shrink-0 px-2 py-1 hover:ink-1">清空全部</button></div>;
}

function AllFiltersPanel({ origin, filters, onChange, onClearAll, onClose, companies, resultTotal, overseas }: { origin: PanelOrigin | null; filters: Filters; onChange: (key: keyof Filters, value: Filters[keyof Filters]) => void; onClearAll: () => void; onClose: () => void; companies: string[]; resultTotal: number; overseas: boolean }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const open = origin !== null;
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKeyDown);
    panelRef.current?.focus();
    // 弹窗打开时锁住背景滚动：否则滚轮会穿透到底下的岗位列表，用户以为弹窗在滚、其实滚的是背景。
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);
  if (!origin) return null;
  // 把「按钮中心 → 视窗中心」的偏移量喂给 CSS，弹窗就从那颗按钮的位置放大展开（见 globals.css
  // 的 job-filter-grow-in）。只在桌面端生效；移动端是底部 Sheet，用不到这几个变量。
  const growStyle = {
    "--fx": `${Math.round(origin.x + origin.w / 2 - window.innerWidth / 2)}px`,
    "--fy": `${Math.round(origin.y + origin.h / 2 - window.innerHeight / 2)}px`,
    "--fs": "0.28",
  } as CSSProperties;
  return <div className="job-filter-backdrop fixed inset-0 z-50 flex items-end bg-[#1a1714]/45 p-0 backdrop-blur-[3px] dark:bg-black/65 lg:items-center lg:justify-center lg:p-6" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div ref={panelRef} role="dialog" aria-modal="true" aria-label="全部筛选" tabIndex={-1} style={growStyle} className="job-filter-panel flex h-[85dvh] w-full flex-col rounded-t-3xl bg-[#f4efe6] shadow-2xl outline-none dark:bg-[#16130f] lg:h-auto lg:max-h-[82vh] lg:w-[40rem] lg:rounded-3xl" onMouseDown={(event) => event.stopPropagation()}><div className="flex items-center justify-between border-b border-black/[0.08] px-5 py-4 dark:border-white/[0.1]"><h2 className="t-h2">全部筛选</h2><button type="button" onClick={onClose} aria-label="关闭全部筛选" className="grid size-9 place-items-center rounded-full ink-3 hover:bg-black/[0.06] hover:ink-1 dark:hover:bg-white/[0.1]"><X size={18} weight="bold" aria-hidden="true" /></button></div><div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5"><div className="space-y-3 lg:hidden"><PanelTitle>基础条件</PanelTitle><MultiValueEditor value={filters.city} onChange={(value) => onChange("city", value)} ariaLabel="城市，可多选" placeholder="城市，可多选" /><RecruitmentType value={filters.jobType} onChange={(value) => onChange("jobType", value)} /><FunctionPicker functionValue={filters.jobFunction} roleValue={filters.jobRole} onChangeFunction={(value) => onChange("jobFunction", value)} onChangeRole={(value) => onChange("jobRole", value)} /><MultiValueEditor value={filters.keyword} onChange={(value) => onChange("keyword", value)} ariaLabel="关键词，可多选" placeholder="关键词，可多选" /><CompanyPicker value={filters.company} onChange={(value) => onChange("company", value)} companies={companies} /></div><div className="space-y-3"><PanelTitle>岗位要求</PanelTitle><PillField label="学历" options={EDUCATION.map((item) => ({ value: item === "不限" ? "" : item, label: item }))} value={filters.education} onChange={(value) => onChange("education", value)} /><PillField label="经验" options={EXPERIENCE} value={filters.experience} onChange={(value) => onChange("experience", value)} /></div><div className="space-y-3"><PanelTitle>岗位新鲜度</PanelTitle><PillField label="发布时间" options={POSTED_WITHIN} value={filters.postedWithin} onChange={(value) => onChange("postedWithin", value)} /><Toggle label="仅新岗位" checked={filters.showNewOnly} onChange={(value) => onChange("showNewOnly", value)} /></div><div className="space-y-3"><PanelTitle>公司</PanelTitle><PillField label="资本来源" options={ORIGINS.map((item) => ({ value: item === "全部" ? "" : item, label: item }))} value={filters.capitalOrigin} onChange={(value) => onChange("capitalOrigin", value)} /></div>{overseas && <div className="space-y-3"><PanelTitle>海外</PanelTitle><PillField label="目标地区" options={REGIONS} value={filters.region} onChange={(value) => onChange("region", value)} /><Toggle label="仅显示提供 Sponsorship 的岗位" checked={filters.sponsorshipOnly} onChange={(value) => onChange("sponsorshipOnly", value)} /></div>}<div className="space-y-3"><PanelTitle>展示</PanelTitle><Toggle label="仅显示公开薪资的岗位" checked={filters.salaryOnly} onChange={(value) => onChange("salaryOnly", value)} /><Toggle label="显示已忽略" checked={filters.showIgnored} onChange={(value) => onChange("showIgnored", value)} /><Toggle label="显示已投递" checked={filters.showApplied} onChange={(value) => onChange("showApplied", value)} /><PillField label="排序" options={[{ value: "match", label: "按匹配度" }, { value: "newest", label: "按发布时间" }]} value={filters.sortBy} onChange={(value) => onChange("sortBy", value as Filters["sortBy"])} /></div></div><div className="flex items-center gap-3 border-t border-black/[0.08] bg-[#f4efe6] px-5 py-4 pb-[max(1rem,env(safe-area-inset-bottom))] dark:border-white/[0.1] dark:bg-[#16130f]"><button type="button" onClick={onClearAll} className="t-label ink-3 shrink-0 px-2 py-2 hover:ink-1">重置全部</button><button type="button" onClick={onClose} className="btn-ink-sm min-w-0 flex-1"><span>查看</span><span className="t-num">{resultTotal}</span><span>个岗位</span></button></div></div></div>;
}

function PanelTitle({ children }: { children: ReactNode }) { return <h3 className="t-h3">{children}</h3>; }
function PillField({ label, options, value, onChange }: { label: string; options: Array<{ value: string; label: string }>; value: string; onChange: (value: string) => void }) { return <div className="space-y-2"><p className="t-label">{label}</p><PillGroup options={options} value={value} onChange={onChange} ariaLabel={label} /></div>; }
function PillGroup({ options, value, onChange, ariaLabel }: { options: Array<{ value: string; label: string }>; value: string; onChange: (value: string) => void; ariaLabel: string }) { return <div className="flex flex-wrap gap-2" aria-label={ariaLabel}>{options.map((option) => <button key={option.value || "all"} type="button" onClick={() => onChange(option.value)} aria-pressed={value === option.value} className={cn("t-label rounded-full border px-3 py-2 transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1a1714]/30 dark:focus-visible:ring-[#f3ecdf]/35", value === option.value ? buttonActive : buttonIdle)}>{option.label}</button>)}</div>; }
function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) { return <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-black/[0.08] bg-white/45 px-3 py-2.5 dark:border-white/[0.1] dark:bg-white/[0.04]"><span className="t-body-sm">{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="size-4 accent-[#1a1714] dark:accent-[#f3ecdf]" /></label>; }
function CountBadge({ count }: { count: number }) { return <span className="btn-ink-sm t-num absolute -right-1 -top-1 grid size-4 place-items-center !p-0">{count}</span>; }

type ActiveChip = { id: string; key: keyof Filters; value?: string; label: string };
function collectActiveChips(filters: Filters, overseas: boolean): ActiveChip[] {
  const values: ActiveChip[] = [];
  const addMany = (key: "city" | "keyword" | "jobFunction" | "jobRole", prefix = "") => splitMultiValue(filters[key]).forEach((value) => values.push({ id: `${key}-${value}`, key, value, label: `${prefix}${key === "jobRole" ? roleLabel(value) : value}` }));
  addMany("city");
  addMany("keyword");
  addMany("jobFunction");
  addMany("jobRole");
  const singles: Array<[keyof Filters, string, string]> = [["company", filters.company, "公司："], ["jobType", filters.jobType, ""], ["experience", labelFor(EXPERIENCE, filters.experience), ""], ["education", filters.education, ""], ["postedWithin", labelFor(POSTED_WITHIN, filters.postedWithin), ""], ["capitalOrigin", filters.capitalOrigin, ""], ["region", overseas ? labelFor(REGIONS, filters.region) : "", ""], ["sortBy", filters.sortBy === "newest" ? "按发布时间" : "", ""]];
  singles.forEach(([key, value, prefix]) => { if (value) values.push({ id: `${key}-${value}`, key, label: `${prefix}${value}` }); });
  ([["showNewOnly", filters.showNewOnly, "仅新岗位"], ["salaryOnly", filters.salaryOnly, "仅公开薪资"], ["sponsorshipOnly", overseas && filters.sponsorshipOnly, "仅 Sponsorship"], ["showIgnored", filters.showIgnored, "显示已忽略"], ["showApplied", filters.showApplied, "显示已投递"]] as Array<[keyof Filters, boolean, string]>).forEach(([key, enabled, label]) => { if (enabled) values.push({ id: String(key), key, label }); });
  return values;
}
function countPanelFilters(filters: Filters, overseas: boolean): number { return [filters.education, filters.experience, filters.postedWithin, filters.capitalOrigin, overseas ? filters.region : "", filters.showNewOnly, filters.salaryOnly, overseas && filters.sponsorshipOnly, filters.showIgnored, filters.showApplied, filters.sortBy !== "match"].filter(Boolean).length; }
function compactMultiValue(value: string): string { const items = splitMultiValue(value); return items.length > 1 ? `${items[0]} +${items.length - 1}` : items[0] || ""; }
// ⚠️ 空值必须返回空串，不能返回「不限」那一项的 label。
// 每个单选组的第一项都是 { value: "", label: "不限" / "全部海外" }，若照常查表，
// 「没选」会被翻译成「不限」这个**看起来像已选**的字符串 → ① 已选 chip 行凭空多出
// 「✕不限」（线上实测一次冒出两个：经验 + 发布时间）② 触发按钮显示成已选态。
// 「不限」是给弹层里的选项用的，不是给「已选摘要」用的。
function labelFor(options: Array<{ value: string; label: string }>, value: string): string {
  if (!value) return "";
  return options.find((option) => option.value === value)?.label || "";
}
