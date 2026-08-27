import { NextRequest, NextResponse } from "next/server";
import { sessionCookieName } from "@/lib/session";
export function proxy(request: NextRequest) {
  if (process.env.NODE_ENV !== "production" && process.env.TEST_BYPASS_AUTH === "true") return NextResponse.next();
  const publicPath = request.nextUrl.pathname === "/" || request.nextUrl.pathname.startsWith("/unauthorized") || request.nextUrl.pathname.startsWith("/session-expired") || request.nextUrl.pathname.startsWith("/api/auth/");
  if (!publicPath && !request.cookies.has(sessionCookieName)) { const url = new URL("/session-expired", request.url); url.searchParams.set("returnTo", request.nextUrl.pathname); return NextResponse.redirect(url); }
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
