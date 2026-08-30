import { NextRequest, NextResponse } from "next/server";
import { applicationOrigin } from "@/lib/origin";
import { setInvitationContinuation } from "@/lib/session";

export async function POST(request: NextRequest) {
  if (request.headers.get("origin") !== applicationOrigin(request) || request.headers.get("sec-fetch-site") === "cross-site")
    return NextResponse.json({ detail: "Request rejected" }, { status: 403 });
  let token: unknown;
  try { token = (await request.json() as { token?: unknown }).token; } catch { token = null; }
  if (typeof token !== "string" || token.length < 32 || token.length > 512)
    return NextResponse.json({ detail: "Invitation unavailable" }, { status: 400 });
  await setInvitationContinuation(token);
  return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "private, no-store" } });
}
