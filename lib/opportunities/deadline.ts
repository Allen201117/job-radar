// 截止日期解析（04 spec §6.1）：把岗位 deadline 文本解析为明确日期，供 DEADLINE_SOON 信号判窗。
// 纯函数，可测；解析不出明确单一日期一律返回 null（宁缺毋滥，不瞎报快截止）。
//
// 解析：YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYY年M月D日（high）；M月D日（无年，按 now 推年，medium）。
// 不解析：长期有效 / 招满即止 / 尽快 / 以及含多个不同日期、无法判断的文本。

const VAGUE = /长期有效|长期招聘|招满即止|招满为止|尽快|滚动招聘|不限|随时|长期/;

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

// 校验 y-m-d 是真实日历日（拒 2 月 30 日等）。返回归一 ISO date 或 null。
function isoDate(y: number, m: number, d: number): string | null {
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return `${y}-${pad2(m)}-${pad2(d)}`;
}

export function parseDeadline(
  raw: string | null | undefined,
  now: Date
): { date: string; confidence: "high" | "medium" } | null {
  if (!raw) return null;
  const text = String(raw).trim();
  if (!text || VAGUE.test(text)) return null;

  // 收集所有可识别的日期（带年 / 不带年）。
  const found: { date: string; confidence: "high" | "medium" }[] = [];

  // 带年：2026-07-01 / 2026/7/1 / 2026.7.1 / 2026年7月1日
  const full = /(\d{4})[\-/.年](\d{1,2})[\-/.月](\d{1,2})日?/g;
  let m: RegExpExecArray | null;
  const fullSpans: Array<[number, number]> = [];
  while ((m = full.exec(text)) !== null) {
    const iso = isoDate(Number(m[1]), Number(m[2]), Number(m[3]));
    if (iso) found.push({ date: iso, confidence: "high" });
    fullSpans.push([m.index, m.index + m[0].length]);
  }

  // 不带年：M月D日（排除已被「带年」匹配覆盖的片段）
  const md = /(\d{1,2})月(\d{1,2})日/g;
  while ((m = md.exec(text)) !== null) {
    const start = m.index;
    const covered = fullSpans.some(([a, b]) => start >= a && start < b);
    if (covered) continue;
    const mm = Number(m[1]);
    const dd = Number(m[2]);
    let y = now.getUTCFullYear();
    let iso = isoDate(y, mm, dd);
    if (!iso) continue;
    // 已过去超 30 天 → 推下一年（medium）
    const cand = new Date(`${iso}T00:00:00Z`).getTime();
    if (cand < now.getTime() - 30 * 86_400_000) {
      y += 1;
      iso = isoDate(y, mm, dd);
      if (!iso) continue;
    }
    found.push({ date: iso, confidence: "medium" });
  }

  if (found.length === 0) return null;

  // 多个不同日期 → 无法判断，不触发（宁缺毋滥）。
  const uniqueDates = new Set(found.map((f) => f.date));
  if (uniqueDates.size > 1) return null;

  return found[0];
}
