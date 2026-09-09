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
import { formatDateLabel } from "@/lib/relative-time";
import { getRequestUser } from "@/lib/auth";
import { getApplyPrograms } from "@/lib/apply-programs-store";
import { groupByType, PROGRAM_TYPE_TONE, type ApplyProgramType } from "@/lib/apply-programs";

export const metadata = { title: "公告制招聘 · 求职雷达" };

// 为什么单独一个入口：有一类公司**客观上不存在「一岗一页」** —— 中通校招是「蓝天计划」
// 项目制投递（整页只有项目介绍 + 宣讲会 + 一个投递按钮，没有岗位列表），国有大行是公告制。
// 它们进不了岗位库（过不了 jd_url 红线，也不该假装是岗位），此前就等于在产品里不存在：
// 用户搜「中通 校招」一无所获，而对方其实正在招。
//
// ⚠️ 这一页的设计红线：**绝不能让它看起来像岗位列表**。所以刻意做了三件与岗位卡相反的事：
//   ① 整卡不可点（只有明确写着「去官方入口投递」的按钮可点）——岗位卡是整卡可点的；
//   ② 每张卡都留着「为什么这家没有岗位列表」的原文说明，不折叠、不截断；
//   ③ 分区标题直接写清这是公告 / 项目 / 人才库。
// 用「看起来有岗」骗点击，比不展示更伤信任。

/** 分区图标：与徽章 tone 同族，让「这是哪一类」在扫视时先于文字被看到。 */
const TYPE_ICON: Record<ApplyProgramType, typeof Megaphone> = {
  campus_program: Student,
  announcement: ClipboardText,
  talent_pool: UsersThree,
};

/**
 * 分区图标底座配色。直接用 --tone-* 语义类（不写 hex），与 Badge 的 tone 保持同一族，
 * 这样「绿=校招项目 / 琥珀=公告制 / 中性=人才库」在图标和徽章上是同一套暗示。
 */
const TYPE_TILE: Record<ApplyProgramType, string> = {
  campus_program: "border-tone-green-border bg-tone-green-bg text-tone-green-fg",
  announcement: "border-tone-amber-border bg-tone-amber-bg text-tone-amber-fg",
  talent_pool: "border-tone-neutral-border bg-tone-neutral-bg text-tone-neutral-fg",
};

export default async function ProgramsPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/programs");

  const programs = await getApplyPrograms();
  const groups = groupByType(programs);

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <ProductHero
          title="公告制招聘"
          icon={Megaphone}
          align="center"
          action={
            programs.length > 0 ? (
              <MetricTile
                label="已核实投递入口"
                value={programs.length}
                icon={SealCheck}
                tone="lime"
              />
            ) : undefined
          }
        />

        {groups.length === 0 ? (
          <div className="mt-10">
            <EmptyState
              title="还没有已核实的投递入口"
              description="入口链接必须人工核实能打开才会展示——没核实的宁可不放，也不让你点开一个死链。"
            />
          </div>
        ) : (
          <div className="mt-10 space-y-12">
            {groups.map((group) => {
              const Icon = TYPE_ICON[group.type];
              return (
                <section key={group.type}>
                  {/* 分区头：图标 + 类型名 + 计数，下面紧跟一句「为什么这类公司没有岗位列表」。
                      这句话是本页最该被读到的信息，所以给它独立一行、不塞进卡片里。 */}
                  <div className="flex items-start gap-3">
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl border",
                        TYPE_TILE[group.type],
                      )}
                    >
                      <Icon size={18} weight="fill" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="t-h2">{group.label}</h2>
                        <Badge tone={PROGRAM_TYPE_TONE[group.type]} size="xs">
                          {group.items.length} 家
                        </Badge>
                      </div>
                      <p className="t-body-sm ink-3 mt-1">{group.hint}</p>
                    </div>
                  </div>

                  {/* 两列网格：9 张卡片平铺成整屏长条会读成「岗位列表」，也浪费右半屏。
                      卡内用 flex-col + mt-auto 把按钮钉在底边，同一行的卡片高度自然对齐。 */}
                  <ul className="mt-5 grid gap-4 lg:grid-cols-2">
                    {group.items.map((program) => {
                      const verified = formatDateLabel(program.verifiedAt);
                      return (
                        <li
                          key={program.entryUrl}
                          className="surface surface-hover flex h-full flex-col p-5"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="t-h3">{program.company}</h3>
                            {program.industry ? (
                              <Badge tone="neutral" size="xs">
                                {program.industry}
                              </Badge>
                            ) : null}
                          </div>
                          <p className="t-body-sm ink-2 mt-1.5 font-medium">{program.programName}</p>

                          {program.description ? (
                            // 不截断、不折叠：这段是「为什么这家搜不到岗位」的原文交代，
                            // 折起来等于把本页存在的理由藏起来。
                            <p className="t-body-sm ink-3 mt-3">{program.description}</p>
                          ) : null}

                          {program.windowText ? (
                            // 时间窗是这页唯一带时效的信息，单独一行 + 琥珀色，别混进正文里被读漏。
                            <p className="t-caption mt-3 inline-flex items-start gap-1.5 rounded-lg border border-tone-amber-border bg-tone-amber-bg px-2.5 py-1.5 text-tone-amber-fg">
                              <CalendarBlank size={14} weight="bold" aria-hidden className="mt-0.5 shrink-0" />
                              <span>对方页面写的时间窗：{program.windowText}</span>
                            </p>
                          ) : null}

                          {/* 底边：左边是「这条链接我们核实过」的凭据，右边是唯一可点的动作。
                              mt-auto 把它压到卡底，同行卡片的按钮因此横向对齐。 */}
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
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </ProductPage>
    </div>
  );
}
