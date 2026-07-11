const assert = require("node:assert/strict");
const test = require("node:test");
const { loadTsModule } = require("./route-test-utils");

const { createJobStatsRefresher, installVisiblePolling } = loadTsModule(
  "lib/job-stats-refresh.ts",
);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("job stats refresher reuses one in-flight promise and starts a new request after settle", async () => {
  const first = deferred();
  const second = deferred();
  const requests = [first, second];
  const starts = [];
  const successes = [];
  let fetchCount = 0;
  const refresher = createJobStatsRefresher({
    fetchStats: () => requests[fetchCount++].promise,
    onStart: () => starts.push("start"),
    onSuccess: (stats) => successes.push(stats),
    onError: (error) => assert.fail(`unexpected error: ${error}`),
  });

  const firstRefresh = refresher.refresh();
  const duplicateRefresh = refresher.refresh();

  assert.strictEqual(duplicateRefresh, firstRefresh);
  assert.equal(fetchCount, 1);
  assert.equal(starts.length, 1);

  first.resolve({ validActive: 12 });
  await firstRefresh;
  assert.deepEqual(successes, [{ validActive: 12 }]);

  const nextRefresh = refresher.refresh();
  assert.notStrictEqual(nextRefresh, firstRefresh);
  assert.equal(fetchCount, 2);
  assert.equal(starts.length, 2);

  second.resolve({ validActive: 13 });
  await nextRefresh;
  assert.deepEqual(successes, [{ validActive: 12 }, { validActive: 13 }]);
});

test("job stats refresher reports a failure once and can retry after it settles", async () => {
  const first = deferred();
  const second = deferred();
  const requests = [first, second];
  const errors = [];
  const successes = [];
  let fetchCount = 0;
  const refresher = createJobStatsRefresher({
    fetchStats: () => requests[fetchCount++].promise,
    onStart: () => {},
    onSuccess: (stats) => successes.push(stats),
    onError: (error) => errors.push(error),
  });

  const failedRefresh = refresher.refresh();
  const failure = new Error("stats unavailable");
  first.reject(failure);
  await failedRefresh;

  assert.deepEqual(errors, [failure]);
  const retry = refresher.refresh();
  assert.equal(fetchCount, 2);
  second.resolve({ validActive: 21 });
  await retry;
  assert.deepEqual(successes, [{ validActive: 21 }]);
});

test("job stats refresher suppresses success and error callbacks after dispose", async () => {
  for (const outcome of ["success", "error"]) {
    const request = deferred();
    const callbacks = [];
    const refresher = createJobStatsRefresher({
      fetchStats: () => request.promise,
      onStart: () => callbacks.push("start"),
      onSuccess: () => callbacks.push("success"),
      onError: () => callbacks.push("error"),
    });

    const refresh = refresher.refresh();
    refresher.dispose();
    if (outcome === "success") request.resolve({ validActive: 1 });
    else request.reject(new Error("late failure"));
    await refresh;

    assert.deepEqual(callbacks, ["start"], `${outcome} callback ran after dispose`);
  }
});

test("visible polling refreshes initially and when the page returns to the foreground", () => {
  let visibilityState = "visible";
  let visibilityListener;
  let intervalCallback;
  let refreshCount = 0;
  const documentLike = {
    get visibilityState() {
      return visibilityState;
    },
    addEventListener(type, listener) {
      assert.equal(type, "visibilitychange");
      visibilityListener = listener;
    },
    removeEventListener() {},
  };
  const windowLike = {
    setInterval(callback, intervalMs) {
      assert.equal(intervalMs, 60_000);
      intervalCallback = callback;
      return 17;
    },
    clearInterval() {},
  };

  installVisiblePolling({
    documentLike,
    windowLike,
    refresh: () => {
      refreshCount += 1;
    },
    intervalMs: 60_000,
  });

  assert.equal(refreshCount, 1);
  visibilityState = "hidden";
  intervalCallback();
  assert.equal(refreshCount, 1);
  visibilityState = "visible";
  visibilityListener();
  assert.equal(refreshCount, 2);
});

test("visible polling cleanup clears the interval and removes its listener", () => {
  let activeVisibilityListener;
  let installedVisibilityListener;
  let refreshCount = 0;
  const removed = [];
  const cleared = [];
  const documentLike = {
    visibilityState: "visible",
    addEventListener(_type, listener) {
      activeVisibilityListener = listener;
      installedVisibilityListener = listener;
    },
    removeEventListener(type, listener) {
      removed.push([type, listener]);
      if (activeVisibilityListener === listener) activeVisibilityListener = undefined;
    },
  };
  const windowLike = {
    setInterval() {
      return 23;
    },
    clearInterval(intervalId) {
      cleared.push(intervalId);
    },
  };

  const cleanup = installVisiblePolling({
    documentLike,
    windowLike,
    refresh: () => {
      refreshCount += 1;
    },
    intervalMs: 60_000,
  });
  cleanup();

  assert.deepEqual(cleared, [23]);
  assert.deepEqual(removed, [["visibilitychange", installedVisibilityListener]]);
  const countAfterCleanup = refreshCount;
  activeVisibilityListener?.();
  assert.equal(refreshCount, countAfterCleanup);
});
