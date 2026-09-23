"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowSquareOut,
  CalendarBlank,
  CaretDown,
  Check,
  Info,
  MagnifyingGlass,
  MapPin,
  SealCheck,
  X,
} from "@phosphor-icons/react";
import { Badge, Button, EmptyState, Popover, Segmented, Spinner, buttonVariants } from "@/components/ui";
import { cn } from "@/lib/utils";
import { formatDateLabel } from "@/lib/relative-time";
import { AUDIENCE_LABEL, inferAnnouncementRegion, type AnnouncementCard } from "@/lib/announcement-postings";
import {
  ANNOUNCEMENT_PAGE_SIZE,
  CLOSING_SOON_DAYS,
  EMPTY_FILTERS,
  activeFilterCount,
  buildFacets,
  daysUntilDeadline,
  matchesFilters,
  sortPostings,
  type AnnouncementFilters,
  type AudienceFilter,
  type InitialAnnouncementView,
  type SortKey,
} from "@/lib/announcement-filters";

const INITIAL_VISIBLE_COUNT = ANNOUNCEMENT_PAGE_SIZE;

/** 分面选项；count 缺省 = 全量还没到货、此刻给不出准确数字（宁可不写，也不写一个对不上的）。 */
type FacetChoice = { value: string; count?: number };

/**
 * 招聘公告列表 + 筛选器。
 *
 * 首屏（无筛选、最新发布）由服务端算好下发（`initial`）；全量公告挂载后从 /api/programs/postings 取，
 * 到货后筛选、排序、加载更多都在浏览器里即时算。全量没到之前，只有首屏那一种状态画得出准确结果——
 * 用户在这之前动了筛选，就先显示「正在载入」，**不拿首屏的数字冒充筛选后的数字**。
 *
 * ⚠️ `today` 由**服务端**算好传进来（`todayInDisplayZone()`），客户端不要自己 `new Date()` ——
 * Vercel 函数跑 UTC、浏览器跑本地时区，两边各算一次「还剩几天」会导致水合文本不一致
 * （项目已因裸 toLocaleDateString 踩过 React #418，见 lib/relative-time 的注释）。
 */
export default function AnnouncementsClient({
  initial,
  today,
}: {
  initial: InitialAnnouncementView;
  today: string;
}) {
  const [filters, setFilters] = useState<AnnouncementFilters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<SortKey>("newest");
  const [shownCount, setShownCount] = useState(INITIAL_VISIBLE_COUNT);
  const [all, setAll] = useState<AnnouncementCard[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    setLoadFailed(false);
    fetch("/api/programs/postings", { signal: ctl.signal, cache: "no-store" })
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok || !body?.ok || !Array.isArray(body.postings)) throw new Error(`HTTP ${res.status}`);
        // 首屏明明有公告、全量却是空的 = 取数出了问题（取数层失败时返回空数组），不能当成「全都下架了」。
        if (body.postings.length === 0 && initial.total > 0) throw new Error("empty_postings");
        setAll(body.postings as AnnouncementCard[]);
      })
      .catch((e: Error) => {
        if (ctl.signal.aborted) return;
        console.warn("[programs] 全量公告加载失败:", e.message);
        setLoadFailed(true);
      });
    return () => ctl.abort();
  }, [attempt, initial.total]);

  // 全量到货前唯一画得准的状态 = 无筛选 + 最新发布（服务端用同一套函数算好的首屏）。
  const pristine = activeFilterCount(filters) === 0 && sort === "newest";
  const facets = useMemo(
    () => (all ? buildFacets(all, filters, today) : pristine ? initial.facets : null),
    [all, filters, today, pristine, initial.facets],
  );
  const visible = useMemo(
    () =>
      all
        ? sortPostings(all.filter((p) => matchesFilters(p, filters, today)), sort, today)
        : pristine
          ? initial.postings
          : null,
    [all, filters, today, sort, pristine, initial.postings],
  );
  const totalCount = all ? all.length : initial.total;
  // 当前筛选下一共几条；首屏态 visible 只有一页，总数要用服务端给的。
  const visibleCount = all ? (visible?.length ?? 0) : pristine ? initial.total : null;
  const unknownDeadlineCount = all
    ? all.filter((posting) => !posting.deadline).length
    : initial.unknownDeadlineCount;
  const displayed = visible ? visible.slice(0, shownCount) : [];
  const activeCount = activeFilterCount(filters);
  const waitingForAll = !all && !loadFailed;
  const retry = () => setAttempt((n) => n + 1);
  const patch = (p: Partial<AnnouncementFilters>) => {
    setFilters((f) => ({ ...f, ...p }));
    setShownCount(INITIAL_VISIBLE_COUNT);
  };
  const withCount = (label: string, n: number | undefined) => (n === undefined ? label : `${label} ${n}`);
  // 全量没到时下拉里照样列出全部可选值（来自首屏分面），只是先不写数字。
  const regionChoices: FacetChoice[] = facets ? facets.regions : initial.facets.regions.map((f) => ({ value: f.value }));
  const employerChoices: FacetChoice[] = facets
    ? facets.employerTypes
    : initial.facets.employerTypes.map((f) => ({ value: f.value }));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-0 flex-1 sm:max-w-xs">
          <MagnifyingGlass
            size={15}
            weight="bold"
            aria-hidden
            className="ink-3 pointer-events-none absolute left-3 top-1/2 -translate-y-1/2"
          />
          <input
            type="search"
            value={filters.q}
            onChange={(e) => patch({ q: e.target.value })}
            placeholder="可搜：标题、地区、单位类型"
            aria-label="搜索招聘公告"
            className="t-body-sm w-full rounded-full border border-black/[0.08] bg-white/70 py-2 pl-9 pr-3 outline-none placeholder:ink-4 focus:border-black/20 dark:border-white/[0.12] dark:bg-white/[0.06]"
          />
        </label>

        <FacetDropdown
          label="地区"
          selected={filters.region}
          facets={regionChoices}
          onSelect={(v) => patch({ region: v })}
        />
        <FacetDropdown
          label="单位类型"
          selected={filters.employerType}
          facets={employerChoices}
          onSelect={(v) => patch({ employerType: v })}
        />

        <Segmented<AudienceFilter>
          ariaLabel="按招聘对象筛选"
          size="sm"
          value={filters.audience}
          onChange={(v) => patch({ audience: v })}
          options={[
            { value: "all", label: withCount("全部", facets?.audience.all) },
            { value: "fresh_grad", label: withCount("应届", facets?.audience.fresh_grad) },
            { value: "experienced", label: withCount("社会", facets?.audience.experienced) },
          ]}
        />

        <button
          type="button"
          aria-pressed={filters.closingWithinDays !== null}
          onClick={() =>
            patch({ closingWithinDays: filters.closingWithinDays === null ? CLOSING_SOON_DAYS : null })
          }
          className={cn(
            "press-feedback t-label inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 transition-colors",
            filters.closingWithinDays !== null
              ? "border-tone-rose-border bg-tone-rose-bg text-tone-rose-fg"
              : "ink-2 border-black/[0.08] bg-white/70 hover:border-black/20 dark:border-white/[0.12] dark:bg-white/[0.06]",
          )}
        >
          <CalendarBlank size={14} weight="bold" aria-hidden />
          {withCount(`${CLOSING_SOON_DAYS} 天内截止`, facets?.closingSoon)}
        </button>

        <Segmented<SortKey>
          ariaLabel="排序方式"
          size="sm"
          value={sort}
          onChange={(value) => { setSort(value); setShownCount(INITIAL_VISIBLE_COUNT); }}
          options={[
            { value: "newest", label: "最新发布" },
            { value: "closing", label: "最快截止" },
          ]}
        />
      </div>

      {activeCount > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {filters.region ? (
            <FilterChip label={filters.region} onClear={() => patch({ region: null })} />
          ) : null}
          {filters.employerType ? (
            <FilterChip label={filters.employerType} onClear={() => patch({ employerType: null })} />
          ) : null}
          {filters.audience !== "all" ? (
            <FilterChip
              label={filters.audience === "fresh_grad" ? "应届" : "社会"}
              onClear={() => patch({ audience: "all" })}
            />
          ) : null}
          {filters.closingWithinDays !== null ? (
            <FilterChip
              label={`${CLOSING_SOON_DAYS} 天内截止`}
              onClear={() => patch({ closingWithinDays: null })}
            />
          ) : null}
          {filters.q.trim() ? (
            <FilterChip label={`“${filters.q.trim()}”`} onClear={() => patch({ q: "" })} />
          ) : null}
          <button
            type="button"
            onClick={() => { setFilters(EMPTY_FILTERS); setShownCount(INITIAL_VISIBLE_COUNT); }}
            className="t-label ink-3 ml-auto shrink-0 px-2 py-1 hover:ink-1"
          >
            清空全部
          </button>
        </div>
      ) : null}

      <p className="t-caption ink-3 mt-3" aria-live="polite">
        {visibleCount === null
          ? `正在载入全部 ${totalCount} 条公告…`
          : activeCount > 0
            ? `在 ${totalCount} 条自动收录的公告里筛出 ${visibleCount} 条`
            : `共 ${totalCount} 条自动收录、正在报名的官方公告`}
        {visibleCount !== null && filters.closingWithinDays !== null && unknownDeadlineCount > 0
          ? `；截止日待确认的 ${unknownDeadlineCount} 条不计入“${CLOSING_SOON_DAYS} 天内截止”`
          : null}
      </p>

      {visible === null ? (
        <div className="mt-5">
          {loadFailed ? (
            <EmptyState
              tone="error"
              title="公告列表没载入成功"
              description="筛选要用到全部公告，刚才没取到。网络恢复后点重试；清空筛选可以先看最新发布的一页。"
              action={<Button variant="soft" size="sm" onClick={retry}>重试</Button>}
            />
          ) : (
            <p className="t-body-sm ink-3 inline-flex items-center gap-2">
              <Spinner size={14} label={null} />
              正在载入全部公告，马上按你的条件筛出来
            </p>
          )}
        </div>
      ) : visibleCount === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="没有符合条件的公告"
            description="换个地区或放宽条件试试——公告每天从各省人社厅官网抓取并复验，报名已截止的会自动下架。"
          />
        </div>
      ) : (
        <ul className="mt-5 grid gap-4 lg:grid-cols-2">
          {displayed.map((p) => (
            <PostingCard key={p.sourceUrl} posting={p} today={today} />
          ))}
        </ul>
      )}
      {visibleCount !== null && visibleCount > displayed.length ? (
        <div className="mt-5 flex justify-center">
          {/* 首屏态点「加载更多」时全量可能还没到：先把页数记下，到货即展开，按钮上显示在等。 */}
          <Button
            variant="soft"
            size="sm"
            loading={waitingForAll && shownCount > displayed.length}
            onClick={() => {
              if (loadFailed) retry();
              if (shownCount <= displayed.length) setShownCount((count) => count + INITIAL_VISIBLE_COUNT);
            }}
          >
            {loadFailed && shownCount > displayed.length
              ? "没载入成功，点此重试"
              : `加载更多（还有 ${visibleCount - displayed.length} 条）`}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <button type="button" onClick={onClear} className="chip ink-2 press-feedback-subtle">
      <X size={12} weight="bold" aria-hidden />
      {label}
    </button>
  );
}

/** 单选下拉分面（地区 / 单位类型）。计数忽略该维度自身的选择，见 lib/announcement-filters 文件头。 */
function FacetDropdown({
  label,
  selected,
  facets,
  onSelect,
}: {
  label: string;
  selected: string | null;
  facets: FacetChoice[];
  onSelect: (value: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);
  if (facets.length === 0 && !selected) return null;

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          "press-feedback t-label inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 transition-colors",
          selected
            ? "border-tone-sky-border bg-tone-sky-bg text-tone-sky-fg"
            : "ink-2 border-black/[0.08] bg-white/70 hover:border-black/20 dark:border-white/[0.12] dark:bg-white/[0.06]",
        )}
      >
        {selected ?? label}
        <CaretDown size={12} weight="bold" aria-hidden />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={anchorRef}
        ariaLabel={`选择${label}`}
        className="max-h-80 w-56 overflow-y-auto p-1.5"
      >
        <FacetOption active={selected === null} label={`全部${label}`} onClick={() => { onSelect(null); setOpen(false); }} />
        {facets.map((f) => (
          <FacetOption
            key={f.value}
            active={selected === f.value}
            label={f.value}
            count={f.count}
            onClick={() => { onSelect(f.value); setOpen(false); }}
          />
        ))}
      </Popover>
    </>
  );
}

function FacetOption({
  active, label, count, onClick,
}: { active: boolean; label: string; count?: number; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="t-body-sm ink-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left hover:bg-black/[0.04] dark:hover:bg-white/[0.06]"
    >
      <Check size={13} weight="bold" aria-hidden className={cn("shrink-0", active ? "opacity-100" : "opacity-0")} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== undefined ? <span className="t-caption ink-3 shrink-0">{count}</span> : null}
    </button>
  );
}

/** 报名截止的展示文案 + 紧迫度色。 */
function deadlineChip(posting: AnnouncementCard, today: string) {
  const left = daysUntilDeadline(posting.deadline, today);
  if (left === null) {
    return posting.deadlineText
      ? { tone: "neutral" as const, text: `报名时间：${posting.deadlineText}` }
      : { tone: "neutral" as const, text: "报名时间以公告为准" };
  }
  const date = formatDateLabel(posting.deadline);
  if (left <= 0) return { tone: "rose" as const, text: `今天 ${date} 截止报名` };
  if (left <= CLOSING_SOON_DAYS) return { tone: "rose" as const, text: `还剩 ${left} 天 · ${date} 截止` };
  return { tone: "amber" as const, text: `报名截止 ${date}` };
}

const CHIP_TONE = {
  rose: "border-tone-rose-border bg-tone-rose-bg text-tone-rose-fg",
  amber: "border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
  neutral: "border-tone-neutral-border bg-tone-neutral-bg text-tone-neutral-fg",
};

/** 官方招聘公告卡。标题即公告名，突出地区/受众/报名截止日。 */
function PostingCard({ posting, today }: { posting: AnnouncementCard; today: string }) {
  const audience = AUDIENCE_LABEL[posting.audience];
  const chip = deadlineChip(posting, today);
  const region = posting.region ?? inferAnnouncementRegion(posting.title);
  return (
    <li className="surface surface-hover flex h-full flex-col p-5">
      <div className="flex flex-wrap items-center gap-2">
        {region ? (
          <Badge tone="neutral" size="xs">
            <MapPin size={11} weight="fill" aria-hidden className="mr-0.5 inline shrink-0" />
            {region}
          </Badge>
        ) : <Badge tone="neutral" size="xs">地区未标注</Badge>}
        {audience ? (
          <Badge tone={posting.audience === "experienced" ? "neutral" : "green"} size="xs">
            {audience}
          </Badge>
        ) : null}
        {posting.employerType ? <Badge tone="neutral" size="xs">{posting.employerType}</Badge> : null}
      </div>
      <h3 className="t-h3 mt-2">{posting.title}{posting.sameTitleHint && <span className="t-body-sm ink-3 font-normal">（{posting.sameTitleHint}）</span>}</h3>

      <p className={cn("t-caption mt-3 inline-flex items-start gap-1.5 rounded-lg border px-2.5 py-1.5", CHIP_TONE[chip.tone])}>
        <CalendarBlank size={14} weight="bold" aria-hidden className="mt-0.5 shrink-0" />
        <span>{chip.text}</span>
      </p>

      {/* 汇总索引页：本页不收报名，得再跳一次。说清楚，别让用户点进去扑空 */}
      {posting.verdict === "index_page" ? (
        <p className="t-caption ink-3 mt-2 inline-flex items-start gap-1.5">
          <Info size={13} weight="fill" aria-hidden className="mt-0.5 shrink-0" />
          <span>官方汇总页：列出多家单位与岗位，报名入口在各单位自己的网站</span>
        </p>
      ) : null}

      {posting.employerUnclear ? (
        <p className="t-caption ink-3 mt-2 inline-flex items-start gap-1.5">
          <Info size={13} weight="fill" aria-hidden className="mt-0.5 shrink-0" />
          <span>招聘单位未写明，投递前请看原公告</span>
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-black/[0.06] pt-4 dark:border-white/[0.08]">
        <span className="t-caption ink-3 inline-flex items-center gap-1.5">
          <SealCheck size={14} weight="fill" aria-hidden className="shrink-0" />
          {posting.publishedAt ? `${formatDateLabel(posting.publishedAt)} 官方发布` : "官方公告"}
        </span>
        <a
          className={cn(buttonVariants({ variant: "ink", size: "sm" }), "press-feedback")}
          href={posting.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          去官方公告投递
          <ArrowSquareOut size={14} weight="bold" aria-hidden />
        </a>
      </div>
    </li>
  );
}
