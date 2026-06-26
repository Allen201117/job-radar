// 登录回跳安全校验：只允许「站内单斜杠相对路径」，其余一律回退 /today。
// 纯函数、零 import，供 middleware / 登录页 / 测试加载器复用。
//
// 接受：以单个 "/" 开头、不是 "//" 开头、不含协议/host、不含反斜杠、不含控制字符、不含空白。
// 拒绝（→ "/today"）：协议绝对地址、协议相对地址（//evil.com）、反斜杠绕过、控制字符、空白、
//   空串、非字符串、缺前导斜杠的相对路径。
export function safeNextPath(next: unknown): string {
  const fallback = "/today";
  if (typeof next !== "string") return fallback;
  if (next.length === 0) return fallback;
  // 必须以单斜杠开头，且不能是「//」协议相对地址。
  if (next[0] !== "/") return fallback;
  if (next[1] === "/") return fallback;
  // 反斜杠可被浏览器规整为「/」造成绕过（如 "/\evil.com"）。
  if (next.includes("\\")) return fallback;
  // 控制字符（含 \t \n \r）或任何空白都不允许出现在合法内部路径里。
  for (let i = 0; i < next.length; i++) {
    const code = next.charCodeAt(i);
    if (code <= 0x20 || code === 0x7f) return fallback;
  }
  return next;
}
