import Link from "next/link";
import Image from "next/image";
import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ returnTo?: string; error?: string }> }) {
  const params = await searchParams;
  const requested = params.returnTo?.startsWith("/") && !params.returnTo.startsWith("//") ? params.returnTo : "/dashboard";
  if (await getSession()) redirect(requested as "/chat");
  return <main className="login" id="main-content">
    <section className="login-brand" aria-label="Atlas Knowledge">
      <div className="brand-logo-shell login-logo"><Image src="/atlas-logo.svg" alt="Atlas" width={360} height={88} priority /></div>
      <div className="login-brand-copy">
        <p className="eyebrow">OPERATIONAL KNOWLEDGE, VERIFIED</p>
        <h2>Decisions grounded in the sources your organization trusts.</h2>
        <p>Atlas gives teams one controlled place to search approved knowledge, trace evidence, and maintain operational context.</p>
      </div>
      <div className="login-assurance"><span>Verified sources</span><span>Role-based access</span><span>Auditable activity</span></div>
    </section>
    <section className="login-auth">
      <div className="login-card" aria-labelledby="login-title">
        <span className="auth-label">Organization access</span>
        <h1 id="login-title">Secure access to your organization&apos;s knowledge</h1>
        <p className="login-copy">Use your company identity to continue to Atlas.</p>
        {params.error && <div className="alert error" role="alert">Sign-in could not be completed. Please try again or contact your administrator.</div>}
        <Link className="button primary wide" href={`/api/auth/login?returnTo=${encodeURIComponent(requested)}`}>Continue with company account</Link>
        <div className="security-note"><span className="security-indicator" aria-hidden="true" /><span>Secured with your organization&apos;s identity provider.</span></div>
      </div>
      <p className="login-footer">Atlas Knowledge · Controlled enterprise access</p>
    </section>
  </main>;
}
