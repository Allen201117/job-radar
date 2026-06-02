import Link from "next/link";
import {
  ArrowRight,
  BellRinging,
  Binoculars,
  Briefcase,
  Broadcast,
  ChartLineUp,
  CheckCircle,
  Database,
  Funnel,
  GlobeHemisphereEast,
  Lightning,
  MapPin,
  ShieldCheck,
  Sparkle,
  Stack,
  UserFocus,
} from "@phosphor-icons/react/ssr";

const pipeline = [
  {
    title: "本地 jobs 库",
    text: "先查已经沉淀的真实岗位，不卡在外部搜索。",
    icon: Database,
    tone: "bg-sky-400 text-sky-950",
  },
  {
    title: "已验证官网源",
    text: "刷新 Apple、百度、京东、Siemens 等官方入口。",
    icon: ShieldCheck,
    tone: "bg-lime-300 text-lime-950",
  },
  {
    title: "低频发现新源",
    text: "只在需要时调用 search provider，沉淀候选源。",
    icon: Binoculars,
    tone: "bg-orange-300 text-orange-950",
  },
];

const proofTiles = [
  { icon: Funnel, title: "第三方平台过滤", text: "BOSS、猎聘、智联、转载页先出局。", mark: "🧹" },
  { icon: GlobeHemisphereEast, title: "官网详情页", text: "保留可点击的官方岗位详情链接。", mark: "🌐" },
  { icon: UserFocus, title: "按用户隔离", text: "收藏、忽略、投递只写入当前用户。", mark: "🔐" },
  { icon: BellRinging, title: "失败有原因", text: "rate limit、parser missing、pending 都说清楚。", mark: "📡" },
];

const jobPreview = [
  { company: "Apple", role: "Machine Learning Engineer", city: "上海", score: 82, tags: ["外企", "AI"] },
  { company: "京东", role: "搜索推荐算法工程师", city: "北京", score: 76, tags: ["算法", "官网"] },
  { company: "Siemens", role: "Data Analyst, China", city: "苏州", score: 64, tags: ["数据", "全球官网"] },
];

export default function LandingPage() {
  return (
    <main className="min-h-screen overflow-x-hidden bg-[#0c0d10] text-white">
      <header className="sticky top-0 z-40 border-b border-white/10 bg-[#0c0d10]/82 backdrop-blur-xl">
        <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="inline-flex items-center gap-2 text-sm font-semibold">
            <span className="grid size-7 place-items-center rounded-xl bg-white text-[#0c0d10]">
              <Broadcast size={17} weight="fill" aria-hidden="true" />
            </span>
            Job Radar
          </Link>
          <div className="hidden items-center gap-7 text-sm text-white/64 md:flex">
            <a href="#pipeline" className="transition-colors hover:text-white">
              检索链路
            </a>
            <a href="#signals" className="transition-colors hover:text-white">
              可信信号
            </a>
            <a href="#launch" className="transition-colors hover:text-white">
              产品入口
            </a>
          </div>
          <Link
            href="/today"
            className="inline-flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-semibold text-[#0c0d10] transition duration-200 hover:bg-sky-200 active:scale-[0.98]"
          >
            进入产品
            <ArrowRight size={15} weight="bold" aria-hidden="true" />
          </Link>
        </nav>
      </header>

      <section className="relative mx-auto grid min-h-[calc(100dvh-3.5rem)] max-w-7xl items-center gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_12%,rgba(56,189,248,0.22),transparent_32%),radial-gradient(circle_at_8%_18%,rgba(251,191,36,0.14),transparent_26%),radial-gradient(circle_at_50%_100%,rgba(163,230,53,0.12),transparent_35%)]" />
        <div className="relative">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/8 px-3 py-1.5 text-sm text-white/72 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
            <Sparkle size={16} weight="fill" className="text-lime-300" aria-hidden="true" />
            官方岗位雷达 · 少刷官网
          </div>
          <h1 className="mt-6 max-w-4xl text-balance text-5xl font-semibold leading-[1.04] sm:text-6xl">
            官网岗位，进入你的机会雷达。
          </h1>
          <p className="mt-6 max-w-2xl text-pretty text-lg leading-8 text-white/68">
            过滤第三方聚合页，追踪官方源，按偏好和简历画像排序。每天打开一次，处理真正值得看的岗位。
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/today"
              className="inline-flex items-center gap-2 rounded-full bg-sky-300 px-6 py-3 text-base font-semibold text-sky-950 transition duration-200 hover:bg-sky-200 active:scale-[0.98]"
            >
              🚀 打开今日看板
              <ArrowRight size={18} weight="bold" aria-hidden="true" />
            </Link>
            <Link
              href="/jobs"
              className="inline-flex items-center gap-2 rounded-full border border-white/14 bg-white/8 px-6 py-3 text-base font-semibold text-white transition duration-200 hover:bg-white/14 active:scale-[0.98]"
            >
              浏览岗位库
              <Briefcase size={18} weight="fill" aria-hidden="true" />
            </Link>
          </div>
        </div>

        <div className="relative">
          <div className="rounded-[1.35rem] border border-white/12 bg-white/10 p-3 shadow-[0_28px_90px_rgba(0,0,0,0.42),inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur">
            <div className="rounded-2xl bg-[#f7f8fb] p-4 text-[#15161a]">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-black/6 pb-4">
                <div>
                  <div className="inline-flex items-center gap-2 rounded-full bg-[#15161a] px-3 py-1 text-xs font-semibold text-white">
                    <Broadcast size={14} weight="fill" aria-hidden="true" />
                    Live queue
                  </div>
                  <p className="mt-3 text-3xl font-semibold tabular-nums">24 个官方岗位</p>
                  <p className="mt-1 text-sm text-[#6f7280]">今天优先处理 11 个高匹配岗位</p>
                </div>
                <div className="rounded-2xl bg-sky-100 px-4 py-3 text-center">
                  <p className="text-xs font-medium text-sky-800">匹配峰值</p>
                  <p className="tabular-nums text-3xl font-semibold text-sky-950">82</p>
                </div>
              </div>

              <div className="mt-4 space-y-3">
                {jobPreview.map((job) => (
                  <div key={job.role} className="grid gap-3 rounded-2xl bg-white p-4 shadow-[0_8px_30px_rgba(15,23,42,0.06)] sm:grid-cols-[1fr_auto] sm:items-center">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 text-sm text-[#707481]">
                        <span>{job.company}</span>
                        <span>·</span>
                        <MapPin size={14} weight="fill" aria-hidden="true" />
                        <span>{job.city}</span>
                      </div>
                      <p className="mt-1 truncate text-lg font-semibold">{job.role}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {job.tags.map((tag) => (
                          <span key={tag} className="rounded-full bg-[#eef0f5] px-2.5 py-1 text-xs font-medium text-[#404350]">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-[#15161a] px-4 py-3 text-center text-white">
                      <p className="text-[11px] text-white/62">MATCH</p>
                      <p className="tabular-nums text-2xl font-semibold">{job.score}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="absolute -bottom-5 -left-3 hidden rounded-2xl border border-white/12 bg-lime-300 px-4 py-3 text-sm font-semibold text-lime-950 shadow-[0_20px_50px_rgba(0,0,0,0.28)] md:block">
            ✅ 第三方结果已过滤
          </div>
        </div>
      </section>

      <section id="pipeline" className="relative border-y border-white/10 bg-white/[0.035] py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl">
            <h2 className="text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              检索不是一次搜索，是一条可控链路。
            </h2>
            <p className="mt-5 text-pretty text-lg leading-8 text-white/64">
              Job Radar 像一个小型任务控制台，先利用已有岗位，再按需刷新和发现。
            </p>
          </div>
          <div className="mt-10 grid gap-4 lg:grid-cols-[1.25fr_0.8fr_0.95fr]">
            {pipeline.map((item, index) => (
              <article
                key={item.title}
                className="group rounded-[1.25rem] border border-white/10 bg-white/[0.07] p-5 transition duration-200 hover:-translate-y-1 hover:bg-white/[0.10]"
              >
                <div className={["grid size-12 place-items-center rounded-2xl", item.tone].join(" ")}>
                  <item.icon size={25} weight="fill" aria-hidden="true" />
                </div>
                <p className="mt-8 text-sm font-semibold text-white/45">Step {index + 1}</p>
                <h3 className="mt-2 text-2xl font-semibold">{item.title}</h3>
                <p className="mt-3 text-pretty text-sm leading-6 text-white/62">{item.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="signals" className="mx-auto grid max-w-7xl gap-5 px-4 py-20 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
        <div className="rounded-[1.25rem] bg-sky-300 p-7 text-sky-950">
          <Stack size={34} weight="fill" aria-hidden="true" />
          <h2 className="mt-8 text-balance text-4xl font-semibold leading-tight">
            可信信号直接长在界面里。
          </h2>
          <p className="mt-5 text-pretty text-base leading-7 text-sky-950/72">
            不靠大段说明，把官方源、匹配分、失败原因、候选状态做成一眼能读的视觉信号。
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {proofTiles.map((item) => (
            <article key={item.title} className="rounded-[1.25rem] border border-white/10 bg-white/[0.07] p-5">
              <div className="flex items-center justify-between gap-4">
                <div className="grid size-11 place-items-center rounded-2xl bg-white text-[#15161a]">
                  <item.icon size={24} weight="fill" aria-hidden="true" />
                </div>
                <span className="text-2xl" aria-hidden="true">{item.mark}</span>
              </div>
              <h3 className="mt-7 text-xl font-semibold">{item.title}</h3>
              <p className="mt-2 text-pretty text-sm leading-6 text-white/62">{item.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="launch" className="px-4 pb-20 sm:px-6 lg:px-8">
        <div className="mx-auto grid max-w-7xl gap-6 rounded-[1.5rem] bg-[#f7f8fb] p-6 text-[#15161a] lg:grid-cols-[1fr_auto] lg:items-end lg:p-8">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-[#15161a] px-3 py-1.5 text-sm font-semibold text-white">
              <Lightning size={16} weight="fill" className="text-orange-300" aria-hidden="true" />
              Ready when you are
            </div>
            <h2 className="mt-5 max-w-3xl text-balance text-4xl font-semibold leading-tight sm:text-5xl">
              进入产品主页，处理今天真正该看的岗位。
            </h2>
            <div className="mt-5 flex flex-wrap gap-2 text-sm font-medium text-[#565a66]">
              <span className="rounded-full bg-white px-3 py-2">📍 城市匹配</span>
              <span className="rounded-full bg-white px-3 py-2">🧠 简历画像</span>
              <span className="rounded-full bg-white px-3 py-2">🛡️ 官方源校验</span>
            </div>
          </div>
          <Link
            href="/today"
            className="inline-flex items-center justify-center gap-2 rounded-full bg-[#15161a] px-6 py-3 text-base font-semibold text-white transition duration-200 hover:bg-sky-700 active:scale-[0.98]"
          >
            打开 Job Radar
            <ChartLineUp size={19} weight="fill" aria-hidden="true" />
          </Link>
        </div>
      </section>
    </main>
  );
}
