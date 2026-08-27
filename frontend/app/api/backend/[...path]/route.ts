import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { clearSession, getSession, setSession } from "@/lib/session";
import { applicationOrigin } from "@/lib/origin";

async function refresh(refreshToken: string) {
  const body = new URLSearchParams({ grant_type: "refresh_token", refresh_token: refreshToken, client_id: process.env.OIDC_CLIENT_ID! });
  if (process.env.OIDC_CLIENT_SECRET) body.set("client_secret", process.env.OIDC_CLIENT_SECRET);
  const response = await fetch(process.env.OIDC_TOKEN_URL!, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body, cache: "no-store" });
  if (!response.ok) return null;
  const data = await response.json() as { access_token: string; refresh_token?: string; expires_in?: number };
  return { accessToken: data.access_token, refreshToken: data.refresh_token ?? refreshToken, expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000 };
}
async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  let session = await getSession();
  if (!session) return NextResponse.json({ detail: "Session expired" }, { status: 401 });
  if (session.expiresAt < Date.now() + 30000 && session.refreshToken) { session = await refresh(session.refreshToken); if (session) await setSession(session); }
  if (!session) { await clearSession(); return NextResponse.json({ detail: "Session expired" }, { status: 401 }); }
  if (!["GET", "HEAD"].includes(request.method)) {
    const jar = await cookies();
    if (!jar.get("rag_csrf")?.value || jar.get("rag_csrf")?.value !== request.headers.get("x-csrf-token") || request.headers.get("origin") !== applicationOrigin(request) || request.headers.get("sec-fetch-site") === "cross-site") return NextResponse.json({ detail: "CSRF validation failed" }, { status: 403 });
  }
  const { path } = await context.params;
  if (path.some((part) => !/^[A-Za-z0-9._~-]+$/.test(part))) return NextResponse.json({ detail: "Invalid path" }, { status: 400 });
  const upstream = new URL(path.join("/"), `${process.env.API_INTERNAL_URL || "http://api:8000"}/`);
  upstream.search = request.nextUrl.search;
  const headers = new Headers(); headers.set("authorization", `Bearer ${session.accessToken}`); headers.set("accept", request.headers.get("accept") || "application/json");
  const contentType = request.headers.get("content-type"); if (contentType) headers.set("content-type", contentType);
  const idempotency = request.headers.get("idempotency-key"); if (idempotency) headers.set("idempotency-key", idempotency);
  const response = await fetch(upstream, { method: request.method, headers, body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(), cache: "no-store", redirect: "manual" });
  if (response.status === 401) await clearSession();
  const outHeaders = new Headers(); outHeaders.set("content-type", response.headers.get("content-type") || "application/json"); outHeaders.set("Cache-Control", "private, no-store");
  const disposition = response.headers.get("content-disposition"); if (disposition) outHeaders.set("content-disposition", disposition);
  return new NextResponse(response.body, { status: response.status, headers: outHeaders });
}
export { handler as GET, handler as POST, handler as DELETE, handler as PUT, handler as PATCH };
