export const dynamic = "force-dynamic";

import { redirect } from "next/navigation";
import Navbar from "@/components/Navbar";
import { ProductHero, ProductPage } from "@/components/ProductChrome";
import { ArrowSquareOut, Megaphone } from "@phosphor-icons/react/ssr";
import { Badge, EmptyState } from "@/components/ui";
import { getRequestUser } from "@/lib/auth";
import { getApplyPrograms } from "@/lib/apply-programs-store";
import { groupByType, PROGRAM_TYPE_TONE } from "@/lib/apply-programs";

export const metadata = { title: "项目制投递 · 求职雷达" };

// 为什么单独一个入口：有一类公司**客观上不存在「一岗一页」** —— 中通校招是「蓝天计划」
// 项目制投递（整页只有项目介绍 + 宣讲会 + 一个投递按钮，没有岗位列表），国有大行是公告制。
// 它们进不了岗位库（过不了 jd_url 红线，也不该假装是岗位），此前就等于在产品里不存在：
// 用户搜「中通 校招」一无所获，而对方其实正在招。
//
// ⚠️ 这一页的设计红线：**绝不能让它看起来像岗位列表**。每张卡都显式标注这是项目/公告，
// 并直说「为什么这里没有岗位列表」—— 用「看起来有岗」骗点击，比不展示更伤信任。
export default async function ProgramsPage() {
  const user = await getRequestUser();
  if (!user) redirect("/login?next=/programs");

  const groups = groupByType(await getApplyPrograms());

  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-4xl">
        <ProductHero
          eyebrow="项目制投递"
          title="有些公司不按岗位挂，得从这里投"
          icon={Megaphone}
          description="这里收的是「有官方投递入口、但没有逐个岗位详情页」的公司——校招项目、招聘公告、人才库。它们不是岗位，所以不会出现在岗位库里；但对方确实在招，链接都人工核实过能打开。"
        />

        {groups.length === 0 ? (
          <div className="mt-10">
            <EmptyState
              title="还没有已核实的投递入口"
              description="入口链接必须人工核实能打开才会展示——没核实的宁可不放，也不让你点开一个死链。"
            />
          </div>
        ) : (
          <div className="mt-10 space-y-10">
            {groups.map((group) => (
              <section key={group.type}>
                <h2 className="t-h2">{group.label}</h2>
                <p className="t-body-sm ink-3 mt-1">{group.hint}</p>
                <ul className="mt-4 space-y-3">
                  {group.items.map((program) => (
                    <li key={program.entryUrl} className="surface rounded-xl p-4 sm:p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="t-h3">{program.company}</h3>
                            <Badge tone={PROGRAM_TYPE_TONE[program.programType]} size="sm">
                              {group.label}
                            </Badge>
                            {program.industry ? (
                              <span className="t-caption ink-3">{program.industry}</span>
                            ) : null}
                          </div>
                          <p className="t-body-sm ink-2 mt-1">{program.programName}</p>
                        </div>
                        <a
                          className="btn-ink t-label inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2"
                          href={program.entryUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          去官方入口投递
                          <ArrowSquareOut size={14} weight="bold" aria-hidden />
                        </a>
                      </div>
                      {program.description ? (
                        <p className="t-body-sm ink-2 mt-3">{program.description}</p>
                      ) : null}
                      {program.windowText ? (
                        <p className="t-caption ink-3 mt-2">对方页面写的时间窗：{program.windowText}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </ProductPage>
    </div>
  );
}
