import type { InsightDimension } from "./types";

export const FIRST_PARTY_MIN_COUNT = 5;
export const FIRST_PARTY_CONTENT_MAX = 200;

export const FIRST_PARTY_DIMENSIONS = [
  "culture",
  "compensation_intensity",
  "path",
  "hiring",
] as const;

export type FirstPartyDimension = (typeof FIRST_PARTY_DIMENSIONS)[number];

export const FIRST_PARTY_TOPICS = {
  internship: "实习体验",
  onboarding: "入职体验",
  bonus: "年终奖",
  interview: "面试难度",
  promotion: "晋升",
  culture: "文化",
} as const;

export type FirstPartyTopic = keyof typeof FIRST_PARTY_TOPICS;

const TOPIC_ALIASES: Record<string, FirstPartyTopic> = {
  实习体验: "internship",
  入职体验: "onboarding",
  年终奖: "bonus",
  面试难度: "interview",
  晋升: "promotion",
  文化: "culture",
};

export const TOPIC_DEFAULT_DIMENSION: Record<FirstPartyTopic, FirstPartyDimension> = {
  internship: "path",
  onboarding: "path",
  bonus: "compensation_intensity",
  interview: "hiring",
  promotion: "path",
  culture: "culture",
};

export type SubmissionValidationError =
  | "missing_company"
  | "invalid_dimension"
  | "invalid_topic"
  | "invalid_rating"
  | "content_required"
  | "content_too_long"
  | "pii_detected"
  | "consent_required";

export interface NormalizedInsightSubmission {
  company: string;
  dimension: FirstPartyDimension;
  topic: FirstPartyTopic;
  topic_label: string;
  rating: number | null;
  content: string;
  payload: Record<string, unknown>;
  consent: true;
}

export type SubmissionValidationResult =
  | { ok: true; value: NormalizedInsightSubmission }
  | { ok: false; error: SubmissionValidationError };

export interface InsightSubmissionRow {
  id: string;
  company: string;
  company_id: string | null;
  user_id?: string;
  dimension: FirstPartyDimension | InsightDimension | string;
  topic: FirstPartyTopic | string;
  rating: number | null;
  content: string;
  payload: Record<string, unknown> | null;
  status: string;
  moderation?: Record<string, unknown>;
  employment_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface FirstPartyInsightItem {
  id: string;
  company: string;
  company_id: string | null;
  dimension: string;
  topic: FirstPartyTopic | string;
  topic_label: string;
  rating: number | null;
  content: string;
  payload: Record<string, unknown>;
  employment_verified: boolean;
  created_month: string | null;
}

export interface FirstPartyAggregate {
  visible: boolean;
  summary: {
    count: number;
    average_rating: number | null;
  };
  items: FirstPartyInsightItem[];
}

// 常见中文姓氏，用于识别「姓 + 称谓」这类指认具体个人的写法（张总 / 王姐 / 李经理）。
// 注意：不做「角色词 + 任意汉字」的宽匹配——那会把「老板画饼」「同事很好」这类正常吐槽
// 全部误判为 PII，等于把本功能想收集的内容全拦掉。称谓门精确度高、几乎不误伤正常语句。
const CN_SURNAMES =
  "王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文";

const PII_PATTERNS: RegExp[] = [
  /(?:\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}/,
  /\b\d{17}[\dXx]\b/,
  /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/,
  /(^|\s)@[A-Za-z0-9_\-\u4e00-\u9fa5]{2,}/,
  new RegExp(`[${CN_SURNAMES}](?:总监|经理|主管|老板|老师|总|姐|哥)`), // 姓 + 称谓：张总 / 王姐 / 李经理
  /(?:张三|李四|王五|赵六)/,
];

function normalizeTopic(input: unknown): FirstPartyTopic | null {
  const value = String(input || "").trim();
  if (!value) return null;
  if (Object.prototype.hasOwnProperty.call(FIRST_PARTY_TOPICS, value)) {
    return value as FirstPartyTopic;
  }
  return TOPIC_ALIASES[value] || null;
}

function normalizeDimension(input: unknown, topic: FirstPartyTopic | null): FirstPartyDimension | null {
  const value = String(input || "").trim();
  if (!value && topic) return TOPIC_DEFAULT_DIMENSION[topic];
  return FIRST_PARTY_DIMENSIONS.includes(value as FirstPartyDimension)
    ? (value as FirstPartyDimension)
    : null;
}

function normalizeRating(input: unknown): number | null {
  if (input === "" || input == null) return null;
  const value = Number(input);
  if (!Number.isInteger(value) || value < 1 || value > 5) return Number.NaN;
  return value;
}

export function containsDirectIdentifier(content: string): boolean {
  return PII_PATTERNS.some((pattern) => pattern.test(content || ""));
}

export function validateSubmission(body: Record<string, unknown>): SubmissionValidationResult {
  const company = String(body.company || "").trim();
  if (!company) return { ok: false, error: "missing_company" };

  const topic = normalizeTopic(body.topic);
  if (!topic) return { ok: false, error: "invalid_topic" };

  const dimension = normalizeDimension(body.dimension, topic);
  if (!dimension) return { ok: false, error: "invalid_dimension" };

  const rating = normalizeRating(body.rating);
  if (Number.isNaN(rating)) return { ok: false, error: "invalid_rating" };

  const content = String(body.content || "").trim().replace(/\s+/g, " ");
  if (!content) return { ok: false, error: "content_required" };
  if (content.length > FIRST_PARTY_CONTENT_MAX) {
    return { ok: false, error: "content_too_long" };
  }
  if (containsDirectIdentifier(content)) {
    return { ok: false, error: "pii_detected" };
  }
  if (body.consent !== true) {
    return { ok: false, error: "consent_required" };
  }

  const payload =
    body.payload && typeof body.payload === "object" && !Array.isArray(body.payload)
      ? (body.payload as Record<string, unknown>)
      : {};

  return {
    ok: true,
    value: {
      company,
      dimension,
      topic,
      topic_label: FIRST_PARTY_TOPICS[topic],
      rating,
      content,
      payload,
      consent: true,
    },
  };
}

function monthFromIso(value: string): string | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString().slice(0, 7);
}

function topicLabel(topic: string): string {
  const normalized = normalizeTopic(topic);
  return normalized ? FIRST_PARTY_TOPICS[normalized] : topic;
}

export function aggregateFirstParty(
  rows: InsightSubmissionRow[],
  options: { minCount?: number } = {},
): FirstPartyAggregate {
  const minCount = Math.max(1, options.minCount ?? FIRST_PARTY_MIN_COUNT);
  const approved = (rows || [])
    .filter((row) => row.status === "approved")
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  const ratings = approved
    .map((row) => row.rating)
    .filter((rating): rating is number => typeof rating === "number");
  const average =
    ratings.length > 0
      ? Number((ratings.reduce((sum, rating) => sum + rating, 0) / ratings.length).toFixed(1))
      : null;

  if (approved.length < minCount) {
    return {
      visible: false,
      summary: { count: approved.length, average_rating: average },
      items: [],
    };
  }

  return {
    visible: true,
    summary: { count: approved.length, average_rating: average },
    items: approved.map((row) => ({
      id: row.id,
      company: row.company,
      company_id: row.company_id || null,
      dimension: row.dimension,
      topic: row.topic,
      topic_label: topicLabel(row.topic),
      rating: row.rating,
      content: row.content,
      payload: row.payload || {},
      employment_verified: row.employment_verified === true,
      created_month: monthFromIso(row.created_at),
    })),
  };
}

export function isFirstPartyLocked(userContributionCount: number): boolean {
  return userContributionCount <= 0;
}
