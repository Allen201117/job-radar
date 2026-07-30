import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * JWT 本地验签 + JWKS 模块级缓存。
 *
 * 背景：Supabase（Auth）托管在悉尼，而页面函数与 jobs 库在香港。改造前 middleware 与每个
 * API 路由都调 `supabase.auth.getUser()`，那是**每次请求一次跨洋往返**（middleware 跑在
 * 全球边缘节点、无法靠迁移机房解决）。改用 `getClaims()` 在本地验 JWT 签名即可零网络。
 *
 * ⚠️ 为什么必须自己缓存 JWKS：auth-js 的 fetchJwk 把公钥缓存在 **GoTrueClient 实例**上
 * （this.jwks / this.jwks_cached_at）。serverless 每个请求都要 createServerClient() 新建实例，
 * 实例缓存永远是空的 → 每请求改成去拉一次 JWKS，等于用「取公钥」换掉「验 token」，
 * 一次往返都没省下。把缓存提到模块级（同一 lambda 实例内跨请求共享）并通过 options.jwks
 * 显式喂进去，命中即纯本地 WebCrypto 验签、真正零网络。
 */

/** 对齐 Supabase 官方 JWKS 端点的 Edge 缓存时长。官方要求调用方不要缓存更久——
 * 缓存过久会在密钥轮换/吊销后误拒仍然有效的 token。 */
const JWKS_TTL_MS = 10 * 60 * 1000;

/** options 形状直接从 SDK 方法签名推导：`@supabase/auth-js` 不在 package.json 里（只是
 * supabase-js 的传递依赖），而 supabase-js 的类型入口是打包产物、导不到 JWK 类型。
 * 这样写的好处是 SDK 换版本改了签名会直接编译报错，而不是静默失效。 */
type GetClaimsOptions = NonNullable<
  Parameters<SupabaseClient["auth"]["getClaims"]>[1]
>;
type Jwks = NonNullable<GetClaimsOptions["jwks"]>;

export type VerifiedUser = { id: string; email: string | undefined };

let cachedJwks: Jwks | null = null;
let cachedAt = 0;
/** 同一实例内多个请求同时未命中时只发一次网络请求，避免冷启动瞬间的 JWKS 请求风暴。 */
let inflight: Promise<Jwks | null> | null = null;

function jwksUrl(): string | null {
  const base = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!base) return null;
  return `${base.replace(/\/+$/, "")}/auth/v1/.well-known/jwks.json`;
}

async function fetchJwks(): Promise<Jwks | null> {
  const url = jwksUrl();
  const apikey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !apikey) return null;
  const resp = await fetch(url, { headers: { apikey } });
  if (!resp.ok) throw new Error(`jwks HTTP ${resp.status}`);
  const body = await resp.json();
  if (!body || !Array.isArray(body.keys) || body.keys.length === 0) return null;
  return body as Jwks;
}

/**
 * 取 JWKS：命中模块级缓存则零网络；未命中/过期则拉一次并共享给并发调用方。
 * 失败不抛给调用方——拿不到 jwks 时 getClaims 会自行回落（SDK 内部 fetchJwk / getUser），
 * 那次退化成一次网络往返，但结果仍然正确。
 */
async function getJwks(): Promise<Jwks | null> {
  if (cachedJwks && Date.now() - cachedAt < JWKS_TTL_MS) return cachedJwks;
  if (!inflight) {
    inflight = fetchJwks()
      .then((jwks) => {
        if (jwks) {
          cachedJwks = jwks;
          cachedAt = Date.now();
        }
        return jwks;
      })
      .catch((e) => {
        console.error(
          "[auth-claims] 拉取 JWKS 失败，本次回落到 SDK 默认验证路径:",
          (e as Error).message,
        );
        return null;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/**
 * 验证当前会话并返回已验证的用户身份（id + email）。
 *
 * - **零网络的前提**：项目已启用非对称 JWT 签名密钥（ECC/RSA）。若仍是对称密钥（HS256），
 *   getClaims 会自动回落到 getUser()，行为与改造前完全一致——只是没有提速。
 *   所以本文件可以先于 Supabase 控制台的密钥迁移安全上线。
 * - **会话刷新不受影响**：getClaims 内部第一步是 getSession()，access token 临期时照常用
 *   refresh token 刷新并触发 cookie 的 setAll，调用方的 cookie 回写逻辑无需改动。
 * - **取舍**：本地验签只证明「签名有效且未过期」，拿不到用户最新状态（封禁 / 改邮箱等要等
 *   token 过期才反映）。需要 Auth 服务器上权威最新记录的场景，仍应显式用 getUser()。
 */
export async function verifyRequestClaims(
  supabase: SupabaseClient,
): Promise<VerifiedUser | null> {
  const jwks = await getJwks();
  const { data, error } = await supabase.auth.getClaims(
    undefined,
    jwks ? { jwks } : undefined,
  );
  if (error || !data) return null;
  // claims 本质是 JWT 里的键值包，按结构读取，不依赖 SDK 具体的 payload 类型。
  const claims = data.claims as unknown as Record<string, unknown>;
  const sub = claims.sub;
  if (typeof sub !== "string" || !sub) return null;
  const email = claims.email;
  return { id: sub, email: typeof email === "string" ? email : undefined };
}
