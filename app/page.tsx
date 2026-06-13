import Link from "next/link";
import { createServerSupabase } from "@/lib/auth";
import {
  ArrowRight,
  BellRinging,
  Binoculars,
  Briefcase,
  Broadcast,
  ChartLineUp,
  CheckCircle,
  Compass,
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

export const dynamic = "force-dynamic";

// —— 卖点①：官方岗位雷达 ——
const pipeline = [
  { title: "本地 jobs 库", text: "先查已经沉淀的真实岗位，不卡在外部搜索。", icon: Database, dot: "bg-[#7fb2e8]" },
  { title: "已验证官网源", text: "刷新 Apple、百度、京东、Siemens 等官方入口。", icon: ShieldCheck, dot: "bg-[#b6da7e]" },
  { title: "低频发现新源", text: "只在需要时调用 search provider，沉淀候选源。", icon: Binoculars, dot: "bg-[#e7b27e]" },
];

const proofTiles = [
  { icon: Funnel, title: "第三方平台过滤", text: "BOSS、猎聘、智联、转载页先出局。" },
  { icon: GlobeHemisphereEast, title: "官网详情页", text: "保留可点击的官方岗位详情链接。" },
  { icon: UserFocus, title: "按用户隔离", text: "收藏、忽略、投递只写入当前用户。" },
  { icon: BellRinging, title: "失败有原因", text: "rate limit、parser missing、pending 都说清楚。" },
];

// —— 卖点②：AI 职业洞察与路径 ——
const insightDims = [
  { icon: Lightning, title: "时机", text: "招聘节奏与放岗周期，什么时候投更有戏。", dot: "bg-[#7fb2e8]" },
  { icon: ChartLineUp, title: "薪酬强度", text: "公开渠道的薪酬与强度对比参考。", dot: "bg-[#b6da7e]" },
  { icon: Compass, title: "路径", text: "典型跳槽与晋升路径，怎么走更顺。", dot: "bg-[#e7b27e]" },
  { icon: UserFocus, title: "文化", text: "团队风格的轻量提示，做浅、重免责。", dot: "bg-[#cfc6b6]" },
];

const insightGuards = [
  { icon: CheckCircle, title: "分级标注", text: "事实 / 观点 / 未核实传闻，前端区分展示。" },
  { icon: BellRinging, title: "时效治理", text: "每条标注信息时间，过时内容降权或过滤。" },
  { icon: ShieldCheck, title: "合规内建", text: "聚合归因、来源去标识、通知-删除入口。" },
];

const audiences = [
  { tag: "校招", icon: UserFocus, text: "应届想盯官方校招岗，再看清行业的放岗节奏。" },
  { tag: "实习", icon: Briefcase, text: "找日常 / 暑期实习，过滤掉中介与水货实习岗。" },
  { tag: "社招", icon: Stack, text: "盯目标公司官方放岗，参考薪酬与跳槽路径。" },
];

const jobPreview = [
  { company: "Apple", role: "Machine Learning Engineer", city: "上海", score: 82, tags: ["外企", "AI"] },
  { company: "京东", role: "搜索推荐算法工程师", city: "北京", score: 76, tags: ["算法", "官网"] },
  { company: "Siemens", role: "Data Analyst, China", city: "苏州", score: 64, tags: ["数据", "全球官网"] },
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
    <main className="bg-editorial grain relative min-h-screen overflow-x-hidden text-[#1a1714]">
      {/* ——— 顶部导航 ——— */}
      <header className="sticky top-0 z-40 border-b border-black/[0.06] bg-[#f4efe6]/80 backdrop-blur-xl">
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 lg:px-8">
          <Link href="/" className="inline-flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-xl bg-[#1a1714] text-[#f7f1e6]">
              <Broadcast size={18} weight="fill" aria-hidden="true" />
            </span>
            <span className="display-tight text-lg font-medium tracking-tight">Job Radar</span>
          </Link>
          <div className="hidden items-center gap-8 text-[14px] text-[#5f594e] md:flex">
            <a href="#radar" className="transition-colors hover:text-[#1a1714]">官方岗位雷达</a>
            <a href="#insight" className="transition-colors hover:text-[#1a1714]">职业洞察</a>
            <a href="#who" className="transition-colors hover:text-[#1a1714]">适用人群</a>
          </div>
          <Link
            href={primaryHref}
            className="inline-flex items-center gap-1.5 rounded-full bg-[#1a1714] px-4 py-2 text-[13px] font-medium text-[#f7f1e6] transition duration-200 hover:bg-[#2b2520] active:scale-95"
          >
            {navCta}
            <ArrowRight size={14} weight="bold" aria-hidden="true" />
          </Link>
        </nav>
      </header>

      {/* ——— Hero：编辑部大标题 + 漂浮的产品碎片 ——— */}
      <section className="relative mx-auto max-w-6xl px-5 pb-20 pt-16 sm:pt-20 lg:px-8 lg:pb-28 lg:pt-24">
        {/* 漂浮产品「拍立得」——绝对定位在标题四角，移动端隐藏 */}
        <figure className="float-soft absolute left-0 top-10 z-10 hidden xl:block" style={{ animationDelay: "0s" }}>
          <div className="polaroid w-[196px] -rotate-[6deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
            <div className="rounded-[0.8rem] bg-[#f6f3ec] p-4">
              <p className="text-[11px] font-medium text-[#8a8275]">今日官方岗位</p>
              <p className="mt-1 text-[2rem] font-semibold leading-none tabular-nums text-[#1a1714]">24</p>
              <p className="mt-1.5 text-[12px] text-[#8a8275]">11 个高匹配待处理</p>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-black/[0.06]">
                <div className="h-full w-[46%] rounded-full bg-[#7fb2e8]" />
              </div>
            </div>
          </div>
          <figcaption className="mt-2 pl-1 text-[12px] text-[#9a9184]">今日看板</figcaption>
        </figure>

        <figure className="float-soft absolute right-0 top-4 z-10 hidden xl:block" style={{ animationDelay: "1.3s" }}>
          <div className="polaroid w-[238px] rotate-[5deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
            <div className="rounded-[0.8rem] bg-white p-4">
              <div className="flex items-center gap-1.5 text-[12px] text-[#8a8275]">
                <span className="font-medium text-[#1a1714]">Apple</span>
                <span>·</span>
                <MapPin size={12} weight="fill" aria-hidden="true" />
                <span>上海</span>
              </div>
              <p className="mt-1.5 text-[15px] font-semibold leading-snug text-[#1a1714]">
                Machine Learning Engineer
              </p>
              <div className="mt-3 flex items-center justify-between">
                <div className="flex gap-1.5">
                  <span className="rounded-full bg-[#eef0f5] px-2 py-0.5 text-[11px] font-medium text-[#4a4d57]">外企</span>
                  <span className="rounded-full bg-[#eef0f5] px-2 py-0.5 text-[11px] font-medium text-[#4a4d57]">AI</span>
                </div>
                <div className="rounded-xl bg-[#1a1714] px-2.5 py-1 text-white">
                  <span className="text-[15px] font-semibold tabular-nums">82</span>
                </div>
              </div>
            </div>
          </div>
          <figcaption className="mt-2 pr-1 text-right text-[12px] text-[#9a9184]">官方岗位卡</figcaption>
        </figure>

        <figure className="float-soft absolute bottom-8 left-2 z-10 hidden xl:block" style={{ animationDelay: "0.7s" }}>
          <div className="polaroid w-[214px] rotate-[3deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
            <div className="rounded-[0.8rem] bg-white p-4">
              <p className="text-[11px] font-medium text-[#8a8275]">职业洞察 · 分级标时间</p>
              <ul className="mt-2.5 grid grid-cols-2 gap-2 text-[12px] text-[#3f3a33]">
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#7fb2e8]" />时机</li>
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#b6da7e]" />薪酬强度</li>
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#e7b27e]" />路径</li>
                <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#cfc6b6]" />文化</li>
              </ul>
            </div>
          </div>
          <figcaption className="mt-2 pl-1 text-[12px] text-[#9a9184]">职业洞察</figcaption>
        </figure>

        <figure className="float-soft absolute bottom-12 right-4 z-10 hidden xl:block" style={{ animationDelay: "2s" }}>
          <div className="polaroid w-[200px] -rotate-[4deg] transition-transform duration-300 ease-out hover:-translate-y-1.5 hover:rotate-0">
            <div className="flex items-center gap-2.5 rounded-[0.8rem] bg-[#1a1714] p-4 text-[#f7f1e6]">
              <CheckCircle size={26} weight="fill" className="shrink-0 text-[#b6da7e]" aria-hidden="true" />
              <p className="text-[13px] font-medium leading-snug">第三方结果<br />已过滤</p>
            </div>
          </div>
          <figcaption className="mt-2 pr-1 text-right text-[12px] text-[#9a9184]">质量门</figcaption>
        </figure>

        {/* 居中文案 */}
        <div className="relative z-20 mx-auto max-w-3xl text-center">
          <p className="rise inline-flex items-center gap-2 rounded-full border border-black/[0.08] bg-white/60 px-3.5 py-1.5 text-[13px] font-medium text-[#5f594e]">
            <Sparkle size={15} weight="fill" className="text-[#e7a24e]" aria-hidden="true" />
            官方岗位雷达 · AI 职业洞察
          </p>
          <h1 className="display-tight rise mt-7 text-balance text-[2.9rem] font-medium leading-[1.1] text-[#1a1714] sm:text-[3.6rem] lg:text-[4.1rem]">
            只看{" "}
            <span className="relative -top-1 mx-1 inline-flex items-center gap-1.5 rounded-full bg-[#1a1714] px-4 py-1.5 align-middle text-[0.42em] font-medium text-[#f7f1e6]">
              <Broadcast size={16} weight="fill" className="text-[#7fb2e8]" aria-hidden="true" />
              官方源
            </span>{" "}
            在招的岗位，
            <br />
            加上能信的求职决策信号。
          </h1>
          <p className="rise mx-auto mt-7 max-w-xl text-pretty text-[16px] leading-7 text-[#5f594e]">
            求职雷达聚合企业官方招聘源、过滤第三方水货岗位；再把公开的招聘节奏、薪酬与跳槽路径，聚合成分级、标时间的职业洞察。每天打开一次，只看真正值得看的。
          </p>
          <div className="rise mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link href={primaryHref} className="btn-ink text-base">
              {primaryLabel}
              <ArrowRight size={18} weight="bold" aria-hidden="true" />
            </Link>
            <a href="#radar" className="btn-ghost text-base">了解功能</a>
          </div>
        </div>
      </section>

      {/* ——— 卖点①：官方岗位雷达 ——— */}
      <section id="radar" className="relative mx-auto max-w-6xl px-5 py-20 lg:px-8">
        <div className="max-w-2xl">
          <span className="text-[13px] font-semibold tracking-[0.14em] text-[#a08a5e]">卖点 ①</span>
          <h2 className="display-tight mt-3 text-balance text-[2.2rem] font-medium leading-[1.12] text-[#1a1714] sm:text-[2.8rem]">
            检索不是一次搜索，
            <br className="hidden sm:block" />
            是一条可控链路。
          </h2>
          <p className="mt-5 text-pretty text-[16px] leading-7 text-[#5f594e]">
            只收企业官方渠道的岗位，第三方转载与聚合页直接出局。Job Radar 像一个小型任务控制台，先利用已有岗位，再按需刷新和发现。
          </p>
        </div>

        <div className="mt-12 grid gap-4 lg:grid-cols-3">
          {pipeline.map((item, index) => (
            <article
              key={item.title}
              className="group rounded-[1.4rem] border border-black/[0.06] bg-white/70 p-6 shadow-[0_18px_44px_-26px_rgba(40,34,28,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-white"
            >
              <div className="flex items-center justify-between">
                <span className="grid size-11 place-items-center rounded-2xl bg-[#f4efe6] text-[#1a1714]">
                  <item.icon size={22} weight="fill" aria-hidden="true" />
                </span>
                <span className={["size-2.5 rounded-full", item.dot].join(" ")} aria-hidden="true" />
              </div>
              <p className="mt-7 text-[12px] font-semibold tracking-wide text-[#a39a8c]">STEP {index + 1}</p>
              <h3 className="display-tight mt-1.5 text-[1.5rem] font-medium text-[#1a1714]">{item.title}</h3>
              <p className="mt-2.5 text-pretty text-[14px] leading-6 text-[#5f594e]">{item.text}</p>
            </article>
          ))}
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {proofTiles.map((item) => (
            <article key={item.title} className="rounded-[1.4rem] border border-black/[0.06] bg-white/55 p-5">
              <span className="grid size-10 place-items-center rounded-2xl bg-[#1a1714] text-[#f7f1e6]">
                <item.icon size={20} weight="fill" aria-hidden="true" />
              </span>
              <h3 className="mt-5 text-[16px] font-semibold text-[#1a1714]">{item.title}</h3>
              <p className="mt-1.5 text-pretty text-[13px] leading-6 text-[#6b655a]">{item.text}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ——— 卖点②：AI 职业洞察（近黑编辑带，制造明暗节奏）——— */}
      <section id="insight" className="mx-auto max-w-6xl px-5 py-12 lg:px-8">
        <div className="overflow-hidden rounded-[2rem] bg-[#1a1714] px-6 py-12 text-[#f7f1e6] sm:px-10 lg:px-14 lg:py-16">
          <div className="max-w-2xl">
            <span className="text-[13px] font-semibold tracking-[0.14em] text-[#cdbf9b]">卖点 ②</span>
            <h2 className="display-tight mt-3 text-balance text-[2.2rem] font-medium leading-[1.12] text-[#f7f1e6] sm:text-[2.8rem]">
              把分散的公开信息差，
              <br className="hidden sm:block" />
              聚合成能信的洞察。
            </h2>
            <p className="mt-5 text-pretty text-[16px] leading-7 text-[#cfc6b6]">
              招聘节奏、薪酬对比、跳槽路径——不做单点指名的断言，只做聚合归因、分级标注、标注时间。
            </p>
          </div>

          <div className="mt-11 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {insightDims.map((item) => (
              <article
                key={item.title}
                className="rounded-[1.3rem] border border-white/10 bg-white/[0.05] p-5 transition duration-200 hover:-translate-y-1 hover:bg-white/[0.08]"
              >
                <div className="flex items-center justify-between">
                  <span className="grid size-10 place-items-center rounded-2xl bg-white/10 text-[#f7f1e6]">
                    <item.icon size={20} weight="fill" aria-hidden="true" />
                  </span>
                  <span className={["size-2.5 rounded-full", item.dot].join(" ")} aria-hidden="true" />
                </div>
                <h3 className="display-tight mt-5 text-[1.35rem] font-medium text-[#f7f1e6]">{item.title}</h3>
                <p className="mt-2 text-pretty text-[13px] leading-6 text-[#b3aa9b]">{item.text}</p>
              </article>
            ))}
          </div>

          <ul className="mt-8 grid gap-x-8 gap-y-3 border-t border-white/10 pt-8 sm:grid-cols-3">
            {insightGuards.map((g) => (
              <li key={g.title} className="flex items-start gap-2.5">
                <g.icon size={19} weight="fill" className="mt-0.5 shrink-0 text-[#b6da7e]" aria-hidden="true" />
                <span className="text-[13px] leading-6 text-[#cfc6b6]">
                  <span className="font-semibold text-[#f7f1e6]">{g.title}</span>：{g.text}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ——— 适用人群 ——— */}
      <section id="who" className="mx-auto max-w-6xl px-5 py-20 lg:px-8">
        <div className="max-w-2xl">
          <h2 className="display-tight text-balance text-[2.2rem] font-medium leading-[1.12] text-[#1a1714] sm:text-[2.8rem]">
            校招、实习、社招，
            <br className="hidden sm:block" />
            都覆盖。
          </h2>
          <p className="mt-5 text-pretty text-[16px] leading-7 text-[#5f594e]">
            不管你在求职的哪个阶段，雷达只给你官方、最新、匹配的信号。
          </p>
        </div>

        <div className="mt-12 grid gap-4 sm:grid-cols-3">
          {audiences.map((a) => (
            <article
              key={a.tag}
              className="rounded-[1.4rem] border border-black/[0.06] bg-white/70 p-7 shadow-[0_18px_44px_-26px_rgba(40,34,28,0.32)] transition duration-200 hover:-translate-y-1 hover:bg-white"
            >
              <div className="flex items-center gap-3">
                <span className="grid size-11 place-items-center rounded-2xl bg-[#f4efe6] text-[#1a1714]">
                  <a.icon size={22} weight="fill" aria-hidden="true" />
                </span>
                <span className="display-tight text-[1.4rem] font-medium text-[#1a1714]">{a.tag}</span>
              </div>
              <p className="mt-5 text-pretty text-[14px] leading-6 text-[#5f594e]">{a.text}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ——— 底部 CTA ——— */}
      <section className="mx-auto max-w-6xl px-5 pb-24 lg:px-8">
        <div className="relative overflow-hidden rounded-[2rem] border border-black/[0.06] bg-white/70 px-6 py-12 text-center shadow-[0_30px_70px_-34px_rgba(40,34,28,0.4)] sm:px-10 lg:py-16">
          <div className="grain absolute inset-0" aria-hidden="true" />
          <div className="relative">
            <p className="inline-flex items-center gap-2 rounded-full bg-[#1a1714] px-3.5 py-1.5 text-[13px] font-medium text-[#f7f1e6]">
              <Lightning size={15} weight="fill" className="text-[#e7a24e]" aria-hidden="true" />
              今天就开始
            </p>
            <h2 className="display-tight mx-auto mt-6 max-w-2xl text-balance text-[2.1rem] font-medium leading-[1.14] text-[#1a1714] sm:text-[2.7rem]">
              官方源岗位 + 分级职业洞察，
              <br className="hidden sm:block" />
              几分钟跑通第一次扫描。
            </h2>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-2 text-[13px] font-medium text-[#6b655a]">
              <span className="rounded-full border border-black/[0.07] bg-white px-3.5 py-1.5">城市匹配</span>
              <span className="rounded-full border border-black/[0.07] bg-white px-3.5 py-1.5">简历画像</span>
              <span className="rounded-full border border-black/[0.07] bg-white px-3.5 py-1.5">官方源校验</span>
            </div>
            <div className="mt-9 flex justify-center">
              <Link href={primaryHref} className="btn-ink text-base">
                {primaryLabel}
                <ChartLineUp size={18} weight="fill" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ——— 页脚 ——— */}
      <footer className="border-t border-black/[0.06]">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-10 sm:flex-row sm:items-center sm:justify-between lg:px-8">
          <Link href="/" className="inline-flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-lg bg-[#1a1714] text-[#f7f1e6]">
              <Broadcast size={14} weight="fill" aria-hidden="true" />
            </span>
            <span className="display-tight text-[15px] font-medium">Job Radar</span>
          </Link>
          <p className="max-w-xl text-[12px] leading-5 text-[#9a9184]">
            职业洞察以聚合形式呈现、来源去标识，支持通知-删除；岗位仅来自企业官方公开渠道。Private Beta。
          </p>
        </div>
      </footer>
    </main>
  );
}
