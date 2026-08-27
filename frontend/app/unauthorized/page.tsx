import Link from "next/link";
export default function Unauthorized() { return <main className="state-page"><section><span className="status-icon">!</span><h1>Access unavailable</h1><p>Your account is not authorized for this workspace, or sign-in could not be completed.</p><Link className="button primary" href="/api/auth/login">Try again</Link></section></main>; }
