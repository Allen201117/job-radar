export function extractExperience(text?: string | null): string {
  if (!text) return "未知";
  const t = text.replace(/\s+/g, "");
  if (/应届|无经验要求|经验不限|不限经验|noexperience|entrylevel/i.test(t)) return "应届/不限";
  let m = t.match(/(\d+)[-~至到](\d+)年/) || t.match(/(\d+)年(?:以上)?(?:工作)?经验/);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  // 英文：3-5 years / 5+ years / 3 years experience（空格已去除）
  m = t.match(/(\d+)[-~to]+(\d+)years?/i) || t.match(/(\d+)\+?years?(?:ofexperience)?/i);
  if (m) return m[2] ? `${m[1]}-${m[2]}年` : `${m[1]}年+`;
  return "未知";
}

export function extractEducation(text?: string | null): string {
  if (!text) return "未知";
  if (/博士|ph\.?d|doctora/i.test(text)) return "博士";
  if (/硕士|研究生|master/i.test(text)) return "硕士";
  if (/本科|学士|bachelor|undergrad/i.test(text)) return "本科";
  if (/大专|专科/.test(text)) return "大专";
  if (/学历不限|不限学历/.test(text)) return "不限";
  return "未知";
}

// ⛔ 正文里的「截止 / 截至 + 日期」多数不是投递截止日，判不出的一律不抽（2026-10-10 立）。
// 与爬虫端 crawler/normalizer.py 的 extract_deadline 同口径，依据与计数写在那边；
// 两端共读 tests/fixtures/deadline-text-cases.json，改一边必须同改另一边。
// 「长期有效」只认招聘声明本身：中文两个词要看前后文（「建立长期有效合作关系」不是），rolling basis 同一句要有
// 招聘类词。逐条镜像 Python 的 _declares_open_ended；不用后行断言，老版 Safari 解析到它会让整个文件报错。
const OPEN_ENDED_CN_SRC = "长期(?:有效|招聘)";
const OPEN_ENDED_CN_TAIL = /^[，,、；; ]{0,2}(?:招满即止|招满为止|欢迎(?:随时)?(?:投递|应聘|报名)|随时投递)/;
const OPEN_ENDED_CN_SUBJECT = /(?:岗位|职位|招聘(?:信息|公告|启事|需求)?)(?:为|是|属|系|均为|[：:])? ?$/;
const OPEN_ENDED_CN_END = /^中?(?:$|[ ，,。.；;！!、）)】\]])/;
const OPEN_ENDED_CN_LABEL =
  /(?:截止日期|截止时间|(?:招聘|岗位|职位)有效期|招聘期限|招聘时间|招聘周期|报名时间|投递时间|申请时间)(?:为|是|[：:】\]])? ?$/;
// 括号前是证件 / 合同：「持有教师资格证（长期有效）」说的是证，不是岗位。
const OPEN_ENDED_CN_NOT_POSTING = /(?:证|证书|证件|执照|驾照|护照|签证|合同|协议|资质|资格)$/;
const OPEN_ENDED_EN_SRC = "until filled|rolling (?:basis|applications?|admissions?)";
// hire / hiring 才是招聘动作；hires / hired 多是「新员工」（New hires start on a rolling basis 说的是入职）。
const HIRING_EN =
  /applicat|appl(?:y|ies|ied|ying)\b|resumes?\b|candidates?\b|recruit|\bhir(?:e|ing)\b|interview|admission/i;
const EN_SENTENCE_END = ".!?;。；！？";

/** 命中处所在的那一句：往前 80 字、往后 40 字，各自到最近的句末标点为止。 */
function sameSentence(base: string, start: number, end: number): string {
  let before = base.slice(Math.max(0, start - 80), start);
  let cut = -1;
  for (const ch of EN_SENTENCE_END) cut = Math.max(cut, before.lastIndexOf(ch));
  before = before.slice(cut + 1);
  let after = base.slice(end, end + 40);
  let stop = after.length;
  for (const ch of EN_SENTENCE_END) {
    const i = after.indexOf(ch);
    if (i >= 0) stop = Math.min(stop, i);
  }
  after = after.slice(0, stop);
  return `${before} ${after}`;
}

/** 正文是不是在声明「这个岗长期招聘 / 招满为止」，而不是碰巧用了这几个词。 */
function declaresOpenEnded(base: string): boolean {
  const cn = new RegExp(OPEN_ENDED_CN_SRC, "g");
  for (let m = cn.exec(base); m; m = cn.exec(base)) {
    const end = m.index + m[0].length;
    const before = base.slice(Math.max(0, m.index - 8), m.index);
    const after = base.slice(end, end + 10);
    if (before.endsWith("中")) continue; // 中长期招聘规划
    // 长期招聘岗位）——后面还接着「的简历筛选」就是招聘岗的工作内容
    if ((after.startsWith("岗位") || after.startsWith("职位")) && OPEN_ENDED_CN_END.test(after.slice(2))) return true;
    const lead = before.replace(/ +$/, "");
    const opener = lead.slice(-1);
    const closer = after.replace(/^ +/, "").slice(0, 1);
    if (
      opener &&
      "（(【[".includes(opener) &&
      closer &&
      "）)】]".includes(closer) &&
      !OPEN_ENDED_CN_NOT_POSTING.test(lead.slice(0, -1))
    )
      return true; // （长期有效）
    if (OPEN_ENDED_CN_TAIL.test(after)) return true;
    if (OPEN_ENDED_CN_SUBJECT.test(before) && OPEN_ENDED_CN_END.test(after)) return true;
    if (OPEN_ENDED_CN_LABEL.test(before)) return true;
  }
  const en = new RegExp(OPEN_ENDED_EN_SRC, "gi");
  for (let m = en.exec(base); m; m = en.exec(base)) {
    if (!m[0].toLowerCase().endsWith("basis")) return true; // until filled / rolling applications / rolling admissions
    if (HIRING_EN.test(sameSentence(base, m.index, m.index + m[0].length))) return true;
  }
  return false;
}

const DEADLINE_CANDIDATE = /(截止|截至|deadline)([^0-9]{0,8})(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/gi;
// 日期前（同一句、往前 14 个字）出现这些词 → 它算的是年龄 / 工龄的时点，不是投递窗口。
const DEADLINE_QUALIFY = /计算|有效期|年龄|周岁|学历|学位|工作经[历验]|工作年限|工龄|服务期|户籍|缴费|资格审查|毕业|出生/;
const DEADLINE_APPLY = /报名|投递|申请|应聘|网申|简历|招聘|招募/;
const DEADLINE_LOOKBACK = 14;
const SENTENCE_BREAK = /[。；;！!？?\n]/;

export function extractDeadline(text?: string | null): string {
  if (!text) return "未知";
  // 与 Python 的 _strip_html 同一道预处理（去标签、空白折成一个空格），两端看到的是同一段文字。
  const base = text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  if (!base) return "未知";
  if (declaresOpenEnded(base)) return "长期有效";
  for (const m of base.matchAll(DEADLINE_CANDIDATE)) {
    const start = m.index ?? 0;
    const before = base.slice(Math.max(0, start - DEADLINE_LOOKBACK), start).split(SENTENCE_BREAK).pop() ?? "";
    if (DEADLINE_QUALIFY.test(before)) continue;
    // 「截止 / 截至」必须带报名类前缀，或紧跟「日期 / 时间」；deadline 这个词本身指向够明确。
    // 「截止投递时间为…」：去掉开头的报名类词后同样要紧跟「时间 / 日期」。
    const applied = DEADLINE_APPLY.exec(m[2]);
    const label = applied && applied.index === 0 ? m[2].slice(applied[0].length) : m[2];
    if (m[1].toLowerCase() !== "deadline" && !(DEADLINE_APPLY.test(before) || /^(?:日期|时间)/.test(label))) continue;
    const [y, mo, d] = [Number(m[3]), Number(m[4]), Number(m[5])];
    // 3000-01-01 这类占位、年份抄错的 → 不是能投的截止日（Date.UTC 还会把 0–99 年当成 19xx）。
    if (y < 2000 || y > 2100) continue;
    const dt = new Date(Date.UTC(y, mo - 1, d));
    // 13 月 / 40 日这类 → 当作没抽到，接着找下一处。
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) continue;
    return dt.toISOString().slice(0, 10);
  }
  return "未知";
}

/**
 * 「截止」标签只放行**近未来的真实日期**，其余一律不显（返回 null）。
 *
 * 为什么需要（2026-09-15 创始人质疑「这截止时间可靠吗」后查实）：`jobs.deadline` 是**自由文本**列，
 * live 全库带值的 10 万个 active 岗里塞着大量占位/垃圾——「长期有效」45,229 个、「3000-01-01」15,066 个、
 * 「2079-11-30」「2030-12-31」这类远未来占位，还有约 1,248 个**已过期却仍 active**。此前卡面直接把原文
 * 塞进「截止 X」标签 → 会渲染出「截止 3000-01-01」「截止 长期有效」「截止 <已过去的日期>」这种不可信内容。
 * 这里与公司级的 `lib/recruitment-cycle.cleanCampusDeadlineMs` 同口径（那条给公司卡、这条给单岗展示）：
 *   · 必须是 YYYY-MM-DD（容忍带时间后缀，如 "2027-08-31 23:59:59"）；
 *   · 落在 [今天, 今天+550 天] 内——滤掉已过期 + 远未来占位。
 * 命中即返回归一后的 YYYY-MM-DD；否则 null（「长期有效」等非日期一律不作为「截止日期」展示）。
 */
export function cleanDeadlineText(raw?: string | null, now: Date = new Date()): string | null {
  const t = raw?.trim();
  if (!t) return null;
  const m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const iso = `${m[1]}-${m[2]}-${m[3]}`;
  const ms = Date.parse(iso + "T00:00:00Z");
  if (Number.isNaN(ms)) return null;
  const nowMs = now.getTime();
  if (ms < nowMs - 24 * 3600 * 1000) return null; // 已过期（留一天缓冲，避开时区/边界）
  if (ms > nowMs + 550 * 24 * 3600 * 1000) return null; // 远未来占位（3000-01-01 / 2079… ）
  return iso;
}

const MISSING_DISPLAY_VALUES = new Set([
  "未知",
  "官网未披露",
  "未披露",
  "暂未披露",
  "暂无",
  "无",
  "n/a",
  "na",
  "null",
  "undefined",
  "-",
  "--",
]);

export function jobFieldDisplayValue(value?: string | null): string | null {
  const text = value?.trim();
  if (!text) return null;
  if (MISSING_DISPLAY_VALUES.has(text.toLowerCase())) return null;
  return text;
}

export function hasJobFieldValue(value?: string | null): boolean {
  return jobFieldDisplayValue(value) !== null;
}
