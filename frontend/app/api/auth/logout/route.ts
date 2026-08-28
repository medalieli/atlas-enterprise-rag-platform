import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { clearSession } from "@/lib/session";
import { applicationOrigin } from "@/lib/origin";
import { isSecureRuntime } from "@/lib/runtime";
export async function POST(request: NextRequest) {
  const csrf = (await cookies()).get("rag_csrf")?.value;
  if (!csrf || request.headers.get("x-csrf-token") !== csrf || request.headers.get("origin") !== applicationOrigin(request)) return NextResponse.json({ detail: "CSRF validation failed" }, { status: 403 });
  await clearSession(); (await cookies()).set("rag_csrf", "", { secure: isSecureRuntime(), sameSite: "strict", path: "/", maxAge: 0 });
  return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
}
