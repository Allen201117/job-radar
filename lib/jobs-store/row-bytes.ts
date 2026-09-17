// 跨库取数的载荷估算 + 分段账本日志（观测用，纯函数，无 DB）。
//
// 为什么要它：香港 jobs 库的**出口带宽是个位数 Mbps**（2026-09-17 实测 psql 裸拉 8MB 要 42.9s ≈ 1.5Mbit/s），
// 所以「这一跳传了多少字节」是这套系统里最该被常开观测的数字——比耗时更稳定、更能指认病根。
// /jobs 已有 `x-jobs-search-timing`（lib/jobs-store/search.ts 的 logSearchTiming）；
// /today 与 /campus 是**要登录**的页面，外部 curl 不到，只能靠服务端日志，因此这里的日志必须常开。
//
// ⚠️ 这是**估算**不是精确值：按 node-pg 交付给 JS 之后的字符串长度算 UTF-8 近似字节
// （ASCII 1 字节、CJK 3 字节），不含 libpq 的协议头与列描述。用途是量级判断与改前/改后对拍，
// 不是计费。行数多时只抽样前 SAMPLE_ROWS 行再外推（对同构的岗位行足够，且不给热路径添成本）。

const SAMPLE_ROWS = 200;

function valueBytes(v: unknown): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number" || typeof v === "boolean") return 8;
  const s = typeof v === "string" ? v : String(v);
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    n += c < 0x80 ? 1 : c < 0x800 ? 2 : 3;
  }
  return n;
}

/** 这批行交付到函数里大约有多少字节（抽样外推）。 */
export function estimateRowBytes(rows: readonly unknown[] | null | undefined): number {
  const list = rows || [];
  if (!list.length) return 0;
  const sample = Math.min(SAMPLE_ROWS, list.length);
  let bytes = 0;
  for (let i = 0; i < sample; i++) {
    const row = list[i];
    if (!row || typeof row !== "object") continue;
    for (const v of Object.values(row as Record<string, unknown>)) bytes += valueBytes(v);
  }
  return Math.round((bytes / sample) * list.length);
}

export const kb = (bytes: number): number => Math.round(bytes / 1024);

/** 校招看板取数的一行账本（可 grep `[campus-zone]` / `[campus-fresh]`）。 */
export function logCampusTiming(
  tag: string,
  t: { companies: number; rows: number; bytes: number; namesMs: number; fetchMs: number; foldMs: number; extra?: string },
): void {
  console.log(
    `[${tag}] companies=${t.companies} rows=${t.rows} kb=${kb(t.bytes)} ` +
      `names_ms=${Math.round(t.namesMs)} fetch_ms=${Math.round(t.fetchMs)} fold_ms=${Math.round(t.foldMs)}` +
      (t.extra ? ` ${t.extra}` : ""),
  );
}
