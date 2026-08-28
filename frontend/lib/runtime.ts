export function isSecureRuntime(): boolean {
  return process.env.APP_ENV !== "development" && process.env.APP_ENV !== "test";
}
