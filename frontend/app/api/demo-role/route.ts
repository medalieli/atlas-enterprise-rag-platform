import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { applicationOrigin } from "@/lib/origin";
import { getSession, setSession } from "@/lib/session";

const roles = new Set(["owner", "admin", "editor", "viewer"]);

export async function POST(request: NextRequest) {
  if (process.env.DEMO_ROLE_PREVIEW_ENABLED !== "true" || process.env.APP_ENV === "production")
    return NextResponse.json({ detail: "Demo role preview is unavailable" }, { status: 404 });
  const jar = await cookies();
  const csrf = jar.get("rag_csrf")?.value;
  if (!csrf || csrf !== request.headers.get("x-csrf-token") || request.headers.get("origin") !== applicationOrigin(request) || request.headers.get("sec-fetch-site") === "cross-site")
    return NextResponse.json({ detail: "CSRF validation failed" }, { status: 403 });
  const session = await getSession();
  if (!session) return NextResponse.json({ detail: "Session expired" }, { status: 401 });
  let input: { tenant_id?: unknown; role?: unknown } = {};
  try { input = await request.json() as typeof input; } catch {}
  if (typeof input.tenant_id !== "string" || typeof input.role !== "string" || !roles.has(input.role))
    return NextResponse.json({ detail: "Invalid demo role request" }, { status: 400 });
  const response = await fetch(`${process.env.API_INTERNAL_URL || "http://api:8000"}/demo/role-preview`, {
    method: "POST",
    headers: { authorization: `Bearer ${session.accessToken}`, "content-type": "application/json" },
    body: JSON.stringify(input),
    cache: "no-store",
    redirect: "manual",
  });
  if (!response.ok) return NextResponse.json({ detail: "Demo role could not be changed" }, { status: response.status });
  const result = await response.json() as { effective_role: "owner" | "admin" | "editor" | "viewer"; preview_token: string };
  await setSession({ ...session, demoPreviewToken: result.preview_token, effectiveDemoRole: result.effective_role });
  return NextResponse.json({ effective_role: result.effective_role }, { headers: { "Cache-Control": "private, no-store" } });
}
