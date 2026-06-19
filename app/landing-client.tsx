"use client";

import Link from "next/link";
import { useEffect } from "react";
import type { CSSProperties } from "react";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";
import {
  ArrowRight,
  Briefcase,
  ChartLineUp,
  CheckCircle,
  Clock,
  Compass,
  GraduationCap,
  House,
  Lightning,
  MagnifyingGlass,
  ShieldCheck,
  Stack,
  UsersThree,
  X,
} from "@phosphor-icons/react";

const COMPANIES = [
  "Apple", "字节跳动", "腾讯", "京东", "百度", "美团", "微软",
  "亚马逊", "谷歌", "Siemens", "荣耀", "货拉拉", "微众银行", "海尔",
];

const PILLARS = [
  { icon: House, dot: "#7fb2e8", title: "官网直发", text: "岗位只来自企业官方招聘页，不是招聘平台的转载，也不是中介代发。来源干净，信息才可信。" },
  { icon: ShieldCheck, dot: "#b6da7e", title: "都还在招", text: "撤下的岗位会自动下架。你点开的每个链接，都是仍然有效的官方详情页，不再扑空。" },
  { icon: MagnifyingGlass, dot: "#e7b27e", title: "按你来排", text: "按你的城市、岗位方向和简历自动匹配，越合适的越靠前。不配的方向，连看都不用看。" },
  { icon: ChartLineUp, dot: "#cfc6b6", title: "能信的洞察", text: "招聘节奏、薪酬区间、跳槽路径、团队风格——分级、标好时间，帮你判断这一票值不值得投。" },
];

const INSIGHT_DIMS = [
  { icon: Lightning, dot: "#7fb2e8", title: "时机", text: "什么时候放岗、什么时候投更有戏，看准节奏再出手。" },
  { icon: ChartLineUp, dot: "#b6da7e", title: "薪酬", text: "公开渠道的薪酬区间与强度参考，心里先有个数。" },
  { icon: Compass, dot: "#e7b27e", title: "路径", text: "典型的跳槽与晋升路径，这一步怎么走更顺。" },
  { icon: UsersThree, dot: "#cfc6b6", title: "文化", text: "团队风格的轻量提示，做浅、重免责，仅供参考。" },
];

const GUARDS = [
  { icon: CheckCircle, b: "分级标注。", t: "事实 / 观点 / 未核实传闻，前端清楚区分。" },
  { icon: Clock, b: "标好时间。", t: "每条都带时间，过时内容自动降权或过滤。" },
  { icon: ShieldCheck, b: "来源可溯。", t: "聚合归因、来源去标识，支持通知后删除。" },
];

const AUDIENCES = [
  { icon: GraduationCap, tag: "校招", text: "应届想盯官方校招岗，再看清目标行业的放岗节奏，别错过窗口期。" },
  { icon: Briefcase, tag: "实习", text: "找日常 / 暑期实习，过滤掉中介和水货实习岗，只投企业官方在招的。" },
  { icon: Stack, tag: "社招", text: "盯目标公司的官方放岗，参考薪酬与跳槽路径，把每一次投递都用在刀刃上。" },
];

const cardBase =
  "rounded-[18px] border border-black/[0.05] bg-white text-[#1a1714] shadow-[0_1px_1px_rgba(40,34,28,0.05),0_22px_48px_-20px_rgba(40,34,28,0.32)] transition-shadow duration-300 hover:shadow-[0_30px_60px_-24px_rgba(40,34,28,0.45)] dark:border-white/[0.06] dark:bg-[#1e1a15] dark:text-[#f3ecdf] dark:shadow-[0_22px_48px_-20px_rgba(0,0,0,0.6)]";

export default function LandingClient({ loggedIn }: { loggedIn: boolean }) {
  const primaryHref = loggedIn ? "/today" : "/login";
  const primaryLabel = loggedIn ? "进入今日看板" : "登录 / 注册";

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // 滚动揭示 + 数字滚动
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (!en.isIntersecting) return;
          en.target.classList.add("in");
          en.target.querySelectorAll<HTMLElement>("[data-count]").forEach((n) => countUp(n, reduce));
          io.unobserve(en.target);
        });
      },
      { threshold: 0.15 },
    );
    document.querySelectorAll(".lp-reveal").forEach((el) => io.observe(el));

    // hero 里的数字立即触发（不在 reveal 容器内）
    const heroNums = document.querySelectorAll<HTMLElement>(".lp-hero [data-count]");
    const t = window.setTimeout(() => heroNums.forEach((n) => countUp(n, reduce)), 450);

    function countUp(el: HTMLElement, skip: boolean) {
      if (el.dataset.done) return;
      el.dataset.done = "1";
      const target = Number(el.dataset.count || "0");
      if (skip) { el.textContent = String(target); return; }
      const dur = 1300;
      let start: number | null = null;
      const step = (ts: number) => {
        if (start === null) start = ts;
        const p = Math.min((ts - start) / dur, 1);
        el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }

    if (reduce) return () => { io.disconnect(); window.clearTimeout(t); };

    // hero 鼠标视差
    const hero = document.querySelector<HTMLElement>(".lp-hero");
    const onHeroMove = (e: PointerEvent) => {
      if (!hero) return;
      const r = hero.getBoundingClientRect();
      hero.style.setProperty("--mx", String((e.clientX - r.left) / r.width - 0.5));
      hero.style.setProperty("--my", String((e.clientY - r.top) / r.height - 0.5));
    };
    const onHeroLeave = () => {
      hero?.style.setProperty("--mx", "0");
      hero?.style.setProperty("--my", "0");
    };
    hero?.addEventListener("pointermove", onHeroMove, { passive: true });
    hero?.addEventListener("pointerleave", onHeroLeave);

    // 卡片 3D 倾斜
    const tilts = Array.from(document.querySelectorAll<HTMLElement>(".lp-tilt"));
    const onTilt = (card: HTMLElement) => (e: PointerEvent) => {
      const r = card.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      card.style.setProperty("--rx", `${-py * 7}deg`);
      card.style.setProperty("--ry", `${px * 7}deg`);
    };
    const onTiltLeave = (card: HTMLElement) => () => {
      card.style.setProperty("--rx", "0deg");
      card.style.setProperty("--ry", "0deg");
    };
    const tiltHandlers = tilts.map((card) => {
      const move = onTilt(card);
      const leave = onTiltLeave(card);
      card.addEventListener("pointermove", move);
      card.addEventListener("pointerleave", leave);
      return { card, move, leave };
    });

    return () => {
      io.disconnect();
      window.clearTimeout(t);
      hero?.removeEventListener("pointermove", onHeroMove);
      hero?.removeEventListener("pointerleave", onHeroLeave);
      tiltHandlers.forEach(({ card, move, leave }) => {
        card.removeEventListener("pointermove", move);
        card.removeEventListener("pointerleave", leave);
      });
    };
  }, []);

  return (
    <main className="bg-editorial grain relative min-h-screen overflow-x-hidden text-[#1a1714] dark:text-[#f3ecdf]">
      {/* ——— 导航 ——— */}
      <header className="sticky top-3 z-50 px-4">
        <nav className="mx-auto flex max-w-6xl items-center justify-between rounded-full border border-black/[0.07] bg-[#f4efe6]/70 px-3 py-2.5 pl-4 backdrop-blur-xl dark:border-white/[0.08] dark:bg-[#16130f]/72">
          <Link href="/" className="transition-opacity hover:opacity-70">
            <BrandMark tile={32} icon={20} wordSize={17} />
          </Link>
          <div className="hidden items-center gap-7 text-[14px] text-[#5f594e] md:flex dark:text-[#b6ad9d]">
            <a href="#why" className="transition-colors hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">为什么选它</a>
            <a href="#vs" className="transition-colors hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">和平台的区别</a>
            <a href="#insight" className="transition-colors hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">职业洞察</a>
            <a href="#who" className="transition-colors hover:text-[#1a1714] dark:hover:text-[#f3ecdf]">适用人群</a>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link href={primaryHref} className="btn-ink-sm cursor-target">
              {primaryLabel}
              <ArrowRight size={14} weight="bold" aria-hidden="true" />
            </Link>
          </div>
        </nav>
      </header>

      {/* ——— HERO ——— */}
      <section className="lp-hero relative mx-auto max-w-6xl px-6 pb-12 pt-[4.5rem] text-center">
        <div className="pointer-events-none absolute left-1/2 top-[46%] z-0 -translate-x-1/2 -translate-y-1/2" aria-hidden="true">
          <span className="lp-ring" style={{ animationDelay: "0s" }} />
          <span className="lp-ring" style={{ animationDelay: "1.3s" }} />
          <span className="lp-ring" style={{ animationDelay: "2.6s" }} />
        </div>

        {/* 漂浮产品卡 */}
        <div className="lp-floats pointer-events-none absolute inset-0 z-10">
          <figure className="lp-float absolute left-[-12px] top-[54px]" style={{ ["--fd" as string]: 42 } as CSSProperties}>
            <div className="float-soft">
              <div className={`${cardBase} w-[200px] p-3.5`} style={{ transform: "rotate(-6deg)" }}>
                <p className="m-0 text-[11px] font-semibold text-[#8a8275] dark:text-[#9a9184]">今日官方岗位</p>
                <p className="mb-0 mt-1.5 text-[2.1rem] font-extrabold leading-none tabular-nums" data-count="24">0</p>
                <p className="mb-0 mt-1.5 text-[12px] text-[#8a8275] dark:text-[#9a9184]"><span className="tabular-nums" data-count="11">0</span> 个高匹配待处理</p>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-black/[0.07] dark:bg-white/[0.08]"><div className="h-full w-[46%] rounded-full bg-[#7fb2e8]" /></div>
              </div>
            </div>
            <figcaption className="mt-2 text-[12px] text-[#9a9184] dark:text-[#837c70]">今日看板</figcaption>
          </figure>

          <figure className="lp-float absolute right-[-16px] top-[30px]" style={{ ["--fd" as string]: 30 } as CSSProperties}>
            <div className="float-soft" style={{ animationDelay: "1.3s" }}>
              <div className={`${cardBase} w-[236px] p-4`} style={{ transform: "rotate(5deg)" }}>
                <div className="flex items-center gap-1.5 text-[12px] text-[#8a8275] dark:text-[#9a9184]"><b className="text-[#1a1714] dark:text-[#f3ecdf]">Apple</b>·上海</div>
                <p className="mb-0 mt-2 text-[15px] font-bold leading-snug">Machine Learning Engineer</p>
                <div className="mt-3.5 flex items-center justify-between">
                  <div className="flex gap-1.5">
                    <span className="rounded-full bg-black/[0.06] px-2.5 py-0.5 text-[11px] font-semibold dark:bg-white/[0.08]">外企</span>
                    <span className="rounded-full bg-black/[0.06] px-2.5 py-0.5 text-[11px] font-semibold dark:bg-white/[0.08]">AI</span>
                  </div>
                  <div className="rounded-[11px] bg-[#00b85f] px-2.5 py-1 text-[15px] font-extrabold text-white tabular-nums" data-count="82">0</div>
                </div>
              </div>
            </div>
            <figcaption className="mt-2 text-right text-[12px] text-[#9a9184] dark:text-[#837c70]">官方岗位卡 · 匹配分</figcaption>
          </figure>

          <figure className="lp-float absolute bottom-[-26px] left-[6px]" style={{ ["--fd" as string]: 24 } as CSSProperties}>
            <div className="float-soft" style={{ animationDelay: "0.7s" }}>
              <div className={`${cardBase} w-[218px] p-4`} style={{ transform: "rotate(3deg)" }}>
                <p className="m-0 text-[11px] font-semibold text-[#8a8275] dark:text-[#9a9184]">职业洞察 · 分级标时间</p>
                <ul className="m-0 mt-3 grid list-none grid-cols-2 gap-2.5 p-0 text-[12px] text-[#5f594e] dark:text-[#b6ad9d]">
                  <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#7fb2e8]" />时机</li>
                  <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#b6da7e]" />薪酬</li>
                  <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#e7b27e]" />路径</li>
                  <li className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-[#cfc6b6]" />文化</li>
                </ul>
              </div>
            </div>
            <figcaption className="mt-2 text-[12px] text-[#9a9184] dark:text-[#837c70]">职业洞察</figcaption>
          </figure>

          <figure className="lp-float absolute bottom-[-14px] right-[8px]" style={{ ["--fd" as string]: 38 } as CSSProperties}>
            <div className="float-soft" style={{ animationDelay: "2s" }}>
              <div className="flex w-[206px] items-center gap-2.5 rounded-[18px] bg-[#1a1714] p-4 shadow-[0_22px_48px_-20px_rgba(40,34,28,0.4)] transition-shadow duration-300 hover:shadow-[0_30px_60px_-24px_rgba(40,34,28,0.5)] dark:bg-[#211b14]" style={{ transform: "rotate(-4deg)" }}>
                <CheckCircle size={26} weight="fill" className="shrink-0 text-[#9ad36a]" aria-hidden="true" />
                <p className="m-0 text-[13px] font-semibold leading-snug text-[#f7f1e6]">招聘平台的<br />水货岗已过滤</p>
              </div>
            </div>
            <figcaption className="mt-2 text-right text-[12px] text-[#9a9184] dark:text-[#837c70]">质量门</figcaption>
          </figure>
        </div>

        {/* 文案 */}
        <div className="relative z-20 mx-auto max-w-[820px]">
          <span className="eyebrow lp-reveal">
            <span className="relative flex size-2.5 items-center justify-center">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-[#00e676] opacity-70" />
              <span className="relative inline-flex size-2 rounded-full bg-[#00e676]" />
            </span>
            官方岗位雷达 · 每天更新
          </span>
          <h1 className="display-tight lp-reveal mt-6 text-balance text-[clamp(2.9rem,7.6vw,6rem)] font-black leading-[1.14] tracking-[-0.035em]">
            官方在招，<br />
            <span className="relative whitespace-nowrap">
              值得才投
              <span className="absolute inset-x-[-6px] bottom-[0.1em] -z-10 h-[0.32em] rounded-[0.2em] bg-[#00e676]/35" aria-hidden="true" />
            </span>
            。
          </h1>
          <p className="lp-reveal mx-auto mt-6 max-w-[600px] text-pretty text-[17px] leading-[1.75] text-[#5f594e] dark:text-[#b6ad9d]">
            职达只抓企业官方招聘页，过滤掉招聘平台的转载和过期岗；再按你的城市、方向和简历排序，并附上招聘节奏、薪酬和跳槽路径的参考。每天打开一次，只看真正值得看的。
          </p>
          <div className="lp-reveal mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link href={primaryHref} className="btn-ink cursor-target text-base">
              {primaryLabel}
              <ArrowRight size={18} weight="bold" aria-hidden="true" />
            </Link>
            <a href="#why" className="btn-ghost cursor-target text-base">看看怎么用</a>
          </div>
          <p className="lp-reveal mt-5 text-[13px] text-[#9a9184] dark:text-[#837c70]">
            已接入 Apple · 字节 · 腾讯 · 京东 · 微软 等 800+ 官方招聘源，每日更新
          </p>
        </div>
      </section>

      {/* ——— 公司官方源 ——— */}
      <div className="lp-reveal mx-auto mt-6 max-w-6xl px-6">
        <p className="mb-4 text-center text-[12px] font-bold uppercase tracking-[0.16em] text-[#9a9184] dark:text-[#837c70]">岗位只来自这些企业的官方招聘源</p>
        <div className="lp-marquee overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)] [-webkit-mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)]">
          <div className="lp-marquee-track gap-3 py-2">
            {[...COMPANIES, ...COMPANIES].map((c, i) => (
              <span
                key={`${c}-${i}`}
                className="inline-flex shrink-0 items-center gap-2 rounded-full border border-white/70 bg-white/45 px-5 py-3 text-[15px] font-semibold text-[#1a1714] shadow-[0_10px_26px_-20px_rgba(40,34,28,0.4)] backdrop-blur-md dark:border-white/[0.14] dark:bg-white/[0.06] dark:text-[#f3ecdf]"
              >
                <span className="size-1.5 rounded-full bg-[#00e676] opacity-80" />
                {c}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ——— 为什么选它 ——— */}
      <section id="why" className="mx-auto max-w-6xl px-6 py-24">
        <div className="lp-reveal max-w-2xl">
          <span className="text-[12px] font-bold uppercase tracking-[0.14em] text-[#a08a5e]">为什么是职达</span>
          <h2 className="display-tight mt-3.5 text-balance text-[clamp(2rem,4.6vw,2.9rem)] font-extrabold leading-[1.14] tracking-[-0.02em]">
            少一点假岗位和噪音，<br className="hidden sm:block" />多一点能直接投的好机会。
          </h2>
          <p className="mt-5 text-pretty text-[17px] leading-[1.7] text-[#5f594e] dark:text-[#b6ad9d]">
            不是又一个聚合搜索框。职达把「找到官方真岗位」这件事，拆成四件你能感知到的事。
          </p>
        </div>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PILLARS.map((p, i) => (
            <article
              key={p.title}
              className="lp-tilt lp-reveal bento-glow cursor-target rounded-[22px] border border-black/[0.06] bg-white/70 p-6 hover:bg-white dark:border-white/[0.08] dark:bg-white/[0.04] dark:hover:bg-white/[0.07]"
              style={{ ["--d" as string]: `${i * 0.08}s` } as CSSProperties}
            >
              <div className="flex items-center justify-between">
                <span className="grid size-11 place-items-center rounded-[14px] bg-[#f4efe6] text-[#1a1714] dark:bg-white/[0.08] dark:text-[#f3ecdf]">
                  <p.icon size={22} weight="fill" aria-hidden="true" />
                </span>
                <span className="size-2.5 rounded-full" style={{ background: p.dot }} />
              </div>
              <h3 className="display-tight mt-5 text-[1.4rem] font-extrabold">{p.title}</h3>
              <p className="mt-2.5 text-pretty text-[14px] leading-[1.65] text-[#5f594e] dark:text-[#b6ad9d]">{p.text}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ——— 和平台的区别 ——— */}
      <section id="vs" className="mx-auto max-w-6xl px-6 py-12">
        <div className="lp-reveal max-w-2xl">
          <span className="text-[12px] font-bold uppercase tracking-[0.14em] text-[#a08a5e]">和刷招聘平台有什么不一样</span>
          <h2 className="display-tight mt-3.5 text-balance text-[clamp(2rem,4.6vw,2.9rem)] font-extrabold leading-[1.14] tracking-[-0.02em]">
            同样是找工作，<br className="hidden sm:block" />看到的东西完全不同。
          </h2>
        </div>
        <div className="mt-12 grid gap-4 sm:grid-cols-2">
          <div className="lp-reveal rounded-[22px] border border-black/[0.06] bg-white/55 p-7 dark:border-white/[0.08] dark:bg-white/[0.03]">
            <h3 className="text-[1.25rem] font-extrabold text-[#5f594e] dark:text-[#b6ad9d]">刷招聘平台</h3>
            <div className="mt-3.5">
              {["真岗、假岗、钓鱼岗混在一起", "大量挂着却早就招满的过期岗", "中介转载，点进去还要再注册", "每天刷很久，真正合适的没几个"].map((line) => (
                <div key={line} className="flex items-start gap-3 rounded-xl px-2.5 py-3 text-[15px] leading-snug transition-colors hover:bg-black/[0.03] dark:hover:bg-white/[0.04]">
                  <span className="mt-0.5 grid size-[22px] shrink-0 place-items-center rounded-full bg-black/[0.07] text-[#8a8275] dark:bg-white/[0.08] dark:text-[#9a9184]"><X size={12} weight="bold" aria-hidden="true" /></span>
                  {line}
                </div>
              ))}
            </div>
          </div>
          <div className="lp-reveal relative overflow-hidden rounded-[22px] bg-[#1a1714] p-7 text-[#f7f1e6] dark:bg-[#211b14]" style={{ ["--d" as string]: "0.1s" } as CSSProperties}>
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_80%_at_100%_0,rgba(0,230,118,0.18),transparent_55%)]" aria-hidden="true" />
            <h3 className="relative flex items-center gap-2.5 text-[1.25rem] font-extrabold">
              <span className="size-2.5 rounded-full bg-[#00e676]" />职达 JobRadar
            </h3>
            <div className="relative mt-3.5">
              {["只有企业官网直发的真岗位", "都还在招，链接点开就是详情页", "按你的背景排序，合适的排在前面", "每天五分钟，只看真正值得看的"].map((line) => (
                <div key={line} className="flex items-start gap-3 rounded-xl px-2.5 py-3 text-[15px] leading-snug transition-colors hover:bg-white/[0.07]">
                  <span className="mt-0.5 grid size-[22px] shrink-0 place-items-center rounded-full bg-[#00e676]/20 text-[#00e676]"><CheckCircle size={14} weight="bold" aria-hidden="true" /></span>
                  {line}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ——— 职业洞察暗带 ——— */}
      <section id="insight" className="mx-auto max-w-6xl px-6 py-12">
        <div className="lp-reveal relative overflow-hidden rounded-[30px] border border-black/[0.06] bg-[#1a1714] px-6 py-14 text-[#f7f1e6] dark:border-white/[0.08] dark:bg-[#211b14] sm:px-11">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(80%_60%_at_100%_0,rgba(0,230,118,0.1),transparent_55%)]" aria-hidden="true" />
          <div className="relative max-w-2xl">
            <span className="text-[12px] font-bold uppercase tracking-[0.14em] text-[#cdbf9b]">不只告诉你在招</span>
            <h2 className="display-tight mt-3.5 text-balance text-[clamp(2rem,4.6vw,2.9rem)] font-extrabold leading-[1.14] tracking-[-0.02em]">
              还告诉你，<br className="hidden sm:block" />这家公司值不值得投。
            </h2>
            <p className="mt-5 text-pretty text-[16px] leading-[1.7] text-[#cfc6b6]">
              招聘节奏、薪酬对比、跳槽路径、团队风格——都来自公开渠道，不做指名的断言，只做聚合归因、分级标注、标好时间。
            </p>
          </div>
          <div className="relative mt-11 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {INSIGHT_DIMS.map((d) => (
              <article key={d.title} className="rounded-[20px] border border-white/10 bg-white/[0.05] p-5 transition duration-200 hover:-translate-y-1.5 hover:bg-white/[0.09]">
                <div className="flex items-center justify-between">
                  <span className="grid size-10 place-items-center rounded-[14px] bg-white/10 text-[#f7f1e6]"><d.icon size={20} weight="fill" aria-hidden="true" /></span>
                  <span className="size-2.5 rounded-full" style={{ background: d.dot }} />
                </div>
                <h3 className="display-tight mt-5 text-[1.3rem] font-extrabold">{d.title}</h3>
                <p className="mt-2 text-pretty text-[13px] leading-[1.6] text-[#b3aa9b]">{d.text}</p>
              </article>
            ))}
          </div>
          <ul className="relative mt-9 grid list-none gap-x-8 gap-y-4 border-t border-white/10 p-0 pt-8 sm:grid-cols-3">
            {GUARDS.map((g) => (
              <li key={g.b} className="flex items-start gap-3 text-[14px] leading-[1.55] text-[#cfc6b6]">
                <g.icon size={19} weight="fill" className="mt-0.5 shrink-0 text-[#9ad36a]" aria-hidden="true" />
                <span><b className="text-[#f7f1e6]">{g.b}</b>{g.t}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ——— 适用人群 ——— */}
      <section id="who" className="mx-auto max-w-6xl px-6 py-24">
        <div className="lp-reveal max-w-2xl">
          <span className="text-[12px] font-bold uppercase tracking-[0.14em] text-[#a08a5e]">谁在用</span>
          <h2 className="display-tight mt-3.5 text-balance text-[clamp(2rem,4.6vw,2.9rem)] font-extrabold leading-[1.14] tracking-[-0.02em]">
            校招、实习、社招，<br className="hidden sm:block" />哪个阶段都能用。
          </h2>
          <p className="mt-5 text-pretty text-[17px] leading-[1.7] text-[#5f594e] dark:text-[#b6ad9d]">不管你在求职的哪一段，职达只给你官方、最新、匹配的信号。</p>
        </div>
        <div className="mt-12 grid gap-4 sm:grid-cols-3">
          {AUDIENCES.map((a, i) => (
            <article
              key={a.tag}
              className="lp-reveal cursor-target group rounded-[22px] border border-black/[0.06] bg-white/70 p-7 transition duration-300 hover:-translate-y-1.5 hover:bg-white hover:shadow-[0_24px_50px_-26px_rgba(40,34,28,0.4)] dark:border-white/[0.08] dark:bg-white/[0.04] dark:hover:bg-white/[0.07]"
              style={{ ["--d" as string]: `${i * 0.1}s` } as CSSProperties}
            >
              <div className="flex items-center gap-3">
                <span className="grid size-11 place-items-center rounded-[14px] bg-[#f4efe6] text-[#1a1714] transition-transform duration-300 group-hover:-rotate-6 dark:bg-white/[0.08] dark:text-[#f3ecdf]">
                  <a.icon size={22} weight="fill" aria-hidden="true" />
                </span>
                <span className="display-tight text-[1.4rem] font-extrabold">{a.tag}</span>
              </div>
              <p className="mt-5 text-pretty text-[14px] leading-[1.65] text-[#5f594e] dark:text-[#b6ad9d]">{a.text}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ——— 收尾 CTA ——— */}
      <section className="mx-auto max-w-6xl px-6 pb-24">
        <div className="lp-reveal relative overflow-hidden rounded-[30px] border border-black/[0.06] bg-white/70 px-6 py-16 text-center dark:border-white/[0.08] dark:bg-white/[0.04]">
          <span className="eyebrow">
            <span className="size-2 rounded-full bg-[#00e676]" />今天就开始
          </span>
          <h2 className="display-tight mx-auto mt-5 max-w-3xl text-balance text-[clamp(2.4rem,5.6vw,4rem)] font-black leading-[1.18] tracking-[-0.035em]">
            每天五分钟，<br className="hidden sm:block" />只看值得看的官方真岗位。
          </h2>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {["城市匹配", "简历画像", "官方源校验", "分级职业洞察"].map((c) => (
              <span key={c} className="rounded-full border border-black/[0.07] bg-white px-4 py-1.5 text-[13px] font-semibold text-[#6b655a] transition-transform hover:-translate-y-0.5 dark:border-white/[0.1] dark:bg-white/[0.06] dark:text-[#b6ad9d]">{c}</span>
            ))}
          </div>
          <div className="mt-8 flex justify-center">
            <Link href={primaryHref} className="btn-ink cursor-target text-base">
              {primaryLabel}
              <ChartLineUp size={18} weight="fill" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>

      {/* ——— 页脚 ——— */}
      <footer className="border-t border-black/[0.06] dark:border-white/[0.08]">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-6 py-9 sm:flex-row sm:justify-between">
          <Link href="/" className="transition-opacity hover:opacity-70">
            <BrandMark tile={28} icon={18} wordSize={15} />
          </Link>
          <p className="max-w-xl text-[12px] leading-5 text-[#9a9184] dark:text-[#837c70]">
            岗位仅来自企业官方公开渠道；职业洞察以聚合形式呈现、来源去标识，支持通知后删除。© 2026 职达 JobRadar
          </p>
        </div>
      </footer>
    </main>
  );
}
