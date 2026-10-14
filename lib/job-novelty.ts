// 判「新岗」的唯一实现（2026-10-12）。新加任何判「新」的读路径都走这里，别再手写「首见 N 天内 = 新」。
//
// 为什么要有它：读侧判「新」此前全认首见时间（first_seen_at = 我们第一次抓到它的时刻）。每接一条新源、
// 每修一次翻页，对方门户上挂了很久的老岗会整批以「新岗」身份进来——拿到岗位库的「近 7 天新增」+10 分、
// 卡片「新发现」徽标、今日推荐的「今天首次发现」与新鲜度分、「目标城市近 7 天新岗」召回层的入场资格。
// 2026-10-12 香港库全量：近 7 天首见的在招岗 26,793 行，带官方发布日的 8,374 行里 2,257 行发布日比首见早 7 天以上；
// 近 24 小时首见、带发布日的 1,311 行里 781 行是这种岗。
//
// 规则：**有官方发布日（posted_at）、且比首见早 STALE_ON_ARRIVAL_DAYS 天以上的岗不算新岗**
// ——进来那天它就已经不在「近 7 天」里了。其余一律照旧按首见算：
//   · 没有发布日 → 照旧（这条规则管不到；Workday / 北森多数门户不给发布日）。
//   · 发布日比首见晚 → 照旧。**只往外排、不往里加**：不少来源的「发布日」其实是最近一次更新
//     （Greenhouse / 网易 / 腾讯 / 小红书 / 快手 / 蚂蚁 / 国聘），对方一刷新它就变新。同日实测首见早于 7 天前、
//     发布日却在近 7 天内的在招岗 5,639 行——「发布日新就算新」会把这批老岗重新算成新岗。
//   · 7 这个数：首见与发布日的间隔是两头分布（隔 0~2 天 5,782 行、3~7 天 87 行、8 天以上 2,257 行），
//     门槛取 3~7 结果几乎一样；取 7 与「近 7 天」同一个数，好解释。
//
// ⚠️ JS 与 SQL 两份判据必须同口径，所以写在同一个文件、共用同一个天数；tests/job-novelty.test.js 钉着
//    （真库逐行对拍是另做的：11,346 行两个方向 0 不一致，见下面那份报告 §4.3）。
// ⚠️ 这里只管「读的时候算不算新」，不改 first_seen_at 的写入口径（召回快照 / 洞察 / 事件表都在用它）。
// ⚠️ 刻意没走这里的三处：lib/jobs-store/read.ts 的「今日新进」（today_new）与两处「近 7 天新」（new_7d）。
//    它们是运营看板 / 必投缺口台账的**入库量**，数的就是「这几天进了多少行」，不是给用户看的「新岗」。
// ⚠️ 已知漏网：对方把老岗的发布日刷新到首见之后，这一行在首见后的 7 天内会重新算新（上限就是那 7 天）。
// 数字与对拍：docs/reviews/2026-10-12-novelty-official-posted-date.md

/** 官方发布日比首见早多少天以上，就算「进来时已经是老岗」。 */
export const STALE_ON_ARRIVAL_DAYS = 7;

/** 卡片「新发现」徽标与「仅新岗位」筛选共用的窗口（首见几天内）。 */
export const NEW_BADGE_DAYS = 3;

const DAY_MS = 86_400_000;

/** 判新只读这两个时间；字段名与 jobs 表一致。 */
export interface NoveltyDates {
  first_seen_at?: string | Date | null;
  posted_at?: string | Date | null;
}

function toMillis(value: string | Date | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const t = value instanceof Date ? value.getTime() : new Date(value).getTime();
  return Number.isFinite(t) ? t : null;
}

function staleByMillis(seen: number | null, posted: number | null): boolean {
  return seen !== null && posted !== null && seen - posted > STALE_ON_ARRIVAL_DAYS * DAY_MS;
}

/** 进来时就已经是老岗：有官方发布日，且比首见早 STALE_ON_ARRIVAL_DAYS 天以上。 */
export function staleOnArrival(job: NoveltyDates): boolean {
  return staleByMillis(toMillis(job.first_seen_at), toMillis(job.posted_at));
}

/** 距首见过了多久（毫秒）。没有首见时间、或进来时就已经是老岗 → null（= 不算新岗）。 */
export function noveltyAgeMs(job: NoveltyDates, nowMs: number): number | null {
  const seen = toMillis(job.first_seen_at);
  if (seen === null || staleByMillis(seen, toMillis(job.posted_at))) return null;
  return nowMs - seen;
}

/** 是不是「近 days 天的新岗」。 */
export function isNewWithinDays(job: NoveltyDates, days: number, nowMs: number = Date.now()): boolean {
  const age = noveltyAgeMs(job, nowMs);
  return age !== null && age <= days * DAY_MS;
}

/**
 * `!staleOnArrival(job)` 的 SQL 版（列名就是 jobs 表的 first_seen_at / posted_at）。
 * 两个 timestamptz 相减得到「天 + 时分秒」的 interval，与 `interval 'N days'` 比较时 1 天 = 24 小时，
 * 和上面 JS 的毫秒差是同一回事。
 * ⚠️ 必须和一个「首见在窗口内」的条件一起用（见 sqlIsNew）：first_seen_at 为 NULL 时它自己是 NULL 不是 true。
 */
export const SQL_NOT_STALE_ON_ARRIVAL =
  `(posted_at is null or first_seen_at - posted_at <= interval '${STALE_ON_ARRIVAL_DAYS} days')`;

/** 给一个「首见在窗口内」的 SQL 条件，返回「是新岗」的完整条件（已带括号，可直接拼进 and / or）。 */
export function sqlIsNew(firstSeenWithin: string): string {
  return `(${firstSeenWithin} and ${SQL_NOT_STALE_ON_ARRIVAL})`;
}
