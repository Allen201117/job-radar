const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const workflows = fs.readdirSync(path.join(root, ".github", "workflows"))
  .filter((name) => /\.ya?ml$/.test(name));

test("every jobs database workflow injects the CA and certificate server name", () => {
  for (const name of workflows) {
    const source = fs.readFileSync(path.join(root, ".github", "workflows", name), "utf8");
    const urlCount = (source.match(/JOBS_DATABASE_URL:\s*\$\{\{ secrets\.JOBS_DATABASE_URL \}\}/g) || []).length;
    if (!urlCount) continue;
    const caCount = (source.match(/JOBS_DATABASE_SSL_CA:\s*\$\{\{ secrets\.JOBS_DATABASE_SSL_CA \}\}/g) || []).length;
    const servernameCount = (source.match(/JOBS_DATABASE_TLS_SERVERNAME:\s*\$\{\{ secrets\.JOBS_DATABASE_TLS_SERVERNAME \}\}/g) || []).length;
    assert.equal(caCount, urlCount, `${name} must inject one CA per jobs DB environment`);
    assert.equal(servernameCount, urlCount, `${name} must inject one certificate name per jobs DB environment`);
  }
});

test("direct libpq workflows enable verify-full before invoking jobs psql", () => {
  const directLibpqWorkflows = [
    "db-report.yml",
    "jobs-db-data-migrate.yml",
    "jobs-db-migrate.yml",
    "maintenance-vacuum.yml",
    "purge-expired.yml",
  ];
  for (const name of directLibpqWorkflows) {
    const source = fs.readFileSync(path.join(root, ".github", "workflows", name), "utf8");
    assert.match(source, /source scripts\/enable-jobs-db-strict-tls\.sh/, name);
  }
});

test("production database consumers contain no rejectUnauthorized false fallback", () => {
  const files = [
    "lib/jobs-store/client.ts",
    "scripts/verify-admin-health-accuracy.mjs",
    "scripts/verify-opportunity-recall.ts",
  ];
  for (const file of files) {
    const source = fs.readFileSync(path.join(root, file), "utf8");
    assert.doesNotMatch(source, /rejectUnauthorized:\s*false/, file);
  }
});
