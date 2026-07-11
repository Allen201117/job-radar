interface JobStatsRefresherOptions<T> {
  fetchStats: () => Promise<T>;
  onStart: () => void;
  onSuccess: (stats: T) => void;
  onError: (error: unknown) => void;
}

export function createJobStatsRefresher<T>({
  fetchStats,
  onStart,
  onSuccess,
  onError,
}: JobStatsRefresherOptions<T>) {
  let disposed = false;
  let inFlight: Promise<void> | null = null;

  const refresh = () => {
    if (inFlight) return inFlight;
    if (disposed) return Promise.resolve();

    onStart();
    const request = (async () => {
      try {
        const stats = await fetchStats();
        if (!disposed) onSuccess(stats);
      } catch (error) {
        if (!disposed) onError(error);
      }
    })();

    const trackedRequest = request.finally(() => {
      if (inFlight === trackedRequest) inFlight = null;
    });
    inFlight = trackedRequest;
    return trackedRequest;
  };

  return {
    refresh,
    dispose() {
      disposed = true;
    },
  };
}

interface VisiblePollingOptions {
  documentLike: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
  windowLike: Pick<Window, "setInterval" | "clearInterval">;
  refresh: () => unknown;
  intervalMs: number;
}

export function installVisiblePolling({
  documentLike,
  windowLike,
  refresh,
  intervalMs,
}: VisiblePollingOptions) {
  const refreshIfVisible = () => {
    if (documentLike.visibilityState === "visible") void refresh();
  };

  refreshIfVisible();
  const intervalId = windowLike.setInterval(refreshIfVisible, intervalMs);
  documentLike.addEventListener("visibilitychange", refreshIfVisible);

  return () => {
    windowLike.clearInterval(intervalId);
    documentLike.removeEventListener("visibilitychange", refreshIfVisible);
  };
}
