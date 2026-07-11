const test = require("node:test");
const assert = require("node:assert/strict");

const { buildJobsDatabaseSsl } = require("../lib/jobs-store/tls-options.js");

test("jobs database TLS refuses to start without a trusted CA", () => {
  assert.throws(
    () => buildJobsDatabaseSsl({}, "db.example.com"),
    /JOBS_DATABASE_SSL_CA/,
  );
});

test("jobs database TLS restores escaped PEM newlines and verifies the URL hostname by default", () => {
  const ssl = buildJobsDatabaseSsl(
    { JOBS_DATABASE_SSL_CA: "-----BEGIN CERTIFICATE-----\\nabc\\n-----END CERTIFICATE-----" },
    "db.example.com",
  );

  assert.deepEqual(ssl, {
    rejectUnauthorized: true,
    ca: "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----",
    servername: "db.example.com",
  });
});

test("jobs database TLS supports an explicit certificate server name", () => {
  const ssl = buildJobsDatabaseSsl(
    {
      JOBS_DATABASE_SSL_CA: "trusted-ca",
      JOBS_DATABASE_TLS_SERVERNAME: "localhost.localdomain",
    },
    "203.0.113.10",
  );

  assert.equal(ssl.servername, "localhost.localdomain");
  assert.equal(ssl.rejectUnauthorized, true);
});
