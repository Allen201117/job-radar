// 「关系/函数不存在（迁移未应用）」统一判定（§9）。多个路由曾各写一份、口径不一（验收 P0-5：
// preferences 漏判 PostgREST 的 PGRST205）。集中到此并单测，杜绝再漂移。
//
// ⚠️ PostgREST 缺表 = **PGRST205**，message「Could not find the table ... in the schema cache」(不含 "does not exist")；
//    缺函数 = **PGRST202**。直连 PG 则为 42P01(undefined_table) / 42883(undefined_function)。
type DbError = { code?: string; message?: string } | null | undefined;

const MISSING_TEXT_RE = /does not exist|schema cache|could not find/i;

export function isMissingRelation(err: DbError): boolean {
  if (!err) return false;
  if (err.code === "PGRST205" || err.code === "42P01") return true;
  return MISSING_TEXT_RE.test(String(err.message || ""));
}

export function isMissingFunction(err: DbError): boolean {
  if (!err) return false;
  if (err.code === "PGRST202" || err.code === "42883") return true;
  return MISSING_TEXT_RE.test(String(err.message || ""));
}
