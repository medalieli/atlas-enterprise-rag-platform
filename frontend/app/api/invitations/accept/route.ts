import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { applicationOrigin } from "@/lib/origin";
import { clearInvitationContinuation, clearSession, getInvitationContinuation, getSession } from "@/lib/session";

export async function POST(request: NextRequest) {
  const jar = await cookies();
  const csrf = jar.get("rag_csrf")?.value;
  if (!csrf || csrf !== request.headers.get("x-csrf-token") || request.headers.get("origin") !== applicationOrigin(request) || request.headers.get("sec-fetch-site") === "cross-site")
    return NextResponse.json({ detail: "CSRF validation failed" }, { status: 403 });
  const [session, continuation] = await Promise.all([getSession(), getInvitationContinuation()]);
  if (!session) return NextResponse.json({ category: "session" }, { status: 401 });
  if (!continuation) return NextResponse.json({ category: "invalid" }, { status: 410 });
  const response = await fetch(`${process.env.API_INTERNAL_URL || "http://api:8000"}/invitations/accept`, {
    method: "POST",
    headers: { authorization: `Bearer ${session.accessToken}`, "content-type": "application/json" },
    body: JSON.stringify({ token: continuation.token }),
    cache: "no-store",
    redirect: "manual",
  });
  if (response.status === 401) await clearSession();
  if (response.ok || response.status === 404 || response.status === 410) await clearInvitationContinuation();
  const category = response.ok ? "accepted" : response.status === 403 ? "identity" : response.status === 401 ? "session" : "invalid";
  return NextResponse.json({ category }, { status: response.status, headers: { "Cache-Control": "private, no-store" } });
}
