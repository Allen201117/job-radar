export function buildJobsDatabaseSsl(
  env: NodeJS.ProcessEnv | Record<string, string | undefined>,
  hostname: string,
): {
  rejectUnauthorized: true;
  ca: string;
  servername: string;
};
