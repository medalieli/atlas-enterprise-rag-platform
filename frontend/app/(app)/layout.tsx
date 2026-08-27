import { getSession } from "@/lib/session";
import { redirect } from "next/navigation";
export default async function AppLayout({ children }: { children: React.ReactNode }) { if (!(process.env.NODE_ENV !== "production" && process.env.TEST_BYPASS_AUTH === "true") && !await getSession()) redirect("/session-expired"); return children; }
