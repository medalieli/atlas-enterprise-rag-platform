"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export default function InvitationAcceptance(){
  const token=useSearchParams().get("token")??""; const [state,setState]=useState<"ready"|"working"|"accepted"|"error">("ready");
  return <main className="auth-page"><section className="auth-card"><span className="brand-mark">A</span><h1>Join this Atlas workspace</h1><p>Your verified identity-provider email must match the invitation. Atlas never asks for or stores your password.</p>{state==="accepted"?<><div className="alert success" role="status">Invitation accepted.</div><a className="button primary" href="/chat">Open Atlas</a></>:<button className="button primary" disabled={!token||state==="working"} onClick={async()=>{setState("working");try{await api("/invitations/accept",{method:"POST",body:JSON.stringify({token})});setState("accepted");}catch{setState("error");}}}>Accept invitation</button>}{state==="error"&&<div className="alert error" role="alert">This invitation is invalid, expired, revoked, already used, or does not match your verified identity.</div>}</section></main>;
}
