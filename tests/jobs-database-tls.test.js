const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildJobsDatabaseSsl,
  buildJobsDatabaseLibpqUrl,
} = require("../lib/jobs-store/tls-options.js");

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

test("libpq TLS uses host plus hostaddr for an IP endpoint with a different certificate name", () => {
  const strictUrl = new URL(buildJobsDatabaseLibpqUrl(
    "postgresql://user:secret@203.0.113.10:5432/jobs?sslmode=require",
    "/tmp/jobs-ca.pem",
    "localhost.localdomain",
  ));

  assert.equal(strictUrl.hostname, "localhost.localdomain");
  assert.equal(strictUrl.searchParams.get("hostaddr"), "203.0.113.10");
  assert.equal(strictUrl.searchParams.get("sslmode"), "verify-full");
  assert.equal(strictUrl.searchParams.get("sslrootcert"), "/tmp/jobs-ca.pem");
});

test("libpq TLS rejects a mismatched DNS endpoint that cannot use hostaddr safely", () => {
  assert.throws(
    () => buildJobsDatabaseLibpqUrl(
      "postgresql://user:secret@db.example.com:5432/jobs",
      "/tmp/jobs-ca.pem",
      "other.example.com",
    ),
    /DNS host/,
  );
});
