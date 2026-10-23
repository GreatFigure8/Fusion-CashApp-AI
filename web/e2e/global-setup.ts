import { startMockApiServer } from "../tests/support/mock-api-server";

/** Starts the programmable mock API before the Next server's first call, and stops it after. */
export default async function globalSetup(): Promise<() => Promise<void>> {
  const server = await startMockApiServer();
  return () => server.close();
}
