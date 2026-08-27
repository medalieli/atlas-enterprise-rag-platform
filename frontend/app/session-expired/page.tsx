import Link from "next/link";
export default function Expired() { return <main className="state-page"><section><span className="status-icon">↻</span><h1>Session expired</h1><p>Your secure session ended. Sign in again to continue.</p><Link className="button primary" href="/api/auth/login">Sign in again</Link></section></main>; }
