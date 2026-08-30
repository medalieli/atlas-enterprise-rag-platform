import Link from "next/link";
import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string; error?: string }> }) {
  const params = await searchParams;
  const requested = params.returnTo?.startsWith("/") && !params.returnTo.startsWith("//") ? params.returnTo : "/dashboard";
  if (await getSession()) redirect(requested as "/chat");
  return <main className="login" id="main-content"><section className="login-card" aria-labelledby="login-title">
    <div className="brand-lockup"><span className="brand-mark">A</span><span>Atlas Knowledge</span></div>
    <p className="eyebrow">INTELLIGENCE, GROUNDED IN YOUR KNOWLEDGE</p>
    <h1 id="login-title">Move from questions to trusted decisions.</h1>
    <p className="login-copy">Explore approved knowledge, trace every answer to its source, and keep your team aligned in one intelligent workspace.</p>
    {params.error && <div className="alert error" role="alert">Sign-in could not be completed. Please try again or contact your administrator.</div>}
    <Link className="button primary wide" href={`/api/auth/login?returnTo=${encodeURIComponent(requested)}`}>Enter Atlas <span aria-hidden="true">→</span></Link>
    <div className="security-note"><strong>Your credentials stay with your identity provider.</strong><span>Atlas never asks for or stores your password. Sessions use secure, HTTP-only cookies.</span></div>
  </section></main>;
}
