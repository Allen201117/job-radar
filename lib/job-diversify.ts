// /jobs 结果分散:头部滑窗贪心稳定重排,单公司在任一 window 内 ≤ cap,超出下压。
// 纯重排:同长、同多集、确定性 → 不影响 total/分页。只处理头部,perf 与候选总量无关。

type Diversifiable = { company?: string | null; id?: string; jd_url?: string | null };

const companyKey = (j: Diversifiable): string =>
  (j.company || `id:${j.id ?? j.jd_url ?? ""}`).trim().toLowerCase();

export function spreadByCompany<T extends Diversifiable>(
  ranked: T[],
  opts: { cap?: number; window?: number; headOnly?: number } = {},
): T[] {
  const cap = opts.cap ?? 3;
  const window = opts.window ?? 10;
  const headOnly = opts.headOnly ?? 200;
  if (ranked.length <= window) return ranked;

  const head = ranked.slice(0, headOnly);
  const tail = ranked.slice(headOnly);

  const out: T[] = [];
  const deferred: T[] = []; // 被下压的,保持相对 rank 顺序
  // 当前窗口(out 末尾 window 条)内各公司计数;增量维护,O(1) 每步。
  const winCount = new Map<string, number>();
  const bump = (co: string, d: number) => {
    const n = (winCount.get(co) ?? 0) + d;
    if (n <= 0) winCount.delete(co); else winCount.set(co, n);
  };
  const emit = (item: T) => {
    out.push(item);
    bump(companyKey(item), 1);
    if (out.length > window) bump(companyKey(out[out.length - 1 - window]), -1);
  };

  let i = 0;
  while (out.length < head.length) {
    // 1) 优先从 deferred 里找一个当前窗口未超 cap 的(rank 顺序,取最靠前那个)
    let placed = -1;
    for (let d = 0; d < deferred.length; d++) {
      if ((winCount.get(companyKey(deferred[d])) ?? 0) < cap) { placed = d; break; }
    }
    if (placed >= 0) { emit(deferred.splice(placed, 1)[0]); continue; }
    // 2) 否则取 head 下一个:未超 cap 就放,超了就压入 deferred
    if (i < head.length) {
      const next = head[i++];
      if ((winCount.get(companyKey(next)) ?? 0) < cap) emit(next);
      else deferred.push(next);
      continue;
    }
    // 3) head 取尽且 deferred 全超 cap → 只能违反 cap,按 rank 顺序放(避免死循环)
    emit(deferred.shift() as T);
  }
  return out.concat(tail);
}
