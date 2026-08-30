import { getInvitationContinuation, getSession } from "@/lib/session";
import InvitationAcceptance from "./invitation-acceptance";

export const dynamic = "force-dynamic";

export default async function InvitationAcceptancePage() {
  const [session, continuation] = await Promise.all([
    getSession(),
    getInvitationContinuation(),
  ]);
  return <InvitationAcceptance authenticated={Boolean(session)} continuationReady={Boolean(continuation)} />;
}
