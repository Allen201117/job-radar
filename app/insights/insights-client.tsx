"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowSquareOut,
  CaretDown,
  ChatCircleText,
  MagnifyingGlass,
  Buildings,
  TreeStructure,
} from "@phosphor-icons/react";
import InsightSubmitForm from "@/components/InsightSubmitForm";
import ActionToast, { useActionToast } from "@/components/ActionToast";
import { assertionChip, ASSERTION_LABEL, ASSERTION_PROMISE } from "@/lib/insight-assertion-chip";
import {
  DIMENSION_LABEL,
  FRESHNESS_LABEL,
  GRADE_LABEL,
  METRIC_LABEL,
  missingContributionTopics,
  type LibraryCardMetric,
  type LibraryFacets,
  type LibrarySubject,
} from "@/lib/insight-library";
import { formatDateLabel } from "@/lib/relative-time";
import type { InsightAssertion, InsightItemView } from "@/lib/types";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui";

type Props = {
  initialSubjects: LibrarySubject[];
  initialTotal: number;
  initialFacets: LibraryFacets;
  /** 服务端从 URL 解析出的初始筛选；页面刷新 / 分享链接都靠它。 */
  initialFilters?: Partial<Filters>;
  subjectTotal: number;
};

type Filters = {
  q: string;
  kind: string;
  assertion: string;
  dimension: string;
  metric: string;
  /** 选中指标的数值上下限。用户要的常常是「加班**少**的公司」，所以上限不能省。 */
  metricMin: string;
  metricMax: string;
  freshness: string;
  sort: string;
};

const EMPTY: Filters = {
  q: "",
  kind: "",
  assertion: "",
  dimension: "",
  metric: "",
  metricMin: "",
  metricMax: "",
  freshness: "",
  sort: "fresh",
};

const SORT_LABEL: Record<string, string> = {
  fresh: "最新核实",
  insights: "洞察最多",
  sample: "样本量最大",
  jobs: "在招规模最大",
};

// 洞察库现在只承载「官方事实」与「公开说法」两档；第一方数据层（signal）已从本页撤下
// （2026-09-03 创始人定调：招聘结构不算信息差）。派生链仍在后台跑，趋势出来后再单独放回。
const ASSERTION_ORDER: InsightAssertion[] = ["fact", "claim"];

function toQuery(filters: Filters, page: number): string {
  const params = new URLSearchParams();
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.assertion) params.set("assertion", filters.assertion);
  if (filters.dimension) params.set("dimension", filters.dimension);
  if (filters.metric) params.set("metric", filters.metric);
  // 阈值只在选了指标时才有意义：没有指标就没有「大于多少」这回事。
  if (filters.metric && filters.metricMin.trim()) params.set("metricMin", filters.metricMin.trim());
  if (filters.metric && filters.metricMax.trim()) params.set("metricMax", filters.metricMax.trim());
  if (filters.freshness) params.set("freshness", filters.freshness);
  if (filters.sort && filters.sort !== "fresh") params.set("sort", filters.sort);
  if (page > 1) params.set("page", String(page));
  return params.toString();
}

export default function InsightsClient({
  initialSubjects,
  initialTotal,
  initialFacets,
  initialFilters,
  subjectTotal,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [filters, setFilters] = useState<Filters>({ ...EMPTY, ...(initialFilters || {}) });
  const [subjects, setSubjects] = useState(initialSubjects);
  const [facets, setFacets] = useState(initialFacets);
  const [total, setTotal] = useState(initialTotal);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const firstRender = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const { toast, show: showToast, dismiss: dismissToast } = useActionToast();

  const load = useCallback(
    async (next: Filters, nextPage: number, append: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      append ? setLoadingMore(true) : setLoading(true);
      setError("");
      try {
        const res = await fetch(`/api/insights/library?${toQuery(next, nextPage)}`, {
          signal: controller.signal,
        });
        const json = await res.json();
        if (!res.ok || !json.ok) throw new Error(json?.error || "load_failed");
        setSubjects((prev) => (append ? [...prev, ...json.subjects] : json.subjects));
        setFacets(json.facets);
        setTotal(json.total);
        setPage(nextPage);
      } catch (err: any) {
        if (err?.name === "AbortError") return;
        // 失败不许静默：用户改了筛选却什么都没变，会以为「就是没有数据」。
        setError("筛选没加载出来，请重试");
      } finally {
        append ? setLoadingMore(false) : setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (firstRender.current) {
      // 首屏由服务端按 URL 里的筛选渲染好了，别再多打一次一样的请求。
      firstRender.current = false;
      return;
    }
    const timer = setTimeout(() => {
      load(filters, 1, false);
      // 把筛选同步进地址栏：可分享、可收藏、刷新不丢。
      // 用 replace 而不是 push —— 连续调筛选不该把浏览器后退键塞满。
      const qs = toQuery(filters, 1);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    }, 250);
    return () => clearTimeout(timer);
  }, [filters, load, pathname, router]);

  const active = useMemo(
    () =>
      // metricMin 不单独成 chip：它显示在「指标」那颗 chip 里（「近 30 天新挂出 ≥ 50」）。
      (Object.keys(filters) as Array<keyof Filters>).filter(
        (k) => k !== "sort" && k !== "metricMin" && k !== "metricMax" && filters[k],
      ),
    [filters],
  );

  const set = (patch: Partial<Filters>) => setFilters((prev) => ({ ...prev, ...patch }));
  const hasMore = subjects.length < total;

  return (
    <div className="mt-8">
      <PromiseLegend />

      {/* 筛选条：吸顶横条，与 /jobs 同形态（不做展开/收起手风琴，见 CLAUDE.md 筛选器规约） */}
      <div className="sticky top-[3.75rem] z-20 -mx-4 mb-5 border-y border-black/[0.06] bg-[#f4efe6]/92 px-4 py-2.5 backdrop-blur dark:border-white/[0.08] dark:bg-[#17140f]/92">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <MagnifyingGlass
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 ink-4"
            />
            <input
              value={filters.q}
              onChange={(e) => set({ q: e.target.value })}
              placeholder="搜公司或业务线"
              className="w-52 rounded-full border border-black/[0.08] bg-white/70 py-1.5 pl-8 pr-3 t-label ink-1 outline-none transition focus:border-[#3f7cc0]/40 dark:border-white/[0.1] dark:bg-white/[0.06]"
            />
          </label>

          <Select
            value={filters.kind}
            onChange={(v) => set({ kind: v })}
            placeholder="全部主体"
            options={facets.kind.map((b) => ({
              value: b.key,
              label: `${b.key ==="company"?"公司":"业务线"}（${b.count}）`,
            }))}
          />
          <Select
            value={filters.assertion}
            onChange={(v) => set({ assertion: v })}
            placeholder="全部强度"
            options={ASSERTION_ORDER.filter((a) => facets.assertion.some((b) => b.key === a)).map(
              (a) => ({
                value: a,
                label: `${ASSERTION_LABEL[a]}（${
                  facets.assertion.find((b) => b.key === a)?.count ?? 0
                }）`,
              }),
            )}
          />
          <Select
            value={filters.dimension}
            onChange={(v) => set({ dimension: v })}
            placeholder="全部维度"
            options={facets.dimension.map((b) => ({
              value: b.key,
              label: `${DIMENSION_LABEL[b.key as keyof typeof DIMENSION_LABEL] || b.key}（${b.count}）`,
            }))}
          />
          <Select
            value={filters.metric}
            onChange={(v) =>
              set({
                metric: v,
                metricMin: v ? filters.metricMin : "",
                metricMax: v ? filters.metricMax : "",
              })
            }
            placeholder="全部主题"
            options={facets.metric.map((b) => ({
              value: b.key,
              label: `${METRIC_LABEL[b.key] || b.key}（${b.count}）`,
            }))}
          />
          {filters.metric && (
            <label className={cn(buttonVariants({ variant: "soft", size: "xs" }), "inline-flex items-center gap-1.5")}>
              <span className="t-label ink-3">≥</span>
              <input
                type="number"
                inputMode="decimal"
                value={filters.metricMin}
                onChange={(e) => set({ metricMin: e.target.value })}
                placeholder="下限"
                className="w-16 bg-transparent t-label ink-1 outline-none"
              />
              <span className="t-label ink-3">≤</span>
              <input
                type="number"
                inputMode="decimal"
                value={filters.metricMax}
                onChange={(e) => set({ metricMax: e.target.value })}
                placeholder="上限"
                className="w-16 bg-transparent t-label ink-1 outline-none"
              />
            </label>
          )}
          <Select
            value={filters.freshness}
            onChange={(v) => set({ freshness: v })}
            placeholder="全部时效"
            options={facets.freshness.map((b) => ({
              value: b.key,
              label: `${FRESHNESS_LABEL[b.key] || b.key}（${b.count}）`,
            }))}
          />

          <div className="ml-auto flex items-center gap-2">
            <Select
              value={filters.sort}
              onChange={(v) => set({ sort: v || "fresh" })}
              placeholder="排序"
              options={Object.entries(SORT_LABEL).map(([value, label]) => ({ value, label }))}
              allowEmpty={false}
            />
          </div>
        </div>

        {active.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {active.map((key) => (
              <button
                key={key}
                type="button"
                onClick={() =>
                  set(
                    (key === "metric"
                      ? { metric: "", metricMin: "", metricMax: "" }
                      : { [key]: "" }) as Partial<Filters>,
                  )
                }
                className="rounded-full border border-[#3f7cc0]/25 bg-[#e6eef8] px-2.5 py-1 t-micro text-[#2f6299] transition hover:bg-[#dbe7f6] dark:border-[#7fb2e8]/25 dark:bg-[#7fb2e8]/[0.14] dark:text-[#7fb2e8]"
              >
                {labelFor(key, filters)} ✕
              </button>
            ))}
            <button
              type="button"
              onClick={() => setFilters({ ...EMPTY, sort: filters.sort })}
              className="rounded-full px-2 py-1 t-micro ink-3 underline-offset-2 hover:underline"
            >
              全部清除
            </button>
          </div>
        )}
      </div>

      <p className="mb-4 t-caption ink-3">
        {loading ? (
          "正在筛选…"
        ) : (
          <>
            {total} 个主体{active.length > 0 ? "符合筛选" : ""}
            <span className="ink-4">（洞察库共 {subjectTotal} 个公司与业务线主体）</span>
          </>
        )}
      </p>

      {error && (
        <div className="mb-4 rounded-xl border border-[#d99a8a] bg-[#fbe9e4] px-4 py-3 t-body-sm text-[#9c4a33] dark:border-[#d99a8a]/30 dark:bg-[#d99a8a]/[0.12] dark:text-[#e8b0a0]">
          {error}
          <button
            type="button"
            onClick={() => load(filters, 1, false)}
            className="ml-2 underline underline-offset-2"
          >
            重试
          </button>
        </div>
      )}

      {subjects.length === 0 && !loading ? (
        <div className="rounded-2xl border border-black/[0.06] bg-white/55 px-5 py-8 text-center dark:border-white/[0.1] dark:bg-white/[0.05]">
          <p className="t-body ink-2">没有主体同时满足这些条件。</p>
          <p className="mt-1 t-caption ink-3">
            试着放宽一个条件——我们宁可少显示，也不用样本不足的数字凑数。
          </p>
        </div>
      ) : (
        <div className="grid gap-3.5">
          {subjects.map((subject) => (
            <SubjectCard
              key={subject.id}
              subject={subject}
              onToast={(text) => showToast({ text })}
            />
          ))}
        </div>
      )}

      {hasMore && (
        <div className="mt-6 text-center">
          <button
            type="button"
            disabled={loadingMore}
            onClick={() => load(filters, page + 1, true)}
            className="rounded-full border border-black/[0.08] bg-white/70 px-5 py-2 t-label ink-2 transition hover:bg-white disabled:opacity-60 dark:border-white/[0.1] dark:bg-white/[0.06]"
          >
            {loadingMore ? "加载中…" : `加载更多（还有 ${total - subjects.length} 个）`}
          </button>
        </div>
      )}

      <ActionToast toast={toast} onDismiss={dismissToast} />
    </div>
  );
}

/** 卡面正文。正文取不到时退回结构化字段拼一句，绝不显示空白。 */
function metricText(m: LibraryCardMetric): string {
  if (m.content) return m.content;
  const value = m.metric_value == null ? "" : `${m.metric_value}${m.metric_unit ||""}`;
  const n = m.sample_size == null ? "" : `（基于 ${m.sample_size} 个在招岗）`;
  return `${METRIC_LABEL[m.metric_key] || m.metric_key} ${value}${n}`.trim();
}

/** 档位类指标（加班强度/晋升节奏/实习体验）把 1–5 翻成人话，直接贴在指标名后面。 */
function gradeText(metricKey: string, value: number | null): string {
  if (value == null) return "";
  return GRADE_LABEL[metricKey]?.[Math.round(value)] || "";
}

function labelFor(key: keyof Filters, filters: Filters): string {
  const value = filters[key];
  if (key === "q") return `搜索「${value}」`;
  if (key === "kind") return value === "company" ? "公司" : "业务线";
  if (key === "assertion") return ASSERTION_LABEL[value as InsightAssertion] || value;
  if (key === "dimension") return DIMENSION_LABEL[value as keyof typeof DIMENSION_LABEL] || value;
  if (key === "metric") {
    const label = METRIC_LABEL[value] || value;
    const lo = filters.metricMin.trim();
    const hi = filters.metricMax.trim();
    if (lo && hi) return `${label} ${lo}–${hi}`;
    if (lo) return `${label} ≥ ${lo}`;
    if (hi) return `${label} ≤ ${hi}`;
    return label;
  }
  if (key === "freshness") return FRESHNESS_LABEL[value] || value;
  return value;
}

function Select({
  value,
  onChange,
  options,
  placeholder,
  allowEmpty = true,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder: string;
  allowEmpty?: boolean;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="appearance-none rounded-full border border-black/[0.08] bg-white/70 py-1.5 pl-3 pr-7 t-label ink-2 outline-none transition focus:border-[#3f7cc0]/40 dark:border-white/[0.1] dark:bg-white/[0.06]"
      >
        {allowEmpty && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <CaretDown
        size={12}
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 ink-4"
      />
    </div>
  );
}

/** 三档承诺图例：这是整个模块的立身之本，放在最上面一次说清。 */
function PromiseLegend() {
  return (
    <div className="mb-5 rounded-2xl border border-black/[0.06] bg-white/55 px-4 py-3.5 dark:border-white/[0.1] dark:bg-white/[0.05]">
      <div className="grid gap-2.5 sm:grid-cols-3">
        {ASSERTION_ORDER.map((a) => {
          const chip = assertionChip(a, "fact", null, 2, null);
          return (
            <div key={a} className="flex items-start gap-2">
              <span
                className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 t-micro font-semibold ${chip.cls}`}
              >
                {ASSERTION_LABEL[a]}
              </span>
              <span className="t-caption ink-3">{ASSERTION_PROMISE[a]}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SubjectCard({
  subject,
  onToast,
}: {
  subject: LibrarySubject;
  onToast: (text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<InsightItemView[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [contribute, setContribute] = useState(false);
  const gaps = missingContributionTopics(subject);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || items || loading) return;
    setLoading(true);
    setFailed(false);
    try {
      const res = await fetch(`/api/insights/library?subject=${encodeURIComponent(subject.id)}`);
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json?.error || "failed");
      setItems(json.items || []);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  // 互链到岗位库：公司走 company 筛选（jobs.company 大小写不敏感子串），
  // 业务线再叠一个关键词把范围收到这条线上。
  // ⚠️ 诚实边界：岗位库没有「业务线」这个筛选维度（业务线是从标题抽出来的派生概念），
  //    所以业务线卡跳过去的条数**不保证**等于卡面的 job_count；公司卡才是同一口径。
  const jobsHref =
    subject.kind === "business_unit"
      ? `/jobs?company=${encodeURIComponent(subject.company)}&q=${encodeURIComponent(subject.name)}`
      : `/jobs?company=${encodeURIComponent(subject.company)}`;

  return (
    <article className="rounded-2xl border border-black/[0.06] bg-white/60 p-5 dark:border-white/[0.1] dark:bg-white/[0.05]">
      <header className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <span
          className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl border ${
            subject.kind === "company"
              ? "border-tone-sky-border bg-tone-sky-bg text-[#2f6299] dark:text-[#7fb2e8]"
              : "border-[#a9cfd8] bg-[#dcf0f2] text-[#2f7d8a] dark:border-[#6cc0cf]/30 dark:bg-[#6cc0cf]/15 dark:text-[#6cc0cf]"
          }`}
        >
          {subject.kind === "company" ? <Buildings size={17} weight="bold" /> : <TreeStructure size={17} weight="bold" />}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="t-h3">
            {subject.kind === "business_unit" ? (
              <>
                <span className="ink-3">{subject.company}</span>
                <span className="ink-4"> / </span>
                {subject.name}
              </>
            ) : (
              subject.name
            )}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 t-caption ink-3">
            <span>{subject.kind === "company" ? "公司" : "业务线"}</span>
            {subject.industry && <span>{subject.industry}</span>}
            <Link href={jobsHref} className="inline-flex items-center gap-1 text-tone-sky-fg hover:underline">
              在招 {subject.job_count} 个岗位
              <ArrowSquareOut size={12} />
            </Link>
            {subject.last_verified_at && (
              <span className="ink-4">核实于 {formatDateLabel(subject.last_verified_at)}</span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {ASSERTION_ORDER.filter((a) => subject.assertion_counts[a] > 0).map((a) => {
            const chip = assertionChip(a, "fact", null, 2, null);
            return (
              <span key={a} className={`rounded-full px-2 py-0.5 t-micro font-semibold ${chip.cls}`}>
                {ASSERTION_LABEL[a]} {subject.assertion_counts[a]}
              </span>
            );
          })}
        </div>
      </header>

      {(subject.cards || []).length > 0 && (
        <ul className="mt-3.5 grid gap-2">
          {(subject.cards || []).map((m) => (
            <li key={`${m.metric_key}-${m.content.slice(0, 12)}`} className="flex items-start gap-2">
              {/* 官方年报这类事实没有主题键，别渲染成一个空芯片 */}
              {m.metric_key && (
                <span className="mt-[3px] shrink-0 rounded px-1.5 py-0.5 t-micro ink-3 ring-1 ring-inset ring-black/[0.06] dark:ring-white/[0.1]">
                  {METRIC_LABEL[m.metric_key] || m.metric_key}
                  {gradeText(m.metric_key, m.metric_value) && (
                    <span className="ink-1"> · {gradeText(m.metric_key, m.metric_value)}</span>
                  )}
                </span>
              )}
              <span className="t-body-sm ink-2">{metricText(m)}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3.5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          className={buttonVariants({ variant: "soft", size: "xs" })}
        >
          {open ? "收起" : `展开全部 ${subject.item_count} 条`}
        </button>
        {gaps.length > 0 && (
          <button
            type="button"
            onClick={() => setContribute((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-full border border-tone-teal-border bg-tone-teal-bg px-3 py-1.5 t-label text-tone-teal-fg transition hover:bg-[#d2eee1]"
          >
            <ChatCircleText size={14} weight="bold" />
            {contribute ? "收起" : "说一句真实体验"}
          </button>
        )}
      </div>

      {gaps.length > 0 && !contribute && (
        // 互惠墙：空缺处不写「暂无数据」，写成贡献入口（spec §1.5「把第三层的空缺做成飞轮」）。
        <p className="mt-2.5 t-caption ink-3">
          {/* 撤掉数据层后，这句不再是「岗位数据里没有」，而是「这几栏还没有可信内容」 */}
          {gaps.map((g) => g.label).join("/")} 还没有可信内容。
          <span className="ink-2"> 你在{subject.company}待过？说一句真实体验，解锁其他人的说法。</span>
        </p>
      )}

      {contribute && (
        <div className="mt-3">
          <InsightSubmitForm
            company={subject.company}
            onSubmitted={() => {
              setContribute(false);
              onToast("已提交，审核通过后匿名聚合展示");
            }}
          />
        </div>
      )}

      {open && (
        <div className="mt-3.5 border-t border-black/[0.06] pt-3.5 dark:border-white/[0.1]">
          {loading && <p className="t-body-sm ink-3">正在加载…</p>}
          {failed && (
            <p className="t-body-sm text-[#9c4a33] dark:text-[#e8b0a0]">
              没加载出来，
              <button type="button" onClick={toggle} className="underline underline-offset-2">
                点这里重试
              </button>
            </p>
          )}
          {items && items.length === 0 && (
            <p className="t-body-sm ink-3">这个主体目前没有能过校验门的条目。</p>
          )}
          {items && items.length > 0 && (
            <ul className="grid gap-3">
              {items.map((item) => (
                <ItemRow key={item.id} item={item} />
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

function ItemRow({ item }: { item: InsightItemView }) {
  const publishers = new Set((item.sources || []).map((s) => s.url)).size;
  const chip = assertionChip(item.assertion, item.grade, item.sample_size, publishers, item.payload);
  return (
    <li className="rounded-xl border border-black/[0.06] bg-white/55 p-3.5 dark:border-white/[0.1] dark:bg-white/[0.04]">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`rounded-full px-2 py-0.5 t-micro font-semibold ${chip.cls}`}>
          {chip.text}
        </span>
        <span className="t-micro ink-3">
          {DIMENSION_LABEL[item.dimension] || item.dimension}
        </span>
        {item.metric_key && (
          <span className="t-micro ink-4">
            {METRIC_LABEL[item.metric_key] || item.metric_key}
            {gradeText(item.metric_key, item.metric_value ?? null) &&
              `· ${gradeText(item.metric_key, item.metric_value ?? null)}`}
          </span>
        )}
        {item.outdated && <span className="t-micro ink-4">可能已过时</span>}
      </div>
      <p className="mt-2 t-body-sm ink-1">{item.content}</p>
      {(item.sources || []).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {(item.sources || []).slice(0, 4).map((s) => (
            <a
              key={s.id}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 t-micro text-tone-sky-fg hover:underline"
            >
              {s.publisher || new URL(s.url).hostname}
              <ArrowSquareOut size={11} />
            </a>
          ))}
        </div>
      )}
    </li>
  );
}
