export const dynamic = "force-dynamic";

import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { MetricTile, ProductHero, ProductPage } from "@/components/ProductChrome";
import {
  ArrowSquareOut,
  CalendarBlank,
  ClipboardText,
  Megaphone,
  SealCheck,
  Student,
  UsersThree,
} from "@phosphor-icons/react/ssr";
import { Badge, EmptyState, buttonVariants } from "@/components/ui";
import { cn } from "@/lib/utils";
import { formatDateLabel, todayInDisplayZone } from "@/lib/relative-time";
import { getRequestUser } from "@/lib/auth";
import { getApplyPrograms } from "@/lib/apply-programs-store";
import { getAnnouncementPostings } from "@/lib/announcement-postings-store";
import {
  PROGRAM_TYPE_HINT,
  PROGRAM_TYPE_LABEL,
  PROGRAM_TYPE_TONE,
  type ApplyProgram,
} from "@/lib/apply-programs";
import AnnouncementsClient from "./announcements-client";

export const metadata = { title: "公告制招聘 · 求职雷达" };

// 为什么单独一个入口：有一类招聘**客观上不存在「一岗一页」** —— 事业单位/体制内多为公告制
// （一条公告 = 批量岗位 + 报名截止日，官网没有逐个岗位的详情页），中通校招是「蓝天计划」项目制投递。
// 它们进不了岗位库（过不了 jd_url 红线，也不该假装是岗位），此前就等于在产品里不存在。
//
// 数据两路：apply_programs（手工核实的边缘条目，如中国银行）+ announcement_postings（官方源自动抓取
// 的招聘公告，事业单位/体制内，量大带时效）。两者在「招聘公告」区统一展示。
//
// ⚠️ 设计红线：**绝不能让它看起来像岗位列表**——整卡不可点、留着「为什么没有逐岗列表」的说明、
// 分区标题写清这是公告/项目/人才库。用「看起来有岗」骗点击，比不展示更伤信任。

const TYPE_ICON = { campus_program: Student, announcement: ClipboardText, talent_pool: UsersThree };
const TYPE_TILE = {
  campus_program: "border-tone-green-border bg-tone-green-bg text-tone-green-fg",
  announcement: "border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
  talent_pool: "border-tone-neutral-border bg-tone-neutral-bg text-tone-neutral-fg",
};

/** 手工核实条目卡（apply_programs）。 */
function ProgramCard({ program }: { program: ApplyProgram }) {
  const verified = formatDateLabel(program.verifiedAt);
  return (
    <li className="surface surface-hover flex h-full flex-col p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="t-h3">{program.company}</h3>
        {program.industry ? <Badge tone="neutral" size="xs">{program.industry}</Badge> : null}
      </div>
      <p className="t-body-sm ink-2 mt-1.5 font-medium">{program.programName}</p>
      {program.description ? <p className="t-body-sm ink-3 mt-3">{program.description}</p> : null}
      {program.windowText ? (
        <p className="t-caption mt-3 inline-flex items-start gap-1.5 rounded-lg border border-tone-amber-border bg-tone-amber-bg px-2.5 py-1.5 text-tone-amber-fg">
          <CalendarBlank size={14} weight="bold" aria-hidden className="mt-0.5 shrink-0" />
          <span>对方页面写的时间窗：{program.windowText}</span>
        </p>
      ) : null}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-black/[0.06] pt-4 dark:border-white/[0.08]">
        <span className="t-caption ink-3 inline-flex items-center gap-1.5">
          <SealCheck size={14} weight="fill" aria-hidden className="shrink-0" />
          {verified ? `${verified} 人工核实` : "入口已人工核实"}
        </span>
        <a
          className={cn(buttonVariants({ variant: "ink", size: "sm" }), "press-feedback")}
          href={program.entryUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          去官方入口投递
          <ArrowSquareOut size={14} weight="bold" aria-hidden />
        </a>
      </div>
    </li>
  );
}

function SectionHeader({
  type,
  count,
}: {
  type: "campus_program" | "announcement" | "talent_pool";
  count: number;
}) {
  const Icon = TYPE_ICON[type];
  return (
    <div className="flex items-start gap-3">
      <span
        aria-hidden="true"
        className={cn("mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl border", TYPE_TILE[type])}
      >
        <Icon size={18} weight="fill" />
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="t-h2">{PROGRAM_TYPE_LABEL[type]}</h2>
          <Badge tone={PROGRAM_TYPE_TONE[type]} size="xs">{count} 项</Badge>
        </div>
        <p className="t-body-sm ink-3 mt-1">{PROGRAM_TYPE_HINT[type]}</p>
      </div>
    </div>
  );
}

export default async function ProgramsPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/programs");

  // 互不依赖 → 并行取（冷启动别串行等两次）。
  const [programs, postings] = await Promise.all([getApplyPrograms(), getAnnouncementPostings()]);
  // ⚠️ 「今天」在服务端算一次传下去：两端各自 new Date() 会因时区不同算出不同的「还剩几天」，
  //    导致水合文本不一致（项目已因裸 toLocaleDateString 踩过 React #418）。
  const today = todayInDisplayZone();

  const campus = programs.filter((p) => p.programType === "campus_program");
  const manualAnnouncements = programs.filter((p) => p.programType === "announcement");
  const talentPool = programs.filter((p) => p.programType === "talent_pool");
  const announcementCount = manualAnnouncements.length + postings.length;
  const total = programs.length + postings.length;

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          title="公告制招聘"
          icon={Megaphone}
          align="center"
          action={
            total > 0 ? (
              <MetricTile label="已核实投递入口" value={total} icon={SealCheck} tone="lime" />
            ) : undefined
          }
        />

        {total === 0 ? (
          <div className="mt-10">
            <EmptyState
              title="还没有已核实的投递入口"
              description="入口链接必须核实能打开、且报名未截止才会展示——没核实、已过期的宁可不放。"
            />
          </div>
        ) : (
          <div className="mt-10 space-y-12">
            {campus.length > 0 ? (
              <section>
                <SectionHeader type="campus_program" count={campus.length} />
                <ul className="mt-5 grid gap-4 lg:grid-cols-2">
                  {campus.map((p) => <ProgramCard key={p.entryUrl} program={p} />)}
                </ul>
              </section>
            ) : null}

            {announcementCount > 0 ? (
              <section>
                <SectionHeader type="announcement" count={announcementCount} />

                {/* 人工核实的少量条目单列一组：它们没有地区/受众字段，跟着筛选器一起被筛掉会显得「东西丢了」，
                    而且「人工核实过」本身是更强的信任信号，值得放在前面。 */}
                {manualAnnouncements.length > 0 ? (
                  <div className="mt-5">
                    <h3 className="t-label ink-3 mb-2.5">人工核实的投递入口 · {manualAnnouncements.length}</h3>
                    <ul className="grid gap-4 lg:grid-cols-2">
                      {manualAnnouncements.map((p) => <ProgramCard key={p.entryUrl} program={p} />)}
                    </ul>
                  </div>
                ) : null}

                {postings.length > 0 ? (
                  <div className="mt-7">
                    <h3 className="t-label ink-3 mb-2.5">各省人社厅官网每日抓取 · 已复验报名未截止</h3>
                    <AnnouncementsClient postings={postings} today={today} />
                  </div>
                ) : null}
              </section>
            ) : null}

            {talentPool.length > 0 ? (
              <section>
                <SectionHeader type="talent_pool" count={talentPool.length} />
                <ul className="mt-5 grid gap-4 lg:grid-cols-2">
                  {talentPool.map((p) => <ProgramCard key={p.entryUrl} program={p} />)}
                </ul>
              </section>
            ) : null}
          </div>
        )}
      </ProductPage>
    </div>
  );
}
