import { cookies } from "next/headers";
import { NextResponse } from "next/server";
export async function GET() { const token = (await cookies()).get("rag_csrf")?.value; return token ? NextResponse.json({ token }, { headers: { "Cache-Control": "no-store" } }) : NextResponse.json({ detail: "Unauthorized" }, { status: 401 }); }
