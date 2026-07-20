// PostgREST「拉全表」查询的分页助手。
//
// ⚠️ 为什么必须存在：PostgREST 单次 select 默认最多返回 1000 行，超出部分被**静默**丢弃
// （不报错、不标记）。sources 已越过 1000（2026-07-20 实测 1121 行 / enabled 1079），
// 任何「拉全表」或「拉全部 enabled」的查询不分页拿到的就是**残缺**集合 → 尾部的源被误判
// 「不存在 / 未接入」→ 覆盖率虚低、刷新选不中、adapter 映射缺条目、管理页少显示。
//
// ⚠️ 分页必须带**稳定排序键**（id）：跨请求翻页时 Postgres 不保证无 ORDER BY 的行序一致，
// 否则可能重复取到同一行、同时漏掉另一行 —— 那比截断更隐蔽（总数看着对，内容却错）。
//
// 同源实现：crawler/auto_discover.py::existing_source_keys。

/** PostgREST 单次 select 的默认行数上限。 */
export const PAGE_SIZE = 1000;

type PageResult<T> = { data: T[] | null; error: { message: string } | null };

/** 只依赖 `.from(table).select(cols)` 链式接口，好让 service client / 浏览器 anon client / 测试假客户端都能传进来。 */
export type PaginatableClient = { from: (table: string) => any };

/**
 * 反复调用 `page(from, to)` 直到某页不满 `step`，把各页拼成全量数组。
 * 任一页出错直接 throw（调用方按自己的容错策略 try/catch）。
 */
export async function fetchAllPages<T>(
  page: (from: number, to: number) => PromiseLike<PageResult<T>>,
  step: number = PAGE_SIZE,
): Promise<T[]> {
  const all: T[] = [];
  for (let offset = 0; ; offset += step) {
    const { data, error } = await page(offset, offset + step - 1);
    if (error) throw new Error(error.message);
    const rows = (data || []) as T[];
    all.push(...rows);
    if (rows.length < step) break;
  }
  return all;
}

/**
 * 分页拉全量 sources（默认含 disabled；`enabledOnly` 只取 enabled）。
 * 排序键固定为 id —— 稳定且必有；调用方若要别的展示顺序，自己在内存里排。
 */
export async function fetchAllSources<T = Record<string, any>>(
  client: PaginatableClient,
  columns: string,
  options: { enabledOnly?: boolean; step?: number } = {},
): Promise<T[]> {
  const step = options.step ?? PAGE_SIZE;
  return fetchAllPages<T>((from, to) => {
    let query = client.from("sources").select(columns);
    if (options.enabledOnly) query = query.eq("enabled", true);
    return query.order("id", { ascending: true }).range(from, to);
  }, step);
}
