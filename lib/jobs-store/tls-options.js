"use strict";

/**
 * Build a strict TLS configuration for the independent jobs database.
 * A missing CA is a startup error: silently falling back to encrypted-but-
 * unauthenticated TLS would reintroduce the production vulnerability.
 *
 * @param {NodeJS.ProcessEnv | Record<string, string | undefined>} env
 * @param {string} hostname
 * @returns {{ rejectUnauthorized: true, ca: string, servername: string }}
 */
function buildJobsDatabaseSsl(env, hostname) {
  const rawCa = env.JOBS_DATABASE_SSL_CA?.trim();
  if (!rawCa) {
    throw new Error(
      "JOBS_DATABASE_SSL_CA 未配置：拒绝以不校验证书身份的方式连接岗位数据库",
    );
  }

  const ca = rawCa.replace(/\\n/g, "\n");
  const servername = env.JOBS_DATABASE_TLS_SERVERNAME?.trim() || hostname;

  return {
    rejectUnauthorized: true,
    ca,
    servername,
  };
}

module.exports = { buildJobsDatabaseSsl };
