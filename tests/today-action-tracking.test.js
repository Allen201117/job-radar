const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.resolve(__dirname, "../app/today-client.tsx"),
  "utf8",
);

test("undo success event is emitted only after the action API succeeds", () => {
  const start = source.indexOf("async function undo()");
  const end = source.indexOf("\n  const order:", start);
  const block = source.slice(start, end);
  const responseCheck = block.indexOf("if (!resp.ok)");
  const successTrack = block.indexOf('track("opportunity_undo"');
  const catchStart = block.indexOf("} catch");

  assert.ok(start >= 0, "undo function missing");
  assert.ok(responseCheck >= 0, "undo response check missing");
  assert.ok(successTrack > responseCheck, "undo event must be after the response success check");
  assert.ok(successTrack < catchStart, "undo event must stay in the success branch");
});
