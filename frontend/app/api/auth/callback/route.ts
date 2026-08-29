import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { decode, setSession } from "@/lib/session";
import { applicationOrigin } from "@/lib/origin";
import { isSecureRuntime } from "@/lib/runtime";

type Transaction = { verifier: string; state: string; returnTo: string };
export async function GET(request: NextRequest) {
  const origin = applicationOrigin(request);
  const jar = await cookies();
  const tx = await decode<Transaction>(jar.get("oidc_transaction")?.value);
  jar.delete("oidc_transaction");
  if (!tx || request.nextUrl.searchParams.get("state") !== tx.state || !request.nextUrl.searchParams.get("code")) return NextResponse.redirect(new URL("/login?error=authentication", origin));
  const body = new URLSearchParams({ grant_type: "authorization_code", code: request.nextUrl.searchParams.get("code")!, redirect_uri: new URL("/api/auth/callback", origin).toString(), client_id: process.env.OIDC_CLIENT_ID!, code_verifier: tx.verifier });
  if (process.env.OIDC_CLIENT_SECRET) body.set("client_secret", process.env.OIDC_CLIENT_SECRET);
  const token = await fetch(process.env.OIDC_TOKEN_URL!, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body, cache: "no-store" });
  if (!token.ok) return NextResponse.redirect(new URL("/login?error=authentication", origin));
  const data = await token.json() as { access_token: string; refresh_token?: string; expires_in?: number };
  await setSession({ accessToken: data.access_token, refreshToken: data.refresh_token, expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000 });
  jar.set("rag_csrf", crypto.randomUUID(), { httpOnly: false, secure: isSecureRuntime(), sameSite: "strict", path: "/", maxAge: 28800 });
  return NextResponse.redirect(new URL(tx.returnTo, origin));
}
