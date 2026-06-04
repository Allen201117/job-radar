import Link from "next/link";
import { createServerSupabase } from "@/lib/auth";
import {
  ArrowRight,
  BellRinging,
  Briefcase,
  Broadcast,
  ChartLineUp,
  CheckCircle,
  Compass,
  Funnel,
  GlobeHemisphereEast,
  Lightning,
  MapPin,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
  Stack,
  UserFocus,
} from "@phosphor-icons/react/ssr";

export const dynamic = "force-dynamic";

const radarPoints = [
  "官方源优先：Apple、百度、京东、Siemens 等官网入口持续刷新",
  "水货过滤：第三方转载页、聚合页、招聘首页一律不进库",
  "质量门：company / title / jd_url 非空，且是可点击的官方详情链接",
  "个性化排序：按你的偏好规则与简历画像给每个岗位打分",
];

const insightPoints = [
  { icon: Lightning, text: "时机：招聘节奏与放岗周期，什么时候投更有戏" },
  { icon: ChartLineUp, text: "薪酬强度：公开渠道的薪酬与强度对比参考" },
  { icon: Compass, text: "路径：典型跳槽与晋升路径，怎么走更顺" },
  { icon: UserFocus, text: "文化：团队风格的轻量提示，做浅、重免责" },
];

const insightGuards = [
  { icon: CheckCircle, text: "分级标注：事实 / 观点 / 未核实传闻，前端区分展示" },
  { icon: BellRinging, text: "时效治理：每条标注信息时间，过时内容降权或过滤" },
  { icon: ShieldCheck, text: "合规内建：聚合归因、来源去标识、通知-删除入口" },
];

const audiences = [
  { tag: "校招", icon: UserFocus, text: "应届想盯官方校招岗，再看清行业的放岗节奏" },
  { tag: "实习", icon: Briefcase, text: "找日常 / 暑期实习，过滤掉中介与水货实习岗" },
  { tag: "社招", icon: Stack, text: "盯目标公司官方放岗，参考薪酬与跳槽路径" },
];

const jobPreview = [
  { company: "Apple", city: "上海", role: "Machine Learning Engineer", score: 82 },
  { company: "京东", city: "北京", role: "搜索推荐算法工程师", score: 76 },
  { company: "Siemens", city: "苏州", role: "Data Analyst, China", score: 64 },
];

export default async function LandingPage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const primaryHref = user ? "/today" : "/login";
  const primaryLabel = user ? "进入今日看板" : "登录 / 注册";
  const navCta = user ? "进入产品" : "登录 / 注册";

  return (
    <main className="min-h-[100dvh] overflow-x-clip bg-background text-foreground">
      {/* ——— 顶栏 ——— */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-xl">
        <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="inline-flex items-center gap-2 font-mono text-sm font-semibold tracking-tight">
            <span className="grid size-7 place-items-center rounded-md border border-border bg-surface text-signal">
              <Broadcast size={16} weight="fill" aria-hidden="true" />
            </span>
            Job Radar
          </Link>
          <div className="hidden items-center gap-7 text-sm text-muted-foreground md:flex">
            <a href="#radar" className="transition-colors hover:text-foreground">岗位雷达</a>
            <a href="#insight" className="transition-colors hover:text-foreground">职业洞察</a>
            <a href="#who" className="transition-colors hover:text-foreground">适用人群</a>
          </div>
          <Link
            href={primaryHref}
            className="inline-flex items-center gap-2 rounded-lg bg-signal px-4 py-2 text-sm font-semibold text-signal-foreground transition duration-200 hover:brightness-110 active:scale-[0.98]"
          >
            {navCta}
            <ArrowRight size={15} weight="bold" aria-hidden="true" />
          </Link>
        </nav>
      </header>

      {/* ——— Hero ——— */}
      <section className="relative border-b border-border">
        <div className="pointer-events-none absolute inset-0 bg-grid opacity-60" />
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: "radial-gradient(60% 50% at 78% 8%, hsl(var(--signal) / 0.10), transparent)" }}
        />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:py-24 lg:px-8">
          <div>
            <span className="animate-rise inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-sm text-muted-foreground">
              <Sparkle size={15} weight="fill" className="text-signal" aria-hidden="true" />
              官方岗位雷达 · AI 职业洞察
            </span>
            <h1 className="animate-rise mt-6 text-balance text-4xl font-semibold leading-[1.08] sm:text-5xl lg:text-6xl" style={{ animationDelay: "60ms" }}>
              只追官方源的岗位，
              <br />
              和能信的职业内幕。
            </h1>
            <p className="animate-rise mt-6 max-w-xl text-pretty text-lg leading-8 text-muted-foreground" style={{ animationDelay: "120ms" }}>
              求职雷达聚合企业官方招聘源、过滤第三方水货岗位；再把公开的招聘节奏、薪酬与跳槽路径，聚合成分级、标时间的职业洞察。每天打开一次，只看真正值得看的。
            </p>
            <div className="animate-rise mt-9 flex flex-wrap items-center gap-3" style={{ animationDelay: "180ms" }}>
              <Link
                href={primaryHref}
                className="inline-flex items-center gap-2 rounded-lg bg-signal px-6 py-3 text-base font-semibold text-signal-foreground transition duration-200 hover:brightness-110 active:scale-[0.98]"
              >
                {primaryLabel}
                <ArrowRight size={18} weight="bold" aria-hidden="true" />
              </Link>
              <a
                href="#radar"
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-6 py-3 text-base font-medium text-foreground/85 transition duration-200 hover:border-foreground/25 hover:bg-surface-2 active:scale-[0.98]"
              >
                了解功能
              </a>
            </div>
          </div>

          {/* Hero 视觉：信号读数面板 + 雷达扫描（差异化记忆点） */}
          <div className="animate-rise relative" style={{ animationDelay: "160ms" }}>
            <div className="rounded-xl border border-border bg-surface p-5 shadow-[0_1px_0_0_hsl(var(--foreground)/0.05)_inset]">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">今日官方岗位</p>
                  <p className="mt-1 font-mono text-4xl font-semibold tabular-nums">24</p>
                </div>
                {/* 雷达扫描 */}
                <div className="relative size-24 shrink-0">
                  <div className="absolute inset-0 rounded-full border border-border" />
                  <div className="absolute inset-[18%] rounded-full border border-border/70" />
                  <div className="absolute inset-[38%] rounded-full border border-border/50" />
                  <div
                    className="absolute inset-0 animate-sweep rounded-full"
                    style={{ background: "conic-gradient(from 0deg, transparent 0deg, hsl(var(--signal) / 0.35) 44deg, transparent 70deg)" }}
                    aria-hidden="true"
                  />
                  <span className="absolute left-1/2 top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-signal" />
                  <span className="absolute left-[68%] top-[34%] size-1 rounded-full bg-signal/80" />
                  <span className="absolute left-[30%] top-[60%] size-1 rounded-full bg-signal/60" />
                </div>
              </div>

              <div className="mt-5 space-y-2.5">
                {jobPreview.map((job) => (
                  <div
                    key={job.role}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-3.5 py-3"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span>{job.company}</span>
                        <span aria-hidden="true">·</span>
                        <MapPin size={12} weight="fill" aria-hidden="true" />
                        <span>{job.city}</span>
                      </div>
                      <p className="mt-0.5 truncate text-sm font-medium">{job.role}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">match</p>
                      <p className="font-mono text-lg font-semibold tabular-nums text-signal">{job.score}</p>
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <CheckCircle size={13} weight="fill" className="text-signal" aria-hidden="true" />
                第三方聚合结果已在入库前过滤
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ——— 卖点① 官方岗位雷达 ——— */}
      <section id="radar" className="border-b border-border">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:py-24 lg:px-8">
          <div>
            <span className="font-mono text-xs uppercase tracking-widest text-signal">卖点 01</span>
            <h2 className="mt-3 text-balance text-3xl font-semibold leading-tight sm:text-4xl">官方岗位雷达</h2>
            <p className="mt-4 text-pretty text-base leading-7 text-muted-foreground">
              只收企业官方渠道的岗位。第三方平台充斥重复、过期、钓鱼岗位；官方源意味着真实、最新、可追溯。
            </p>
            <span className="mt-6 inline-flex size-12 place-items-center justify-center rounded-lg border border-border bg-surface text-signal">
              <ShieldCheck size={26} weight="fill" aria-hidden="true" />
            </span>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {[
              { icon: ShieldCheck, text: radarPoints[0] },
              { icon: Funnel, text: radarPoints[1] },
              { icon: GlobeHemisphereEast, text: radarPoints[2] },
              { icon: SlidersHorizontal, text: radarPoints[3] },
            ].map((p) => (
              <li
                key={p.text}
                className="group rounded-xl border border-border bg-surface p-5 transition duration-200 hover:-translate-y-0.5 hover:border-foreground/20"
              >
                <span className="grid size-10 place-items-center rounded-lg border border-border bg-background text-signal">
                  <p.icon size={20} weight="fill" aria-hidden="true" />
                </span>
                <p className="mt-4 text-sm leading-6 text-foreground/85">{p.text}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ——— 卖点② AI 职业洞察 ——— */}
      <section id="insight" className="border-b border-border">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1.2fr_0.8fr] lg:py-24 lg:px-8">
          <div className="order-2 lg:order-1 grid gap-3 sm:grid-cols-2">
            {insightPoints.map((p) => (
              <div
                key={p.text}
                className="group rounded-xl border border-border bg-surface p-5 transition duration-200 hover:-translate-y-0.5 hover:border-foreground/20"
              >
                <span className="grid size-10 place-items-center rounded-lg border border-border bg-background text-signal">
                  <p.icon size={20} weight="fill" aria-hidden="true" />
                </span>
                <p className="mt-4 text-sm leading-6 text-foreground/85">{p.text}</p>
              </div>
            ))}
          </div>
          <div className="order-1 lg:order-2">
            <span className="font-mono text-xs uppercase tracking-widest text-signal">卖点 02</span>
            <h2 className="mt-3 text-balance text-3xl font-semibold leading-tight sm:text-4xl">AI 职业洞察与路径</h2>
            <p className="mt-4 text-pretty text-base leading-7 text-muted-foreground">
              把分散在公开渠道的招聘节奏、薪酬对比、跳槽路径，聚合成可信的分级洞察——不做单点指名的断言，只做聚合归因。
            </p>
            <ul className="mt-6 space-y-2.5">
              {insightGuards.map((g) => (
                <li key={g.text} className="flex items-start gap-2.5 text-sm leading-6 text-foreground/80">
                  <g.icon size={17} weight="fill" className="mt-0.5 shrink-0 text-signal" aria-hidden="true" />
                  {g.text}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ——— 适用人群 ——— */}
      <section id="who" className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24 lg:px-8">
          <h2 className="text-balance text-3xl font-semibold leading-tight sm:text-4xl">校招、实习、社招都覆盖</h2>
          <p className="mt-4 max-w-2xl text-pretty text-base leading-7 text-muted-foreground">
            不管你在求职的哪个阶段，雷达只给你官方、最新、匹配的信号。
          </p>
          <div className="mt-9 grid gap-3 sm:grid-cols-3">
            {audiences.map((a) => (
              <div key={a.tag} className="rounded-xl border border-border bg-surface p-6">
                <div className="flex items-center gap-2.5">
                  <span className="grid size-9 place-items-center rounded-lg border border-border bg-background text-signal">
                    <a.icon size={18} weight="fill" aria-hidden="true" />
                  </span>
                  <span className="font-mono text-sm font-semibold tracking-tight">{a.tag}</span>
                </div>
                <p className="mt-4 text-sm leading-6 text-muted-foreground">{a.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ——— 底部 CTA ——— */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 lg:px-8">
          <div className="relative overflow-hidden rounded-2xl border border-border bg-surface px-6 py-12 text-center sm:px-10">
            <div
              className="pointer-events-none absolute inset-0"
              style={{ background: "radial-gradient(50% 80% at 50% 0%, hsl(var(--signal) / 0.12), transparent)" }}
            />
            <div className="relative">
              <Lightning size={28} weight="fill" className="mx-auto text-signal" aria-hidden="true" />
              <h2 className="mt-5 text-balance text-3xl font-semibold leading-tight sm:text-4xl">
                今天就把求职雷达打开。
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-pretty text-base leading-7 text-muted-foreground">
                官方源的真实岗位 + 分级标时间的职业洞察，几分钟跑通你的第一次扫描。
              </p>
              <Link
                href={primaryHref}
                className="mt-8 inline-flex items-center gap-2 rounded-lg bg-signal px-6 py-3 text-base font-semibold text-signal-foreground transition duration-200 hover:brightness-110 active:scale-[0.98]"
              >
                {primaryLabel}
                <ArrowRight size={18} weight="bold" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ——— 页脚 ——— */}
      <footer className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <Link href="/" className="inline-flex items-center gap-2 font-mono text-sm font-semibold tracking-tight">
            <span className="grid size-6 place-items-center rounded-md border border-border bg-surface text-signal">
              <Broadcast size={13} weight="fill" aria-hidden="true" />
            </span>
            Job Radar
          </Link>
          <p className="max-w-xl text-xs leading-5 text-muted-foreground">
            职业洞察以聚合形式呈现、来源去标识，支持通知-删除；岗位仅来自企业官方公开渠道。Private Beta。
          </p>
        </div>
      </footer>
    </main>
  );
}
