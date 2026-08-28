import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { calculatePKCECodeChallenge, generateRandomCodeVerifier, generateRandomState } from "oauth4webapi";
import { encode } from "@/lib/session";
import { applicationOrigin } from "@/lib/origin";
import { isSecureRuntime } from "@/lib/runtime";

export async function GET(request: NextRequest) {
  const auth = process.env.OIDC_AUTHORIZATION_URL;
  const client = process.env.OIDC_CLIENT_ID;
  const origin = applicationOrigin(request);
  if (!auth || !client) return NextResponse.redirect(new URL("/unauthorized?reason=configuration", origin));
  const verifier = generateRandomCodeVerifier();
  const state = generateRandomState();
  const returnTo = request.nextUrl.searchParams.get("returnTo") || "/chat";
  const safeReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/chat";
  const jar = await cookies();
  jar.set("oidc_transaction", await encode({ verifier, state, returnTo: safeReturnTo }, "10m"), { httpOnly: true, secure: isSecureRuntime(), sameSite: "lax", path: "/", maxAge: 600 });
  const url = new URL(auth);
  url.search = new URLSearchParams({ response_type: "code", client_id: client, redirect_uri: new URL("/api/auth/callback", origin).toString(), scope: process.env.OIDC_SCOPES || "openid profile offline_access rag:access", state, code_challenge: await calculatePKCECodeChallenge(verifier), code_challenge_method: "S256" }).toString();
  return NextResponse.redirect(url);
}
