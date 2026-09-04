import { currentGradClass } from "@/lib/grad-class";

/**
 * 往届校招/实习岗不进默认结果 —— SQL where 片段，`/jobs` 检索与 `/today` 召回共用同一份。
 *
 * 与 `/campus` 专区完全同一条口径：`lib/jobs-store/read.ts` 的 `getCampusZone` 早就用
 * `isCurrentSeasonGradClass` 把往届岗移出默认列表了，这里把同一道门补到另外两个入口
 * （2026-09-04 实测它俩的检索/打分路径里 `grad_class` 一次都没出现过 = 完全没设防）。
 *
 * 为什么要有：live 实测库里 4,178 个 active 校招/实习岗标着 2026 届及更早，云从科技那批
 * 正文里明写「发布时间：2020-08-21」、2021 届，对方页面自己没撤，我们照单全收。
 * 默认排序（first_seen_at desc）下它们占校招流前 50 的 2.0%、前 1000 的 6.6%——
 * **校招用户投一个往届岗就白费一轮**，是正确性问题，不是排序偏好问题。
 *
 * ⚠️ **只作用于校招/实习，社招绝不能碰**：实测另有 632 个**社招**岗正文里提到老届别
 *    （「2021 届及以后均可」这类），它们完全在招，一并滤掉就是误杀 632 个真岗。
 * ⚠️ `grad_class is null` 一律放行 —— 留白 ≠ 隐藏。全库 73% 的校招/实习岗没标届别，
 *    这条与 `lib/grad-class.js` 的注释、`campus-facets.facetMatches`、`jobIndustryAllowed`
 *    是同一条一以贯之的原则：信息不足放行，只挡有明确反向证据的。
 * ⚠️ 刻意下推到 SQL 而不是在 JS 里过滤：候选与 `exactTotalWhenCapped` 的 count 用的是
 *    **同一份 conds/params**，下推后两边仍然一致 → 计数照常能给确定数字；改成 JS 过滤会让
 *    自检门③（rankedLength === scanned - hiddenScanned）失败，把所有校招搜索的计数打成「N+」。
 * ⚠️ 调用方必须保证 `params` 此刻只含 where 参数（排序/分页参数要走各自的副本），
 *    否则 count 查询会带上用不到的绑定参数、PG 直接报错。
 */
export function appendCurrentSeasonWhere(conds: string[], params: unknown[]): void {
  params.push(currentGradClass());
  conds.push(
    `not (recruitment_category in ('校招','实习') and grad_class is not null and grad_class < $${params.length})`,
  );
}
