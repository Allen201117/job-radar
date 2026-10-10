"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { AUDIENCE_LABEL, type AnnouncementCard } from "@/lib/announcement-postings";
import {
  ANNOUNCEMENT_PAGE_SIZE,
  CLOSING_SOON_DAYS,
  EMPTY_FILTERS,
  UNKNOWN_REGION,
  activeFilterCount,
  announcementQueryParams,
  deadlineChip,
  type AnnouncementFilters,
  type AnnouncementResult,
  type AudienceFilter,
  type SortKey,
} from "@/lib/announcement-filters";

/** 分面选项；count 缺省 = 新条件的结果还没回来、此刻给不出准确数字（宁可不写，也不写一个对不上的）。 */
type FacetChoice = { value: string; count?: number };

/** 搜索框连着打字时等这么久再发请求，免得每敲一个字都打一次。 */
const QUERY_DEBOUNCE_MS = 250;

/** 「筛选 + 排序」的身份：用它判断屏幕上画着的结果是不是当前条件的。 */
function queryKey(filters: AnnouncementFilters, sort: SortKey): string {
  return announcementQueryParams({ filters, sort, offset: 0, limit: ANNOUNCEMENT_PAGE_SIZE, after: null }).toString();
}
const PRISTINE_KEY = queryKey(EMPTY_FILTERS, "newest");

/**
 * `key` 就是这组条件的查询串（见 queryKey）。翻页时带上「已经画了几条」和「最后一张卡是谁」：
 * 服务端优先从那张卡后面接着取（两次请求之间前面有公告下架也不会跳过后面的），找不到它才按条数取。
 */
async function fetchPostings(
  key: string,
  shownSoFar: readonly AnnouncementCard[],
  signal: AbortSignal,
): Promise<AnnouncementResult> {
  const params = new URLSearchParams(key);
  if (shownSoFar.length > 0) {
    params.set("offset", String(shownSoFar.length));
    params.set("after", shownSoFar[shownSoFar.length - 1].sourceUrl);
  }
  const res = await fetch(`/api/programs/postings?${params.toString()}`, { signal, cache: "no-store" });
  const body = await res.json().catch(() => null);
  // 形状要验全：缺了分面 / 总数的回包（比如部署切换那一刻）画出来会直接崩，宁可走「没载入成功 + 重试」。
  const ok = res.ok && body?.ok && Array.isArray(body.postings) && typeof body.total === "number"
    && typeof body.allTotal === "number" && Array.isArray(body.facets?.regions);
  if (!ok) throw new Error(`HTTP ${res.status}`);
  return body as AnnouncementResult;
}

/**
 * 招聘公告列表 + 筛选器。
 *
 * 筛选、排序、翻页都在**服务端**做：浏览器每次只拿当前条件下的一页 + 分面计数（/api/programs/postings）。
 * 原先是把全部公告发给浏览器再筛——在展示的公告从 455 条涨到 1,500 条后那一份已有 570KB，还会随天数涨。
 * 首屏（无筛选、最新发布）由服务端随页面算好下发（`initial`），不用再请求；回到无筛选状态时直接用它。
 *
 * 新条件的结果回来之前，屏幕上的旧卡片留着但压暗、计数先不写——**不拿上一组条件的数字冒充这一组的**。
 *
 * ⚠️ `today` 由**服务端**算好传进来（`todayInDisplayZone()`），客户端不要自己 `new Date()` ——
 * Vercel 函数跑 UTC、浏览器跑本地时区，两边各算一次「还剩几天」会导致水合文本不一致
 * （项目已因裸 toLocaleDateString 踩过 React #418，见 lib/relative-time 的注释）。
 */
export default function AnnouncementsClient({
  initial,
  today,
}: {
  initial: AnnouncementResult;
  today: string;
}) {
  const [filters, setFilters] = useState<AnnouncementFilters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<SortKey>("newest");
  // 屏幕上画着的结果，以及它是哪一组条件的。
  const [shown, setShown] = useState<{ key: string; result: AnnouncementResult }>({ key: PRISTINE_KEY, result: initial });
  const [failed, setFailed] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreFailed, setMoreFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const moreAbort = useRef<AbortController | null>(null);
  const lastSearch = useRef("");

  const wantKey = queryKey(filters, sort);

  useEffect(() => {
    // 条件一变，正在取的「下一页」就作废（它是上一组条件的）。
    moreAbort.current?.abort();
    setLoadingMore(false);
    setMoreFailed(false);
    setFailed(false);
    // 只有搜索框在打字时才等一等；点地区 / 类型 / 排序这些是一次性的动作，立刻发。
    const search = new URLSearchParams(wantKey).get("q") ?? "";
    const typing = search !== lastSearch.current;
    lastSearch.current = search;
    if (wantKey === PRISTINE_KEY) {
      setShown((cur) => (cur.key === PRISTINE_KEY && cur.result === initial ? cur : { key: PRISTINE_KEY, result: initial }));
      return;
    }
    const ctl = new AbortController();
    const run = () => {
      fetchPostings(wantKey, [], ctl.signal)
        .then((result) => setShown({ key: wantKey, result }))
        .catch((e: Error) => {
          if (ctl.signal.aborted) return;
          console.warn("[programs] 公告筛选请求失败:", e.message);
          setFailed(true);
        });
    };
    // 不打字时直接发，不过定时器：标签页在后台时浏览器会把定时器压到一秒一次。
    const timer = typing ? setTimeout(run, QUERY_DEBOUNCE_MS) : null;
    if (!typing) run();
    return () => {
      if (timer) clearTimeout(timer);
      ctl.abort();
    };
    // attempt 变 = 用户点了重试。
  }, [wantKey, attempt, initial]);

  const loadMore = useCallback(() => {
    const ctl = new AbortController();
    moreAbort.current?.abort();
    moreAbort.current = ctl;
    setLoadingMore(true);
    setMoreFailed(false);
    const key = shown.key;
    fetchPostings(key, shown.result.postings, ctl.signal)
      .then((next) => {
        setShown((cur) => {
          if (cur.key !== key) return cur;
          // 两次请求之间服务端缓存可能换过一批：按入口链接去重，别把同一张卡画两遍。
          const have = new Set(cur.result.postings.map((p) => p.sourceUrl));
          const fresh = next.postings.filter((p) => !have.has(p.sourceUrl));
          const postings = [...cur.result.postings, ...fresh];
          // 一条新的都没带回来（后面的在这期间下架了）：就到这儿，别让「加载更多」原地打转。
          return { key, result: { ...next, postings, total: fresh.length ? next.total : postings.length } };
        });
        setLoadingMore(false);
      })
      .catch((e: Error) => {
        if (ctl.signal.aborted) return;
        console.warn("[programs] 加载更多失败:", e.message);
        setLoadingMore(false);
        setMoreFailed(true);
      });
  }, [shown]);

  useEffect(() => () => moreAbort.current?.abort(), []);

  // 屏幕上的结果是不是当前条件的。不是 = 新结果还在路上。
  const settled = shown.key === wantKey;
  const result = shown.result;
  const facets = settled ? result.facets : null;
  const displayed = result.postings;
  const totalCount = result.allTotal;
  const visibleCount = settled ? result.total : null;
  const activeCount = activeFilterCount(filters);
  const retry = () => setAttempt((n) => n + 1);
  const patch = (p: Partial<AnnouncementFilters>) => setFilters((f) => ({ ...f, ...p }));
  const withCount = (label: string, n: number | undefined) => (n === undefined ? label : `${label} ${n}`);
  // 新结果没回来时下拉里照样列出可选值（上一组结果里的），只是先不写数字。
  const regionChoices: FacetChoice[] = facets ? facets.regions : result.facets.regions.map((f) => ({ value: f.value }));
  const employerChoices: FacetChoice[] = facets
    ? facets.employerTypes
    : result.facets.employerTypes.map((f) => ({ value: f.value }));

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
          onChange={setSort}
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
            onClick={() => setFilters(EMPTY_FILTERS)}
            className="t-label ink-3 ml-auto shrink-0 px-2 py-1 hover:ink-1"
          >
            清空全部
          </button>
        </div>
      ) : null}

      <p className="t-caption ink-3 mt-3" aria-live="polite">
        {visibleCount === null ? (
          failed ? "这组条件没筛成功" : (
            <span className="inline-flex items-center gap-2">
              <Spinner size={12} label={null} />
              正在按你的条件筛选…
            </span>
          )
        ) : activeCount > 0
          ? `在 ${totalCount} 条自动收录的公告里筛出 ${visibleCount} 条`
          : `共 ${totalCount} 条自动收录、正在报名的官方公告`}
        {visibleCount !== null && filters.closingWithinDays !== null && result.unknownDeadlineCount > 0
          ? `；截止日待确认的 ${result.unknownDeadlineCount} 条不计入“${CLOSING_SOON_DAYS} 天内截止”`
          : null}
      </p>

      {failed ? (
        <div className="mt-5">
          <EmptyState
            tone="error"
            title="公告列表没载入成功"
            description="刚才这组条件没取到结果。网络恢复后点重试；清空筛选可以先看最新发布的一页。"
            action={<Button variant="soft" size="sm" onClick={retry}>重试</Button>}
          />
        </div>
      ) : visibleCount === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="没有符合条件的公告"
            description="换个地区或放宽条件试试——公告每天从各省人社厅官网和国聘收录，过了报名截止日的会自动下架。"
          />
        </div>
      ) : (
        // 新条件的结果还在路上时，上一组的卡片留着但压暗：比整块换成转圈更稳，也不会让人以为这就是新结果。
        <ul
          className={cn("mt-5 grid gap-4 transition-opacity lg:grid-cols-2", settled ? "" : "pointer-events-none opacity-50")}
          aria-busy={!settled}
        >
          {displayed.map((p) => (
            <PostingCard key={p.sourceUrl} posting={p} today={today} />
          ))}
        </ul>
      )}
      {!failed && visibleCount !== null && visibleCount > displayed.length ? (
        <div className="mt-5 flex justify-center">
          <Button variant="soft" size="sm" loading={loadingMore} onClick={loadMore}>
            {moreFailed ? "没载入成功，点此重试" : `加载更多（还有 ${visibleCount - displayed.length} 条）`}
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

const CHIP_TONE = {
  rose: "border-tone-rose-border bg-tone-rose-bg text-tone-rose-fg",
  amber: "border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
  neutral: "border-tone-neutral-border bg-tone-neutral-bg text-tone-neutral-fg",
};

/** 官方招聘公告卡。标题即公告名，突出地区/受众/报名截止日。 */
function PostingCard({ posting, today }: { posting: AnnouncementCard; today: string }) {
  const audience = AUDIENCE_LABEL[posting.audience];
  const chip = deadlineChip(posting, today);
  return (
    <li className="surface surface-hover flex h-full flex-col p-5">
      <div className="flex flex-wrap items-center gap-2">
        {/* 地区由读侧定好（库里的值，没有才按标题补），与筛选器读的是同一个字段——这里别再自己另推一遍。 */}
        {posting.region ? (
          <Badge tone="neutral" size="xs">
            <MapPin size={11} weight="fill" aria-hidden className="mr-0.5 inline shrink-0" />
            {posting.region}
          </Badge>
        ) : <Badge tone="neutral" size="xs">{UNKNOWN_REGION}</Badge>}
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
