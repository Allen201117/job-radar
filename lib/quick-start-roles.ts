// 「一键设目标」可选的岗位方向词 —— UI 渲染与 API 白名单校验**共读这一份**。
//
// 为什么不能让用户随便填、也不能直接用职能桶名（`JOB_FUNCTION_BUCKETS`）：
// 匹配引擎认的是 `CHINA_KEYWORD_GROUPS` 里的词，桶名不在里面。2026-09-06 实测：
//   keywordMatchTier("研发",  "后台开发")     → null   ← 桶名，匹配不上
//   keywordMatchTier("后端",  "后台开发")     → related
//   keywordMatchTier("后端",  "后端开发工程师") → exact
// 拿桶名当目标词写进偏好，用户会得到一个**更空**的看板——比不设目标还糟。
// 所以这里只暴露每个概念组的**首词（规范词）**，它天然被词库扩展、被 FTS 召回覆盖。
//
// ⚠️ 加方向 = 改 `lib/china-keyword-expansion.js` 的词库，不要在这里维护第二份词表。
// 契约测试 tests/quick-start-roles.test.js 会断言这里的每个词都真能匹配、且能被 API 白名单接受。
import {
  CHINA_KEYWORD_GROUPS,
  JOB_FUNCTION_BUCKETS,
  KEYWORD_GROUP_FUNCTIONS,
} from "./china-keyword-expansion";

export interface QuickStartRole {
  /** 写进 user_preferences.target_roles 的值（必须是词库里的规范词）。 */
  value: string;
  /** 界面上显示的名字。只在规范词本身读起来别扭时才不同（如 ios → iOS）。 */
  label: string;
  /** 所属职能桶，用来在界面上分组。 */
  bucket: string;
}

/** 规范词本身读起来别扭时的显示名。**只改显示，不改写库的值**。 */
const DISPLAY_OVERRIDES: Record<string, string> = {
  ios: "iOS",
};

function buildRoles(): QuickStartRole[] {
  const seen = new Set<string>();
  const roles: QuickStartRole[] = [];
  CHINA_KEYWORD_GROUPS.forEach((group: string[], i: number) => {
    const bucket = KEYWORD_GROUP_FUNCTIONS[i];
    // 组职能为 null = 这组不是职能（招聘类型 / 工程通用锚点之类），不该出现在「选方向」里。
    if (!bucket) return;
    const value = String(group?.[0] ?? "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    roles.push({ value, label: DISPLAY_OVERRIDES[value] ?? value, bucket });
  });
  return roles;
}

export const QUICK_START_ROLES: QuickStartRole[] = buildRoles();

/** API 白名单：只接受词库里的规范词，挡掉任意文本写进偏好。 */
const ALLOWED = new Set(QUICK_START_ROLES.map((r) => r.value));

export function isQuickStartRole(value: unknown): value is string {
  return typeof value === "string" && ALLOWED.has(value.trim());
}

/** 按职能桶分组，桶顺序沿用 JOB_FUNCTION_BUCKETS（与筛选器同序，用户不用重新认一遍）。 */
export function quickStartRolesByBucket(): Array<{ bucket: string; roles: QuickStartRole[] }> {
  const map = new Map<string, QuickStartRole[]>();
  for (const role of QUICK_START_ROLES) {
    const list = map.get(role.bucket);
    if (list) list.push(role);
    else map.set(role.bucket, [role]);
  }
  return JOB_FUNCTION_BUCKETS.filter((b: string) => map.has(b)).map((bucket: string) => ({
    bucket,
    roles: map.get(bucket)!,
  }));
}

/** 一次最多选几个方向：够表达意图，又不至于宽到「什么都想要」= 没筛。 */
export const QUICK_START_MAX_ROLES = 5;
