import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { calculatePKCECodeChallenge, generateRandomCodeVerifier, generateRandomState } from "oauth4webapi";
import { encode } from "@/lib/session";
import { applicationOrigin } from "@/lib/origin";

export async function GET(request: NextRequest) {
  const auth = process.env.OIDC_AUTHORIZATION_URL;
  const client = process.env.OIDC_CLIENT_ID;
  if (!auth || !client) return NextResponse.redirect(new URL("/unauthorized?reason=configuration", request.url));
  const verifier = generateRandomCodeVerifier();
  const state = generateRandomState();
  const returnTo = request.nextUrl.searchParams.get("returnTo") || "/chat";
  const safeReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/chat";
  const jar = await cookies();
  jar.set("oidc_transaction", await encode({ verifier, state, returnTo: safeReturnTo }, "10m"), { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: 600 });
  const url = new URL(auth);
  url.search = new URLSearchParams({ response_type: "code", client_id: client, redirect_uri: new URL("/api/auth/callback", applicationOrigin(request)).toString(), scope: process.env.OIDC_SCOPES || "openid profile offline_access rag:access", state, code_challenge: await calculatePKCECodeChallenge(verifier), code_challenge_method: "S256" }).toString();
  return NextResponse.redirect(url);
}
