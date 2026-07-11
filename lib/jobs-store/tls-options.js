"use strict";

const net = require("node:net");

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

/**
 * Build a libpq-compatible verify-full URL. libpq separates the logical host
 * used for certificate verification from the network address via hostaddr.
 * That lets the current IP endpoint verify its pinned certificate name.
 *
 * @param {string} rawUrl
 * @param {string} rootCertPath
 * @param {string | undefined} certificateServername
 * @returns {string}
 */
function buildJobsDatabaseLibpqUrl(rawUrl, rootCertPath, certificateServername) {
  const url = new URL(rawUrl);
  const endpointHost = url.hostname;
  const servername = certificateServername?.trim() || endpointHost;

  if (servername !== endpointHost) {
    if (!net.isIP(endpointHost)) {
      throw new Error(
        "JOBS_DATABASE_TLS_SERVERNAME differs from a DNS host; configure a certificate whose SAN matches the database URL",
      );
    }
    url.hostname = servername;
    url.searchParams.set("hostaddr", endpointHost);
  }

  url.searchParams.set("sslmode", "verify-full");
  url.searchParams.set("sslrootcert", rootCertPath);
  return url.toString();
}

module.exports = { buildJobsDatabaseSsl, buildJobsDatabaseLibpqUrl };
