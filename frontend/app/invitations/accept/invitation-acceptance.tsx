"use client";
/* eslint-disable @next/next/no-location-assign-relative-destination -- hard navigation ensures HttpOnly continuation cookies reach the server render */

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { logout } from "@/lib/api";

type State = "preparing" | "ready" | "working" | "accepted" | "wrong-identity" | "invalid" | "session-expired";

export default function InvitationAcceptance({ authenticated, continuationReady }: { authenticated: boolean; continuationReady: boolean }) {
  const [state, setState] = useState<State>(continuationReady ? "ready" : "preparing");
  const captureStarted = useRef(false);

  useEffect(() => {
    if (continuationReady || captureStarted.current) return;
    captureStarted.current = true;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) { void Promise.resolve().then(() => setState("invalid")); return; }
    window.history.replaceState(null, "", window.location.pathname);
    void fetch("/api/invitations/continue", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
    }).then((response) => {
      if (!response.ok) { setState("invalid"); return; }
      window.location.replace("/invitations/accept");
    }).catch(() => setState("invalid"));
  }, [continuationReady]);

  async function accept() {
    setState("working");
    const csrf = await fetch("/api/auth/csrf", { cache: "no-store" });
    if (!csrf.ok) { setState("session-expired"); return; }
    const token = (await csrf.json() as { token: string }).token;
    const response = await fetch("/api/invitations/accept", { method: "POST", headers: { "x-csrf-token": token }, cache: "no-store" });
    if (response.ok) { setState("accepted"); return; }
    if (response.status === 401) { setState("session-expired"); return; }
    if (response.status === 403) { setState("wrong-identity"); return; }
    setState("invalid");
  }

  async function signOutAndRetry() {
    await logout();
    window.location.assign("/invitations/accept");
  }

  return <main className="auth-page" id="main-content"><section className="auth-card" aria-labelledby="invitation-title">
    <span className="invitation-logo"><Image src="/atlas-logo.svg" alt="Atlas" width={360} height={88} priority /></span><h1 id="invitation-title">Join this Atlas workspace</h1>
    <p>Your verified identity-provider email must match the invitation. Atlas never asks for or stores your password.</p>
    {state === "preparing" && <div role="status">Preparing your secure invitation…</div>}
    {state === "ready" && !authenticated && <a className="button primary" href="/api/auth/login?returnTo=%2Finvitations%2Faccept">Sign in to accept invitation</a>}
    {state === "ready" && authenticated && <button className="button primary" onClick={() => void accept()}>Accept invitation</button>}
    {state === "working" && <button className="button primary" disabled>Accepting invitation…</button>}
    {state === "accepted" && <><div className="alert success" role="status">Invitation accepted.</div><a className="button primary" href="/dashboard">Open Atlas</a></>}
    {state === "wrong-identity" && <><div className="alert error" role="alert">This signed-in account cannot accept this invitation. Sign out and sign in with the invited company account.</div><button className="button" onClick={() => void signOutAndRetry()}>Sign out and retry</button></>}
    {state === "session-expired" && <><div className="alert error" role="alert">Your session ended before the invitation could be accepted.</div><a className="button primary" href="/api/auth/login?returnTo=%2Finvitations%2Faccept">Sign in again</a></>}
    {state === "invalid" && <><div className="alert error" role="alert">This invitation is invalid, expired, revoked, or already used.</div><a className="button" href="/login">Return to login</a><p>Contact an organization administrator for a new invitation.</p></>}
  </section></main>;
}
