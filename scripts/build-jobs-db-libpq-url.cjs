#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  buildJobsDatabaseSsl,
  buildJobsDatabaseLibpqUrl,
} = require("../lib/jobs-store/tls-options.js");

const rawUrl = process.env.JOBS_DATABASE_URL;
if (!rawUrl) throw new Error("JOBS_DATABASE_URL is required");

const parsed = new URL(rawUrl);
const ssl = buildJobsDatabaseSsl(process.env, parsed.hostname);
const rootCertPath = path.join(
  process.env.RUNNER_TEMP || os.tmpdir(),
  "job-radar-jobs-db-ca.pem",
);
fs.writeFileSync(rootCertPath, ssl.ca, { encoding: "utf8", mode: 0o600 });
fs.chmodSync(rootCertPath, 0o600);

process.stdout.write(
  buildJobsDatabaseLibpqUrl(rawUrl, rootCertPath, ssl.servername),
);
