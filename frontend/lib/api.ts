export type Membership = { tenant_id: string; role: "viewer" | "editor" | "admin"; permissions: string[] };
export type Identity = { principal_id: string; memberships: Membership[] };
export type Collection = { id: string; tenant_id: string; name: string; description: string | null };
export type DocumentItem = { id: string; collection_id: string; status: string; active_version_id: string | null; deleted: boolean; filename: string | null; content_type: string | null; active_version_number: number | null; active_generation_id: string | null; created_at: string; updated_at: string };
export type Version = { id: string; version_number: number; status: string; active: boolean; filename: string; content_type: string; size_bytes: number; metadata: Record<string, unknown>; active_generation_id: string | null; failure_category: string | null };
export type Citation = { citation_number: number; source_id: string; source_status?: string; document_id: string | null; document_version_id: string | null; generation_id: string | null; document_name: string | null; content_type: string | null; page_number: number | null; section_path: string | null; start_offset: number; end_offset: number; metadata: Record<string, unknown>; source_excerpt: string | null };
export type Message = { id: string; sequence_number: number; role: "user" | "assistant"; content: string; created_at: string; citations: Citation[]; answer_status?: Answer["status"] | "clarification_required"; rewriting_applied?: boolean };
export type Conversation = { id: string; collection_id: string; created_at: string; updated_at?: string };
export type Answer = { status: "answered" | "insufficient_context" | "conflicting_sources"; answer: string; citations: Citation[] };
export type Turn = { turn_status: string; rewriting_applied: boolean; clarification_question: string | null; answer: Answer | null };

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
let csrf: string | null = null;
export function resetCsrfForTests() { csrf = null; }
async function csrfToken() { if (!csrf) { const r = await fetch("/api/auth/csrf", { cache: "no-store" }); if (!r.ok) throw new ApiError(r.status, "Your session has expired."); csrf = (await r.json() as { token: string }).token; } return csrf; }
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && !["GET", "HEAD"].includes(init.method)) headers.set("x-csrf-token", await csrfToken());
  if (init.body && !(init.body instanceof FormData)) headers.set("content-type", "application/json");
  let response: Response;
  try { response = await fetch(`/api/backend${path}`, { ...init, headers, cache: "no-store" }); } catch { throw new ApiError(0, "Network unavailable. Check your connection and try again."); }
  if (!response.ok) { let detail = "Request could not be completed."; try { detail = (await response.json() as { detail?: string }).detail || detail; } catch {} throw new ApiError(response.status, detail); }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
export async function logout(): Promise<void> {
  const response = await fetch("/api/auth/logout", { method: "POST", headers: { "x-csrf-token": await csrfToken() }, cache: "no-store" });
  if (!response.ok) throw new ApiError(response.status, "Logout could not be completed.");
  csrf = null;
}
export const key = () => crypto.randomUUID();
