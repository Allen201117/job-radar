// 批量门店发布源的**检索层去重**：同一个岗位在 N 家门店各发一条，只有店名/人名之差。
//
// 治的病（2026-09-04 live 实测）：我爱我家 8,003 个 active 岗，标题长这样——
//   「何奇-清澄名苑旗舰全能A店(J679323)」「杭州-赵乐怡-奥特莱斯店3组(J711263)」
// 店名 + HR 真人姓名，**连职位名都没有**。可测后果：杭州 17.4%、北京 8.3%、山西省 40.7%
// 的在招岗是这一家的门店副本。8,003 行其实只有 489 种正文，全是房产经纪人。
//
// ⚠️ 为什么是**检索层**而不是存量折叠（2026-09-04 创始人拍板前实测否掉了后者）：
//   · 按标题折叠没用——店名和人名就在标题里，`collapse_bulk_duplicates` 的归一（去括号/去数字）
//     只能把 8,003 压到 6,888（−14%），远不是任务卡预估的 ~4,600。
//   · 按正文折叠有用（→711 行，−91%），但**一次性折叠次日就白做**：这源每天都在抓
//     （8,003 行今天全被抓到），`RepetitionBrake` 按设计刹不住它（归一标题重复率 0.141，
//     远低于 0.90 阈值——它在 base.py 的注释里被明确列为「正常源」），而 `removed` 行
//     下一轮 upsert 会自动复活（jobs_db 的 REAPPEARED）。
//   检索层去重不改 status，所以不会被重抓回来，也不影响探活/台账/北极星口径。
//
// ⚠️⚠️ **公司必须显式点名，绝不自动识别**——这是本文件最重要的一条。
// 「同公司 + 同城 + 同正文」这个判据单独用会**误杀真岗**，2026-09-04 实测差点踩进去：
//   · 美光 Micron：1,255 行共用同一段正文，但那是**公司简介样板**
//     （"Our vision is to transform how the world uses information…"），
//     底下是 **727 个真正不同的岗**（SAP ERP Analyst / Electrical Failure Analysis Engineer /
//     Lean Manufacturing Engineer…）。按正文合并 = 一次性抹掉 727 个真实机会。
//   · Visa 1,534 行 / 647 个不同岗、Salesforce、强生、Applied Materials 全是同一种形态。
//   我爱我家能安全折叠，是因为它的**正文才是角色载体**（标题是店名人名）；
//   美光正好相反（标题是角色，正文是样板）。两者用同一个判据结果相反——
//   所以判据只能用来**出候选给人看**，不能用来自动决定折叠谁。
//   新增公司前必须先跑 docs 里那条体检 SQL 逐个人工核验（见 README of this file 上方注释）。
//
// 与 `crawler/collapse_bulk_duplicates.py` 的分工：那个清**存量**（对刹得住的星巴克/来伊份/喜茶
// 有效，因为刹车让它们不再被翻到）；这里治**每天都在重抓、刹不住**的源。

/** 显式点名的批量门店发布公司。子串匹配（库里 company 常带后缀）。
 *  ⚠️ 加公司前必须人工核验「正文是角色载体」——见文件顶部美光的反例。 */
export const BULK_STORE_COMPANIES = ["我爱我家"];

/** 正文短于这个长度就不折叠：太短的正文不是可靠的角色载体，宁可多留几行也不能把不同角色并成一个。
 *  （与 count_valid_active_jobs 的「JD 正文 ≥60 字」同一个数量级，非巧合：短正文本来就不算有效岗。） */
export const MIN_BODY_CHARS = 60;

/** 命中哪家批量门店公司；不是则 null。 */
export function bulkStoreCompanyOf(company: unknown): string | null {
  const c = String(company ?? "").toLowerCase();
  if (!c) return null;
  for (const name of BULK_STORE_COMPANIES) {
    if (c.includes(name.toLowerCase())) return name;
  }
  return null;
}

/**
 * 折叠键：`公司|完整location|归一正文`。命中批量公司且正文够长才有键，否则 null（= 不参与折叠）。
 *
 * ⚠️ 用**完整 location** 而不是解析出的城市：解析城市会把「杭州·余杭区」和「杭州·滨江区」并成一个，
 * 而门店岗恰恰是按区分布的。宁可少归一（多留几行）也不能多归一——与 collapse 脚本同一条取舍。
 */
export function bulkStoreGroupKey(job: any): string | null {
  const owner = bulkStoreCompanyOf(job?.company);
  if (!owner) return null;
  const body = String(job?.summary ?? "").replace(/\s+/g, "");
  if (body.length < MIN_BODY_CHARS) return null;
  return `${owner}|${String(job?.location ?? "")}|${body}`;
}

/** 折叠结果：留下的岗 + 每个被留下的岗代表了多少条（1 = 没折叠）。 */
export type BulkStoreDedupeResult<T> = { jobs: T[]; groupSizeById: Map<string, number> };

/**
 * 对**已排好序**的列表折叠：同一个键只留排在最前面的那条（= 打分最高的那条），
 * 并记下这一组一共有多少条，供 UI 诚实标注「另有 N 家门店在招」。
 *
 * ⚠️ 必须在排序**之后**调用：留下的那条是用户最该看到的那条。
 * ⚠️ 调用方把 `jobs.length` 当 `total` 用时会天然缩小 → `exactTotalWhenCapped` 的
 *    自检门③（rankedLength === scanned - hiddenScanned）失败 → 退回「N+」。
 *    这是**对的**：折叠之后 SQL 那个 count 已经不等于用户看到的条数了，给确定数字才是撒谎。
 */
export function dedupeBulkStoreJobs<T extends { id?: unknown }>(jobs: T[]): BulkStoreDedupeResult<T> {
  const kept: T[] = [];
  const keptIdByKey = new Map<string, string>();
  const groupSizeById = new Map<string, number>();
  for (const job of jobs || []) {
    const key = bulkStoreGroupKey(job);
    if (key === null) {
      kept.push(job);
      continue;
    }
    const existingId = keptIdByKey.get(key);
    if (existingId !== undefined) {
      groupSizeById.set(existingId, (groupSizeById.get(existingId) || 1) + 1);
      continue;
    }
    const id = String((job as any)?.id ?? "");
    keptIdByKey.set(key, id);
    groupSizeById.set(id, 1);
    kept.push(job);
  }
  return { jobs: kept, groupSizeById };
}

/** 把折叠组大小写回岗位对象（`__storeCount`，>1 才写），供卡片渲染「另有 N 家门店」。 */
export function annotateBulkStoreCounts<T extends { id?: unknown }>(result: BulkStoreDedupeResult<T>): T[] {
  for (const job of result.jobs) {
    const n = result.groupSizeById.get(String((job as any)?.id ?? "")) || 1;
    if (n > 1) (job as any).__storeCount = n;
  }
  return result.jobs;
}

/** 一步到位：折叠 + 标注。检索路径直接用这个。 */
export function collapseBulkStoreJobs<T extends { id?: unknown }>(jobs: T[]): T[] {
  return annotateBulkStoreCounts(dedupeBulkStoreJobs(jobs));
}
