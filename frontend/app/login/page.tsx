import Link from "next/link";
import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string; error?: string }> }) {
  if (await getSession()) redirect("/dashboard" as "/chat");
  const params = await searchParams;
  const requested = params.returnTo?.startsWith("/") && !params.returnTo.startsWith("//") ? params.returnTo : "/dashboard";
  return <main className="login" id="main-content"><section className="login-card" aria-labelledby="login-title">
    <div className="brand-lockup"><span className="brand-mark">A</span><span>Atlas Knowledge</span></div>
    <p className="eyebrow">ENTERPRISE KNOWLEDGE WORKSPACE</p>
    <h1 id="login-title">Answers your team can verify.</h1>
    <p className="login-copy">Search approved knowledge, inspect exact citations, and keep trusted documents current in one secure workspace.</p>
    {params.error && <div className="alert error" role="alert">Sign-in could not be completed. Please try again or contact your administrator.</div>}
    <Link className="button primary wide" href={`/api/auth/login?returnTo=${encodeURIComponent(requested)}`}>Sign in to Atlas</Link>
    <div className="security-note"><strong>Your credentials stay with your identity provider.</strong><span>Atlas never asks for or stores your password. Sessions use secure, HTTP-only cookies.</span></div>
  </section></main>;
}
