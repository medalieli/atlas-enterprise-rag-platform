import type { NextRequest } from "next/server";

export function applicationOrigin(request: NextRequest): string {
  const configured = process.env.APP_BASE_URL;
  if (!configured) return request.nextUrl.origin;
  const url = new URL(configured);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('APP_BASE_URL must be an HTTP(S) origin without credentials, path, query, or fragment');
  }
  return url.origin;
}
