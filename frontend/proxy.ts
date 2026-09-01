import { NextRequest, NextResponse } from "next/server";
import { sessionCookieName } from "@/lib/session";
export function proxy(request: NextRequest) {
  if (process.env.DEMO_ROLE_PREVIEW_ENABLED === "true" && (request.nextUrl.pathname === "/admin/members" || request.nextUrl.pathname === "/admin/invitations"))
    return new NextResponse("Not found", { status: 404 });
  if (process.env.NODE_ENV !== "production" && process.env.TEST_BYPASS_AUTH === "true") return NextResponse.next();
  const publicPath = request.nextUrl.pathname === "/login" || request.nextUrl.pathname === "/health" || request.nextUrl.pathname === "/atlas-logo.svg" || request.nextUrl.pathname === "/invitations/accept" || request.nextUrl.pathname.startsWith("/api/auth/") || request.nextUrl.pathname.startsWith("/api/invitations/");
  if (!publicPath && !request.cookies.has(sessionCookieName)) { const url = new URL("/login", request.url); url.searchParams.set("returnTo", `${request.nextUrl.pathname}${request.nextUrl.search}`); return NextResponse.redirect(url); }
  const response = NextResponse.next();
  if (!publicPath) {
    response.headers.set("Cache-Control", "private, no-store");
    response.headers.set("Pragma", "no-cache");
  }
  return response;
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
