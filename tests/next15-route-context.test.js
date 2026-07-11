const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const routes = [
  ["app/api/job-actions/[jobId]/route.ts", ["PUT", "PATCH"]],
  ["app/api/jobs/[jobId]/liveness/route.ts", ["POST"]],
  ["app/api/job-actions/[jobId]/view/route.ts", ["POST"]],
];

for (const [relativePath, handlers] of routes) {
  const source = fs.readFileSync(path.join(root, relativePath), "utf8");

  for (const handler of handlers) {
    test(`${relativePath} ${handler} uses the Next 15 async route context`, () => {
      const signature = new RegExp(
        `export\\s+async\\s+function\\s+${handler}\\s*\\([^)]*\\{\\s*params\\s*\\}\\s*:\\s*\\{\\s*params\\s*:\\s*Promise\\s*<\\s*\\{\\s*jobId\\s*:\\s*string\\s*;?\\s*\\}\\s*>\\s*\\}`,
        "s",
      );
      assert.match(source, signature, `${handler} must type params as Promise<{ jobId: string }>`);

      const bodyStart = source.indexOf("{", source.indexOf(`export async function ${handler}`));
      const nextExport = source.indexOf("\nexport async function ", bodyStart + 1);
      const body = source.slice(bodyStart, nextExport === -1 ? source.length : nextExport);
      assert.match(body, /const\s+\{\s*jobId\s*\}\s*=\s*await\s+params\s*;/);
    });
  }
}

test("liveness authentication remains before awaiting route params", () => {
  const source = fs.readFileSync(path.join(root, "app/api/jobs/[jobId]/liveness/route.ts"), "utf8");
  const authIndex = source.indexOf("const auth = await requireUser();");
  const paramsIndex = source.indexOf("const { jobId } = await params;");
  assert.ok(authIndex !== -1 && paramsIndex !== -1 && authIndex < paramsIndex);
});
