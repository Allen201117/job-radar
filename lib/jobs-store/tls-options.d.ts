export function buildJobsDatabaseSsl(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
  hostname: string,
): {
  rejectUnauthorized: true;
  ca: string;
  servername: string;
};

export function buildJobsDatabaseLibpqUrl(
  rawUrl: string,
  rootCertPath: string,
  certificateServername?: string,
): string;
