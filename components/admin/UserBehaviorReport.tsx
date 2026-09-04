import {
  BarList,
  Callout,
  FunnelSteps,
  JumpTile,
  StatRing,
  StatusBadge,
  TrendLine,
} from "@/components/health-viz";
import type { BandTone } from "@/lib/admin-health";
import {
  FUNNEL_STEP_LABELS,
  MIN_SAMPLE,
  biggestDrop,
  formatPct,
  headlineSentence,
  pendingBlocks,
  rate,
  retentionTone,
  zeroResultTone,
  type UserAnalytics,
} from "@/lib/admin-user-analytics";

// 管理员看板「用户行为」模块。
//
// 形态是**一页式报告**，不是二级 tab：内容确实多，但把它们藏进 tab 等于没做——
// 管理员每次只会点开第一个。所以做成「顶部四个锚点 → 四个章节 → 人名单」，
// 一屏能扫完结论，往下滚是依据。
//
// 每章只有一个主图，数字当主角、解释压小；四章顺序 = 创始人提的四个问题的顺序。

function SectionHead({ title, desc, badge }: { title: string; desc: string; badge?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="max-w-2xl">
        <h2 className="t-h2 ink-1">{title}</h2>
        <p className="t-body-sm mt-1 ink-2">{desc}</p>
      </div>
      {badge}
    </div>
  );
}

// 大号主角数字。比率样本不足时显示分子分母，不显示一个骗人的百分比。
function BigStat({
  value,
  unit,
  label,
  hint,
  tone = "muted",
}: {
  value: React.ReactNode;
  unit?: string;
  label: string;
  hint: string;
  tone?: BandTone;
}) {
  return (
    <div className="min-w-0">
      <p className="t-caption ink-3">{label}</p>
      <p className="mt-1 flex items-baseline gap-1">
        <span className="text-[2.1rem] font-semibold leading-none tracking-[-0.04em] tabular-nums ink-1">{value}</span>
        {unit && <span className="t-body-sm ink-3">{unit}</span>}
      </p>
      <div className="mt-2"><StatusBadge tone={tone} /></div>
      <p className="t-caption mt-2 leading-5 ink-3">{hint}</p>
    </div>
  );
}

function ErrorState() {
  return (
    <section className="surface-soft p-5 sm:p-6">
      <h2 className="t-h2 ink-1">用户行为</h2>
      <Callout tone="danger" className="mt-4">
        用户行为数据这次没读出来。这里不显示 0——0 和「读失败」是两回事，看板不能拿读失败冒充「没人用」。
      </Callout>
    </section>
  );
}

export default function UserBehaviorReport({
  analytics,
  includeStaff,
}: {
  analytics: UserAnalytics | null;
  includeStaff: boolean;
}) {
  if (!analytics) return <ErrorState />;

  const a = analytics;
  const registered = Math.max(1, a.totals.registered);
  const drop = biggestDrop(a.funnel);
  const pending = pendingBlocks(a);

  // ── 章节二：回访 ────────────────────────────────────────────────────────
  const everRate = rate(a.retention.everReturned, a.retention.everCohort);
  const d7Rate = rate(a.retention.d7Returned, a.retention.d7Cohort);
  const d30Rate = rate(a.retention.d30Returned, a.retention.d30Cohort);
  const activatedUsers = a.activeDays.one + a.activeDays.twoToSix + a.activeDays.sevenPlus;

  // ── 章节三：搜索 ────────────────────────────────────────────────────────
  const zeroRate = a.search.searches > 0 ? a.search.zeroSearches / a.search.searches : null;
  const searchReady = a.search.searches >= MIN_SAMPLE;

  // ── 章节四：推荐转化 ────────────────────────────────────────────────────
  // 这四级是**次数**不是人数：一个人一天可以点开十个岗位。
  // 所以级间比值读作「平均每次打开推荐点开几个岗位」，不能读成「留下百分之几的人」。
  const r = a.recommendation;
  const perOpen = r.feedOpens > 0 ? r.officialOpens / r.feedOpens : null;
  const saveRate = r.officialOpens > 0 ? r.saves / r.officialOpens : null;
  const applyRate = r.officialOpens > 0 ? r.applies / r.officialOpens : null;

  const staffHref = includeStaff ? "/admin/health?tab=users" : "/admin/health?tab=users&staff=1";

  return (
    <div className="grid gap-5">
      {/* ── 口径条：一行说清「统计了谁、多长时间」，外加排除开关 ──
          刻意不放巨型标题句：下面四张卡本来就在说同样的结论（最大的坎 / 回访 / 白搜 / 推荐比），
          再顶一行大字既重复又压掉真正该被先看到的数字。 */}
      <section className="surface-soft flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <span className="t-label font-semibold ink-1">用户行为</span>
        <span className="t-caption ink-3">最近 {a.windowDays} 天</span>
        <span aria-hidden="true" className="h-3.5 w-px bg-black/[0.12] dark:bg-white/[0.16]" />
        <StatusBadge tone={a.totals.weekActive > 0 ? "success" : "warning"} label={`本周 ${a.totals.weekActive} 人在用`} />
        <StatusBadge tone="muted" label={`今天 ${a.totals.todayActive} 人`} />
        <StatusBadge tone="muted" label={`累计注册 ${a.totals.registered} 人`} />
        <a
          href={staffHref}
          title="不排除的话，自己人日常使用产生的几百条操作会把所有比率拉高，看着热闹但那不是真实用户"
          className="t-label ml-auto inline-flex items-center gap-1.5 rounded-full border border-black/[0.12] px-3 py-1.5 ink-2 transition hover:bg-black/[0.04] dark:border-white/[0.15] dark:hover:bg-white/[0.06]"
        >
          {includeStaff ? "已含管理员/测试号 · 点此排除" : `已排除管理员与测试号（${a.excludedUsers} 个）`}
        </a>
      </section>

      {/* ── 四个锚点：一屏读完四个问题的答案，点了跳到依据 ── */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <JumpTile
          label="① 用户卡在哪"
          value={drop ? `掉 ${drop.lost} 人` : "—"}
          hint={drop ? `最大的坎：${drop.from.label} → ${drop.to.label}` : "还没出现明显流失"}
          href="#funnel"
          tone={drop && drop.keepRate < 0.5 ? "danger" : drop ? "warning" : "muted"}
        />
        <JumpTile
          label="② 还回不回来"
          value={formatPct(everRate)}
          hint={`${a.retention.everReturned}/${a.retention.everCohort} 人换一天还会再来`}
          href="#retention"
          tone={retentionTone(everRate)}
        />
        <JumpTile
          label="③ 搜完有没有货"
          value={searchReady ? formatPct(zeroRate) : "积累中"}
          hint={searchReady ? `${a.search.zeroSearches}/${a.search.searches} 次搜索一条都没搜到` : "搜索埋点刚上线，数据从明天开始"}
          href="#search"
          tone={searchReady ? zeroResultTone(zeroRate) : "muted"}
        />
        <JumpTile
          label="④ 推的准不准"
          value={perOpen == null ? "—" : perOpen.toFixed(1)}
          hint="平均每次打开今日推荐，点开几个岗位官网"
          href="#reco"
          tone={perOpen == null ? "muted" : perOpen >= 1 ? "success" : "warning"}
        />
      </section>

      {pending.length > 0 && (
        <Callout tone="muted">
          <span className="font-medium">{pending.join("、")}</span> 这
          {pending.length > 1 ? "两" : "一"}块埋点是今天新加的，历史数据补不回来，
          明天开始才会有真实数字。在此之前这里显示「积累中」，不显示 0——显示 0 会让人误以为「没人搜」。
        </Callout>
      )}

      {/* ══ 章节一：用户卡在哪一步 ══════════════════════════════════════ */}
      <section id="funnel" className="surface-soft scroll-mt-20 p-5 sm:p-6">
        <SectionHead
          title="① 用户卡在哪一步"
          desc="从注册到真的去投递，每一步还剩多少人。哪一级掉得最狠，下一步就修哪儿。"
          badge={<StatusBadge tone={drop && drop.keepRate < 0.5 ? "danger" : "warning"} label={drop ? `最大流失 ${drop.lost} 人` : "暂无明显流失"} />}
        />
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_15rem]">
          <FunnelSteps steps={a.funnel} baseline={registered} ariaLabel="用户激活漏斗" />
          <aside className="grid content-start gap-3">
            <div className="rounded-xl border border-black/[0.06] bg-white/45 p-3.5 dark:border-white/[0.09] dark:bg-white/[0.04]">
              <p className="t-caption font-medium ink-2">顺带看这几个</p>
              <dl className="mt-2.5 space-y-2.5">
                {[
                  ["传过简历", a.sideMetrics.resumeUploaded, "可选动作，不算漏斗一级"],
                  ["被「先设目标」拦下", a.sideMetrics.onboardingBlocked, "打开今日推荐时没设过求职目标"],
                  ["收藏过岗位", a.sideMetrics.saved, "投递之前的犹豫信号"],
                ].map(([label, value, hint]) => (
                  <div key={label as string}>
                    <dt className="t-caption ink-3">{label}</dt>
                    <dd className="mt-0.5">
                      <span className="text-lg font-semibold tabular-nums ink-1">{value as number}</span>
                      <span className="t-caption ml-1 ink-3">人</span>
                      <p className="t-micro mt-0.5 leading-4 ink-3">{hint}</p>
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </aside>
        </div>
        <p className="t-body-sm mt-4 ink-2">{headlineSentence(a)}</p>
        {a.sideMetrics.onboardingBlocked > registered * 0.5 && (
          <Callout tone="warning" className="mt-4">
            {a.sideMetrics.onboardingBlocked} 人（{Math.round((a.sideMetrics.onboardingBlocked / registered) * 100)}%）
            第一次打开今日推荐时，被「请先设置求职目标」挡在门外。新用户的第一屏就是一道空白表单，
            这通常是流失最集中的地方——值得考虑先给他们看几个岗位，再请他们填。
          </Callout>
        )}
      </section>

      {/* ══ 章节二：还回不回来 ══════════════════════════════════════════ */}
      <section id="retention" className="surface-soft scroll-mt-20 p-5 sm:p-6">
        <SectionHead
          title="② 用户还回不回来"
          desc="回访 = 注册那天之外，还有别的日子来过。一次性用户多，说明产品还没给出「明天还得来看看」的理由。"
          badge={<StatusBadge tone={retentionTone(everRate)} label={`回访 ${formatPct(everRate)}`} />}
        />
        <div className="grid gap-5 sm:grid-cols-3">
          <BigStat
            label="来过第二天"
            value={formatPct(everRate)}
            tone={retentionTone(everRate)}
            hint={`${a.retention.everReturned} / ${a.retention.everCohort} 人（注册满 1 天的都算进分母）`}
          />
          <BigStat
            label="注册后 7 天内回来过"
            value={formatPct(d7Rate)}
            tone={retentionTone(d7Rate)}
            hint={`${a.retention.d7Returned} / ${a.retention.d7Cohort} 人（只算注册满 7 天的）`}
          />
          <BigStat
            label="注册后 30 天内回来过"
            value={formatPct(d30Rate)}
            tone={retentionTone(d30Rate)}
            hint={`${a.retention.d30Returned} / ${a.retention.d30Cohort} 人（只算注册满 30 天的）`}
          />
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="rounded-xl border border-black/[0.06] p-4 dark:border-white/[0.08]">
            <p className="t-label ink-2">每天有几个人在用</p>
            <TrendLine
              className="mt-3"
              ariaLabel="每日活跃用户"
              points={a.dailyActive.map((d) => ({ label: d.date.slice(5), value: d.users }))}
              tone={a.totals.weekActive > 0 ? "success" : "warning"}
              formatValue={(v) => `${v} 人`}
            />
          </div>
          <div className="rounded-xl border border-black/[0.06] p-4 dark:border-white/[0.08]">
            <p className="t-label ink-2">每人一共来过几天</p>
            <BarList
              className="mt-3"
              ariaLabel="活跃天数分布"
              items={[
                { key: "one", label: "只来过 1 天", value: `${a.activeDays.one} 人`, ratio: activatedUsers ? a.activeDays.one / activatedUsers : null, tone: "danger", caption: "看一眼就走了" },
                { key: "few", label: "来过 2–6 天", value: `${a.activeDays.twoToSix} 人`, ratio: activatedUsers ? a.activeDays.twoToSix / activatedUsers : null, tone: "warning", caption: "有回访但还没成习惯" },
                { key: "many", label: "来过 7 天以上", value: `${a.activeDays.sevenPlus} 人`, ratio: activatedUsers ? a.activeDays.sevenPlus / activatedUsers : null, tone: "success", caption: "真正的常客" },
              ]}
            />
          </div>
        </div>
      </section>

      {/* ══ 章节三：用户在找什么 ════════════════════════════════════════ */}
      <section id="search" className="surface-soft scroll-mt-20 p-5 sm:p-6">
        <SectionHead
          title="③ 用户在找什么"
          desc="他们搜的词、想去的城市、要的岗位方向。「一条都没搜到」的比例最重要——它直接说明岗位库对用户想要的东西有没有货。"
          badge={<StatusBadge tone={searchReady ? zeroResultTone(zeroRate) : "muted"} label={searchReady ? `空手而归 ${formatPct(zeroRate)}` : "数据积累中"} />}
        />
        {!searchReady ? (
          <Callout tone="muted">
            搜索埋点今天刚上线，目前累计 {a.search.searches} 次，样本不足 {MIN_SAMPLE} 次还不出结论。
            用户搜了什么、有多少次白搜，明天起会出现在这里。
          </Callout>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[11rem_minmax(0,1fr)] lg:items-start">
            <div className="flex justify-center lg:justify-start">
              <StatRing pct={zeroRate} tone={zeroResultTone(zeroRate)} size="section">
                <span className="text-2xl font-semibold tabular-nums ink-1">{formatPct(zeroRate)}</span>
                <span className="t-micro mt-1 ink-2">搜完一条没有</span>
              </StatRing>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <p className="t-label mb-2 ink-2">搜得最多的词</p>
                <BarList
                  ariaLabel="热门搜索词"
                  items={a.search.topKeywords.slice(0, 6).map((k, i) => ({
                    key: `kw-${i}`,
                    label: k.value,
                    value: `${k.count} 次`,
                    ratio: a.search.topKeywords[0]?.count ? k.count / a.search.topKeywords[0].count : null,
                    tone: k.zero > 0 && k.zero / k.count > 0.5 ? "danger" : "success",
                    caption: k.zero > 0 ? `其中 ${k.zero} 次没搜到` : undefined,
                  }))}
                />
              </div>
              <div>
                <p className="t-label mb-2 ink-2">想去的城市</p>
                <BarList
                  ariaLabel="热门城市"
                  items={a.search.topCities.slice(0, 6).map((k, i) => ({
                    key: `city-${i}`, label: k.value, value: `${k.count} 次`,
                    ratio: a.search.topCities[0]?.count ? k.count / a.search.topCities[0].count : null,
                  }))}
                />
              </div>
              <div>
                <p className="t-label mb-2 ink-2">要的岗位方向</p>
                <BarList
                  ariaLabel="热门岗位方向"
                  items={a.search.topFunctions.slice(0, 6).map((k, i) => ({
                    key: `fn-${i}`, label: k.value, value: `${k.count} 次`,
                    ratio: a.search.topFunctions[0]?.count ? k.count / a.search.topFunctions[0].count : null,
                  }))}
                />
              </div>
            </div>
          </div>
        )}
        {a.pages.length > 0 && (
          <div className="mt-5">
            <p className="t-label mb-2 ink-2">哪几个页面被打开得最多</p>
            <BarList
              ariaLabel="页面浏览分布"
              items={a.pages.slice(0, 8).map((p) => ({
                key: p.path,
                label: PAGE_LABELS[p.path] || p.path,
                value: `${p.views} 次`,
                valueDetail: `${p.users} 人`,
                ratio: a.pages[0]?.views ? p.views / a.pages[0].views : null,
              }))}
            />
          </div>
        )}
      </section>

      {/* ══ 章节四：推的准不准 ══════════════════════════════════════════ */}
      <section id="reco" className="surface-soft scroll-mt-20 p-5 sm:p-6">
        <SectionHead
          title="④ 我们推的准不准"
          desc="这四个数是「次数」不是「人数」——一个人一天可以点开十个岗位。级与级之间的比值，就是推荐质量。"
        />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {([
            { label: "打开今日推荐", value: r.feedOpens, unit: "次", hint: "用户主动来看我们推的机会", tone: "muted" },
            { label: "点开岗位官网", value: r.officialOpens, unit: "次", hint: perOpen == null ? "—" : `平均每次打开推荐点开 ${perOpen.toFixed(1)} 个`, tone: perOpen != null && perOpen >= 1 ? "success" : "warning" },
            { label: "收藏", value: r.saves, unit: "次", hint: saveRate == null ? "—" : `点开的岗位里 ${formatPct(saveRate)} 被收藏`, tone: "muted" },
            { label: "标记投递", value: r.applies, unit: "次", hint: applyRate == null ? "—" : `点开的岗位里 ${formatPct(applyRate)} 真去投了`, tone: applyRate != null && applyRate > 0 ? "success" : "warning" },
          ] as Array<{ label: string; value: number; unit: string; hint: string; tone: BandTone }>).map((s) => (
            <div key={s.label} className="rounded-xl border border-black/[0.06] p-4 dark:border-white/[0.08]">
              <BigStat label={s.label} value={s.value} unit={s.unit} hint={s.hint} tone={s.tone} />
            </div>
          ))}
        </div>
        <Callout tone="muted" className="mt-4">
          这一段用的是最近 {a.windowDays} 天的操作次数。「标记投递」是用户自己在产品里点的，
          不等于他真的投了简历——真实投递发生在企业官网上，我们看不到，也不该假装看得到。
        </Callout>
      </section>

      {/* ══ 人名单 ══════════════════════════════════════════════════════ */}
      <section className="surface-soft p-5 sm:p-6">
        <SectionHead
          title="一个一个看"
          desc="70 人体量下，比任何比率都有用的是「这个人注册完干了啥、卡在哪」。这里不显示邮箱，只给一个短编号。"
        />
        <details className="group">
          <summary className="t-label inline-flex cursor-pointer list-none items-center gap-2 rounded-full border border-black/[0.12] px-3.5 py-1.5 ink-2 transition hover:bg-black/[0.04] dark:border-white/[0.15] dark:hover:bg-white/[0.06]">
            <span className="transition group-open:rotate-90" aria-hidden="true">▸</span>
            展开全部 {a.users.length} 位用户
          </summary>
          <div className="mt-4 max-h-[36rem] overflow-auto rounded-2xl border border-black/[0.07] dark:border-white/[0.1]">
            <table className="w-full min-w-[46rem] text-left">
              <thead className="sticky top-0 z-10 bg-[#f4efe6] dark:bg-[#1c1813]">
                <tr className="t-caption ink-3">
                  <th className="px-4 py-3 font-medium">编号</th>
                  <th className="px-4 py-3 font-medium">走到哪一步</th>
                  <th className="px-4 py-3 font-medium">行业 / 阶段</th>
                  <th className="px-4 py-3 text-right font-medium">来过几天</th>
                  <th className="px-4 py-3 text-right font-medium">操作次数</th>
                  <th className="px-4 py-3 font-medium">注册</th>
                  <th className="px-4 py-3 font-medium">最后一次来</th>
                </tr>
              </thead>
              <tbody>
                {a.users.map((u) => {
                  const tone: BandTone = u.step >= 5 ? "success" : u.step >= 3 ? "warning" : "danger";
                  return (
                    <tr key={u.uid} className="t-body-sm border-t border-black/[0.05] ink-2 dark:border-white/[0.08]">
                      <td className="px-4 py-2.5 font-mono text-xs ink-1">{u.uid}</td>
                      <td className="px-4 py-2.5"><StatusBadge tone={tone} label={FUNNEL_STEP_LABELS[u.step] || "—"} /></td>
                      <td className="t-caption px-4 py-2.5">
                        {u.industries.length ? u.industries.join("、") : "未填"}
                        {u.stage ? `· ${u.stage}` : ""}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{u.activeDays}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{u.events}</td>
                      <td className="t-caption px-4 py-2.5 tabular-nums">{u.signupDate}</td>
                      <td className="t-caption px-4 py-2.5 tabular-nums">{u.lastActive || "从没来过"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      </section>
    </div>
  );
}

// 页面路径 → 人话。看板上不该出现 /today 这种给程序看的字符串。
const PAGE_LABELS: Record<string, string> = {
  "/": "落地页",
  "/today": "今日推荐",
  "/jobs": "岗位库",
  "/campus": "校招专区",
  "/path": "职业路径",
  "/saved": "值得投",
  "/applied": "已投递",
  "/preferences": "求职目标",
  "/me": "个人主页",
  "/login": "登录页",
  "/sources": "招聘源管理",
  "/admin/health": "运营看板",
  "/admin/insights": "洞察管理",
  other: "其它页面",
};
