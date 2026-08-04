// 届别（2027 届 / 2026 届）抽取与当季判定 —— 纯函数，无网络无 DB。
//
// 为什么要有届别：秋招正式批开闸后，库里会同时躺着当季（2027 届）新岗与上一届（2026 届）
// 没下架的残岗。校招用户看到往届岗会白投一轮，这是实打实的伤害。
//
// ⚠️ 核心原则：**只认硬信号，抽不出就留白，绝不靠时间或上下文猜。**
// 曾考虑「用入库时间兜底」（8 月抓到的校招岗大概率是 2027 届）——已明确否决：
//   · 8 月同样会抓到 2026 届的收尾岗，猜错就是把往届岗标成当季，比不标更伤；
//   · first_seen_at 本身在 2026-06-15 库重建时被污染过，不是可靠的时间基准。
// 留白 ≠ 隐藏：抽不出届别的岗照常展示（绝大多数岗都抽不出，隐藏它们等于清空专区）。
//
// 与 crawler/grad_class.py 是同口径的两份实现（写入端在 Python、展示端在 JS）。
// 改规则必须两边同改 + 两边测试同步，同 canonicalize_jd_url 的约定。

// 届别年份的合理窗口：太老/太远的四位数一律不认（防把「1998」「3027」当届别）。
const MIN_GRAD_YEAR = 2015;
const MAX_GRAD_YEAR = 2100;

// 硬信号：年份必须**紧贴届别语境词**才算数。
// 「2027年12月前入职」「2027 年度预算」这类光有年份没有届别语境的，一律不认。
const PATTERNS = [
  // 2027届 / 2027 届
  /(20\d{2})\s*届/g,
  // 27届（两位年份 + 届）
  /(?:^|[^\d])(\d{2})\s*届/g,
  // 2027校招 / 2027秋招 / 2027春招 / 2027校园招聘 / 2027年校园招聘
  /(20\d{2})\s*年?\s*(?:校招|秋招|春招|校园招聘|校园招募)/g,
  // Class of 2027
  /class\s+of\s+(20\d{2})/gi,
  // 2027 Graduate / 2027 Campus
  /(20\d{2})\s+(?:graduate|campus)/gi,
];

function _normalizeYear(raw) {
  const n = parseInt(raw, 10);
  if (Number.isNaN(n)) return null;
  // 两位年份补全：27 → 2027
  const year = n < 100 ? 2000 + n : n;
  if (year < MIN_GRAD_YEAR || year > MAX_GRAD_YEAR) return null;
  return year;
}

/**
 * 从岗位标题/正文抽届别。命中多个不同届别时取**最大**——招聘文案常写
 * 「2026/2027 届均可」，取更晚那届更贴合当季投递人群。
 * 无硬信号返回 null。
 */
function extractGradClass(job) {
  if (!job) return null;
  const text = [job.title, job.job_type, job.summary].filter(Boolean).join(" ");
  if (!text) return null;

  let best = null;
  for (const re of PATTERNS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      const year = _normalizeYear(m[1]);
      if (year !== null && (best === null || year > best)) best = year;
    }
  }
  return best;
}

/**
 * 当季届别。与 lib/recruitment-cycle.ts 的选季口径一致：
 * 5-12 月是秋招季，招的是**次年**毕业那届；1-4 月是春招补录，补的还是当年毕业那届。
 */
function currentGradClass(now = new Date()) {
  const d = now instanceof Date ? now : new Date(now);
  const month = d.getUTCMonth() + 1;
  const year = d.getUTCFullYear();
  return month >= 5 ? year + 1 : year;
}

/**
 * 该届别是否该进校招专区默认列表。
 * 当季放行；**未知（null）放行**（留白不等于隐藏）；比当季更晚的届别也放行（提前批常见）；
 * 只有明确早于当季的往届岗被移出默认列表。
 */
function isCurrentSeasonGradClass(gradClass, now = new Date()) {
  if (gradClass === null || gradClass === undefined) return true;
  return gradClass >= currentGradClass(now);
}

module.exports = { extractGradClass, currentGradClass, isCurrentSeasonGradClass };
