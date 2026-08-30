"use client";
/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  changeDemoRole,
  key,
  logout as endSession,
  type Citation,
  type Collection,
  type Conversation,
  type DocumentItem,
  type Identity,
  type Message,
  type Turn,
  type Version,
} from "@/lib/api";
import { AdminPortal, type AdminView } from "@/components/admin-portal";

const terminal = new Set(["succeeded", "failed", "cancelled"]);
function errorText(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session expired. Sign in again.";
    if (error.status === 403)
      return "You do not have permission for this action.";
    if (error.status === 404) return "That item is no longer available.";
    if (error.status === 429)
      return "Too many requests. Wait a moment and retry.";
    if (error.status >= 500) return "The service is temporarily unavailable.";
    return error.message;
  }
  return "Something went wrong.";
}
const startupRetryDelays = [150, 400, 900];
async function startupRead<T>(path: string): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await api<T>(path);
    } catch (error) {
      const transient =
        error instanceof ApiError &&
        (error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504);
      if (!transient || attempt >= startupRetryDelays.length) throw error;
      await new Promise((resolve) => setTimeout(resolve, startupRetryDelays[attempt]));
    }
  }
}
function Status({ value }: { value: string }) {
  return (
    <span className={`badge ${value.replaceAll("_", "-")}`}>
      <span aria-hidden="true" className="dot" />
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Workspace({
  initialView,
}: {
  initialView: "dashboard" | "chat" | "documents" | AdminView;
}) {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity>();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [mobile, setMobile] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteCollectionOpen, setDeleteCollectionOpen] = useState(false);
  const [deleteCollectionConfirmation, setDeleteCollectionConfirmation] = useState("");
  const [roleChanging, setRoleChanging] = useState(false);
  const membership =
    identity?.memberships.find(
      (x) =>
        collections.find((c) => c.id === collectionId)?.tenant_id ===
        x.tenant_id,
    ) ?? identity?.memberships[0];
  async function load() {
    try {
      const me = await startupRead<Identity>("/auth/me");
      setIdentity(me);
      const groups = (
        await Promise.all(
          me.memberships.map((m) =>
            startupRead<Collection[]>(`/collections?tenant_id=${m.tenant_id}`),
          ),
        )
      ).flat();
      setCollections(groups);
      const saved = sessionStorage.getItem("collection");
      setCollectionId(
        groups.some((c) => c.id === saved) ? saved! : groups[0]?.id || "",
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        const returnTo = `${window.location.pathname}${window.location.search}`;
        window.location.replace(`/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
        return;
      }
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (collectionId) sessionStorage.setItem("collection", collectionId);
  }, [collectionId]);
  useEffect(() => {
    const adminView = (["members", "invitations", "audit", "analytics"] as string[]).includes(initialView);
    if (identity && adminView && !identity.memberships.some((item) => ["owner", "admin"].includes(item.role))) {
      router.replace("/dashboard" as "/chat");
    }
  }, [identity, initialView, router]);
  async function logout() {
    try {
      await endSession();
    } finally {
      router.push("/login" as "/");
      router.refresh();
    }
  }
  async function selectDemoRole(role: "owner" | "admin" | "editor" | "viewer") {
    if (!membership || roleChanging) return;
    setRoleChanging(true);
    setError("");
    try {
      await changeDemoRole(membership.tenant_id, role);
      window.location.reload();
    } catch (e) {
      setError(errorText(e));
      setRoleChanging(false);
    }
  }
  async function deleteCurrentCollection() {
    if (!collectionId) return;
    try {
      await api(`/collections/${collectionId}`, { method: "DELETE" });
      const remaining = collections.filter((collection) => collection.id !== collectionId);
      setCollections(remaining);
      setCollectionId(remaining[0]?.id ?? "");
      setDeleteCollectionOpen(false);
      setDeleteCollectionConfirmation("");
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (loading)
    return (
      <main className="loading-shell" aria-busy="true">
        <div className="skeleton sidebar-skeleton" />
        <div className="skeleton content-skeleton" />
        <span className="sr-only">Loading workspace</span>
      </main>
    );
  return (
    <div className="app-shell">
      <header className="mobile-header">
        <button
          className="icon-button"
          aria-label="Open navigation"
          onClick={() => setMobile(true)}
        >
          ☰
        </button>
        <span className="brand">Atlas</span>
        <span className="avatar">{membership?.role[0].toUpperCase()}</span>
      </header>
      {mobile && (
        <button
          className="scrim"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <aside
        className={`sidebar ${mobile ? "open" : ""}`}
        aria-label="Primary navigation"
      >
        <div className="brand-row">
          <span className="brand-mark small">A</span>
          <span>
            <b>Atlas</b>
            <small>Knowledge workspace</small>
          </span>
          <button
            className="close-nav"
            aria-label="Close navigation"
            onClick={() => setMobile(false)}
          >
            ×
          </button>
        </div>
        <label className="select-label" htmlFor="collection">
          Collection
        </label>
        <select
          id="collection"
          value={collectionId}
          onChange={(e) => setCollectionId(e.target.value)}
        >
          {collections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {!collections.length && (
          <div className="sidebar-empty">No collections yet.</div>
        )}
        {membership && ["owner", "admin"].includes(membership.role) && (
          <div className="collection-actions">
            <button type="button" onClick={() => setCreateOpen(true)}>New collection</button>
            {collectionId && <button className="danger" type="button" onClick={() => { setDeleteCollectionConfirmation(""); setDeleteCollectionOpen(true); }}>Delete collection</button>}
          </div>
        )}
        {identity?.demo_role_preview_enabled && membership?.real_role === "owner" && (
          <div className="demo-role-control">
            <label htmlFor="demo-role">View workspace as</label>
            <select
              id="demo-role"
              value={identity.effective_demo_role ?? "owner"}
              disabled={roleChanging}
              onChange={(event) => void selectDemoRole(event.target.value as "owner" | "admin" | "editor" | "viewer")}
            >
              <option value="owner">Owner</option>
              <option value="admin">Admin</option>
              <option value="editor">Editor</option>
              <option value="viewer">Viewer</option>
            </select>
            {(identity.effective_demo_role ?? "owner") !== "owner" && (
              <button type="button" onClick={() => void selectDemoRole("owner")} disabled={roleChanging}>
                Return to Owner
              </button>
            )}
          </div>
        )}
        <nav>
          <Link className={initialView === "dashboard" ? "active" : ""} href={"/dashboard" as "/chat"}>Overview</Link>
          <Link className={initialView === "chat" ? "active" : ""} href="/chat">
            ◫ <span>Chat</span>
          </Link>
          <Link
            className={initialView === "documents" ? "active" : ""}
            href="/documents"
          >
            ▤ <span>Documents</span>
          </Link>
          {membership && ["owner", "admin"].includes(membership.role) && (
            <>
              {!identity?.demo_role_preview_enabled && <a className={initialView === "members" ? "active" : ""} href="/admin/members">Members</a>}
              {!identity?.demo_role_preview_enabled && <a className={initialView === "invitations" ? "active" : ""} href="/admin/invitations">Invitations</a>}
              <a
                className={initialView === "audit" ? "active" : ""}
                href="/admin/audit"
              >
                Audit activity
              </a>
              <a
                className={initialView === "analytics" ? "active" : ""}
                href="/admin/analytics"
              >
                Analytics
              </a>
            </>
          )}
        </nav>
        <div className="user-card">
          <span className="avatar">{membership?.role[0].toUpperCase()}</span>
          <span>
            <b>Current user</b>
            <small>{membership?.role ?? "member"}</small>
          </span>
          <button aria-label="Log out" onClick={() => void logout()}>
            ↪
          </button>
        </div>
      </aside>
      <main className={`workspace ${initialView === "chat" ? "chat-workspace" : ""}`} id="main-content">
        {identity?.effective_demo_role && identity.effective_demo_role !== "owner" && (
          <div className="demo-role-banner" role="status">
            <strong>Viewing as {identity.effective_demo_role[0].toUpperCase() + identity.effective_demo_role.slice(1)}</strong>
            <span>Your owner identity stays active while permissions match this role.</span>
            <button type="button" onClick={() => void selectDemoRole("owner")} disabled={roleChanging}>Return to Owner</button>
          </div>
        )}
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {(
          ["members", "invitations", "audit", "analytics"] as string[]
        ).includes(initialView) &&
        membership &&
        ["owner", "admin"].includes(membership.role) ? (
          <AdminPortal
            view={initialView as AdminView}
            tenantId={membership.tenant_id}
            collections={collections}
          />
        ) : !collections.length ? (
          <EmptyCollections
            admin={
              identity?.memberships.some((m) =>
                ["owner", "admin"].includes(m.role),
              ) ?? false
            }
            onCreate={() => setCreateOpen(true)}
          />
        ) : initialView === "dashboard" ? (
          <Dashboard collectionId={collectionId} collection={collections.find((item) => item.id === collectionId)!} admin={!!membership && ["owner", "admin"].includes(membership.role)} />
        ) : initialView === "chat" ? (
          <Chat collectionId={collectionId} />
        ) : (
          <Documents
            collectionId={collectionId}
            role={
              collections.find((c) => c.id === collectionId)?.access_role ??
              "viewer"
            }
          />
        )}
      </main>
      {createOpen && identity && (
        <CreateCollection
          tenant={
            identity.memberships.find((m) =>
              ["owner", "admin"].includes(m.role),
            )?.tenant_id ?? ""
          }
          onClose={() => setCreateOpen(false)}
          onCreated={(c) => {
            setCollections((x) => [...x, c]);
            setCollectionId(c.id);
            setCreateOpen(false);
          }}
        />
      )}
      {deleteCollectionOpen && (
        <Dialog title="Delete collection" onClose={() => { setDeleteCollectionOpen(false); setDeleteCollectionConfirmation(""); }}>
          <p>Delete <strong>{collections.find((collection) => collection.id === collectionId)?.name}</strong> and all of its documents, conversations, and indexed content? This cannot be undone.</p>
          <label>Type {collections.find((collection) => collection.id === collectionId)?.name} to confirm<input value={deleteCollectionConfirmation} onChange={(event) => setDeleteCollectionConfirmation(event.target.value)} autoComplete="off" /></label>
          <div className="dialog-actions">
            <button type="button" onClick={() => { setDeleteCollectionOpen(false); setDeleteCollectionConfirmation(""); }}>Cancel</button>
            <button className="button danger-fill" type="button" disabled={deleteCollectionConfirmation !== collections.find((collection) => collection.id === collectionId)?.name} onClick={() => void deleteCurrentCollection()}>Delete collection</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
function Dashboard({ collectionId, collection, admin }: { collectionId: string; collection: Collection; admin: boolean }) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  useEffect(() => { void Promise.all([api<DocumentItem[]>(`/collections/${collectionId}/documents`), api<{ conversations: Conversation[] }>(`/collections/${collectionId}/conversations`)]).then(([docs, chats]) => { setDocuments(docs); setConversations(chats.conversations); }); }, [collectionId]);
  const ready = documents.filter((item) => item.status === "available").length;
  const failed = documents.filter((item) => item.status === "failed").length;
  return <><header className="page-head"><div><p className="eyebrow">WORKSPACE OVERVIEW</p><h1>{collection.name}</h1><p>{collection.description || "Your approved knowledge at a glance."}</p></div></header><div className="metric-grid"><div className="panel metric"><span>Ready documents</span><strong>{ready}</strong></div><div className="panel metric"><span>Recent conversations</span><strong>{conversations.length}</strong></div><div className="panel metric"><span>Ingestion failures</span><strong>{failed}</strong></div><div className="panel metric"><span>Collection access</span><strong className="role-metric">{collection.access_role}</strong></div></div><section className="panel dashboard-panel"><h2>Continue working</h2><p>Ask evidence-grounded questions or keep this collection’s source material current.</p><div className="dashboard-actions"><Link className="button primary" href="/chat">Open chat</Link><Link className="button" href="/documents">Manage documents</Link>{admin && <Link className="button" href="/admin/analytics">Organization analytics</Link>}</div></section></>;
}
function EmptyCollections({
  admin,
  onCreate,
}: {
  admin: boolean;
  onCreate(): void;
}) {
  return (
    <section className="empty">
      <div className="empty-icon">◇</div>
      <h1>No collections available</h1>
      <p>
        {admin
          ? "Create a collection to organize trusted documents."
          : "Ask an administrator to grant access to a collection."}
      </p>
      {admin && (
        <button className="button primary" onClick={onCreate}>
          Create collection
        </button>
      )}
    </section>
  );
}
function Dialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose(): void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    ref.current?.querySelector<HTMLElement>("input,button")?.focus();
  }, []);
  return (
    <dialog ref={ref} onCancel={onClose}>
      <div className="dialog-head">
        <h2>{title}</h2>
        <button aria-label="Close dialog" onClick={onClose}>
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
function CreateCollection({
  tenant,
  onClose,
  onCreated,
}: {
  tenant: string;
  onClose(): void;
  onCreated(c: Collection): void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  return (
    <Dialog title="Create collection" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const created = await api<Collection>("/collections", {
              method: "POST",
              body: JSON.stringify({ tenant_id: tenant, name }),
            });
            onCreated(created);
            onClose();
          } catch (x) {
            setError(errorText(x));
          }
        }}
      >
        <label>
          Name
          <input
            autoComplete="off"
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary">Create</button>
        </div>
      </form>
    </Dialog>
  );
}

function Documents({
  collectionId,
  role,
}: {
  collectionId: string;
  role: string;
}) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [selected, setSelected] = useState<DocumentItem>();
  const [upload, setUpload] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const reload = async () => {
    try {
      setDocs(
        await api<DocumentItem[]>(`/collections/${collectionId}/documents`),
      );
    } catch (e) {
      setError(errorText(e));
    }
  };
  useEffect(() => {
    void reload();
  }, [collectionId]);
  return (
    <>
      <header className="page-head">
        <div>
          <p className="eyebrow">KNOWLEDGE BASE</p>
          <h1>Documents</h1>
          <p>Manage indexed sources and monitor their lifecycle.</p>
        </div>
        {role !== "viewer" && (
          <button className="button primary" onClick={() => setUpload(true)}>
            ＋ Upload document
          </button>
        )}
      </header>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!!docs.length && <div className="filter-bar" role="search"><label>Search documents<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filename" /></label><label>Status<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option>{Array.from(new Set(docs.map((doc) => doc.status))).map((value) => <option key={value}>{value}</option>)}</select></label></div>}
      {!docs.length ? (
        <section className="empty panel">
          <div className="empty-icon">▤</div>
          <h2>No documents yet</h2>
          <p>
            {role === "viewer"
              ? "Ask a collection manager or administrator to add trusted documents."
              : "Upload a PDF or DOCX to make its knowledge searchable."}
          </p>
          {role !== "viewer" && (
            <button className="button primary" onClick={() => setUpload(true)}>
              Upload document
            </button>
          )}
        </section>
      ) : (
        <section className="panel table-panel">
          <table>
            <caption className="sr-only">Documents in this collection</caption>
            <thead>
              <tr>
                <th>Document</th>
                <th>Status</th>
                <th>Active version</th>
                <th>Updated</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {docs.filter((doc) => (statusFilter === "all" || doc.status === statusFilter) && (doc.filename ?? "").toLowerCase().includes(search.toLowerCase())).map((d) => (
                <tr key={d.id}>
                  <td>
                    <b>{d.filename || "Processing upload"}</b>
                    <small>
                      {d.content_type?.includes("pdf") ? "PDF" : "DOCX"}
                    </small>
                  </td>
                  <td>
                    <Status value={d.status} />
                  </td>
                  <td>
                    {d.active_version_number
                      ? `v${d.active_version_number}`
                      : "Not active"}
                  </td>
                  <td>{new Date(d.updated_at).toLocaleDateString()}</td>
                  <td>
                    <button
                      className="link-button"
                      onClick={() => setSelected(d)}
                    >
                      View details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {upload && (
        <Upload
          collectionId={collectionId}
          onClose={() => setUpload(false)}
          onDone={() => {
            setUpload(false);
            void reload();
          }}
        />
      )}
      {selected && (
        <DocumentDetails
          document={selected}
          role={role}
          onClose={() => setSelected(undefined)}
          onChange={() => void reload()}
        />
      )}
    </>
  );
}
type UploadItem = { id: string; file: File; status: string; error?: string; jobId?: string };
const MAX_BATCH_FILES = 20, MAX_FILE_BYTES = 20 * 1024 * 1024, MAX_BATCH_BYTES = 100 * 1024 * 1024, UPLOAD_CONCURRENCY = 3;

function Upload({
  collectionId,
  onClose,
  onDone,
  replacement,
}: {
  collectionId: string;
  onClose(): void;
  onDone(): void;
  replacement?: string;
}) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [metadata, setMetadata] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  function addFiles(files: File[]) {
    setError("");
    const accepted = replacement ? files.slice(0, 1) : files;
    if (accepted.length + items.length > (replacement ? 1 : MAX_BATCH_FILES)) return setError(`Select no more than ${replacement ? 1 : MAX_BATCH_FILES} files.`);
    const seen = new Set(items.map((x) => `${x.file.name}:${x.file.size}:${x.file.lastModified}`));
    const next: UploadItem[] = [];
    for (const file of accepted) {
      const signature = `${file.name}:${file.size}:${file.lastModified}`;
      if (seen.has(signature)) { setError("Duplicate files were ignored."); continue; }
      seen.add(signature);
      const validType = file.name.toLowerCase().endsWith(".pdf") || file.name.toLowerCase().endsWith(".docx");
      next.push({ id: crypto.randomUUID(), file, status: !validType ? "invalid type" : file.size > MAX_FILE_BYTES ? "too large" : "queued", error: !validType ? "Only PDF and DOCX files are supported." : file.size > MAX_FILE_BYTES ? "File exceeds the 20 MB limit." : undefined });
    }
    if ([...items, ...next].reduce((sum, x) => sum + x.file.size, 0) > MAX_BATCH_BYTES) return setError("The batch exceeds the 100 MB total limit.");
    setItems((current) => [...current, ...next]);
  }
  async function poll(id: string, job: string) {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const result = await api<{ status: string; error_message: string | null }>(`/processing-jobs/${job}`);
      setItems((current) => current.map((x) => x.id === id ? { ...x, status: result.status, error: result.error_message ?? undefined } : x));
      if (terminal.has(result.status)) return result.status === "succeeded";
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("Processing is taking longer than expected.");
  }
  async function uploadOne(item: UploadItem) {
    setItems((current) => current.map((x) => x.id === item.id ? { ...x, status: "uploading", error: undefined } : x));
    const body = new FormData(); body.set("file", item.file); if (metadata.trim()) body.set("metadata", metadata);
    try {
      const path = replacement ? `/collections/${collectionId}/documents/${replacement}/versions` : `/collections/${collectionId}/documents`;
      const result = await api<{ job_id: string }>(path, { method: "POST", body, headers: { "idempotency-key": key() } });
      setItems((current) => current.map((x) => x.id === item.id ? { ...x, status: "queued", jobId: result.job_id } : x));
      return await poll(item.id, result.job_id);
    } catch (caught) {
      setItems((current) => current.map((x) => x.id === item.id ? { ...x, status: "failed", error: errorText(caught) } : x));
      return false;
    }
  }
  async function start() {
    if (metadata.trim()) { try { JSON.parse(metadata); } catch { return setError("Metadata must be valid JSON."); } }
    const queue = items.filter((x) => x.status === "queued" || x.status === "failed");
    if (!queue.length) return;
    setRunning(true); let cursor = 0;
    const results: boolean[] = [];
    async function worker() { while (cursor < queue.length) { const item = queue[cursor++]; results.push(await uploadOne(item)); } }
    await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, queue.length) }, worker));
    setRunning(false);
    if (results.every(Boolean)) onDone();
    else setError(`${results.filter(Boolean).length} file(s) succeeded and ${results.filter((value) => !value).length} failed. Successful documents were kept; retry failed files individually.`);
  }
  return (
    <Dialog
      title={replacement ? "Upload replacement" : "Upload document"}
      onClose={onClose}
    >
      <form onSubmit={(event) => { event.preventDefault(); void start(); }}>
        <label className="drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(Array.from(event.dataTransfer.files)); }}>
          <strong>{replacement ? "Choose a replacement" : "Drop PDF or DOCX files here"}</strong>
          <span>or select files · {replacement ? "one file" : `${MAX_BATCH_FILES} files / 100 MB per batch`}</span>
          <input
            type="file"
            multiple={!replacement}
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.currentTarget.value = ""; }}
          />
        </label>
        {!!items.length && <ul className="upload-queue" aria-label="Upload queue">{items.map((item) => <li key={item.id}>
          <span><strong>{item.file.name}</strong><small>{(item.file.size / 1024 / 1024).toFixed(1)} MB</small></span>
          <Status value={item.status} />
          {item.error && <small className="field-error">{item.error}</small>}
          {!running && ["queued", "failed", "invalid type", "too large"].includes(item.status) && <button type="button" aria-label={`Remove ${item.file.name}`} onClick={() => setItems((current) => current.filter((x) => x.id !== item.id))}>Remove</button>}
          {!running && item.status === "failed" && <button type="button" onClick={() => { setItems((current) => current.map((x) => x.id === item.id ? { ...x, status: "queued", error: undefined } : x)); }}>Retry</button>}
        </li>)}</ul>}
        <label>
          Metadata <span className="optional">optional JSON</span>
          <textarea
            placeholder='{"department":"Operations","tags":["policy"]}'
            value={metadata}
            onChange={(e) => setMetadata(e.target.value)}
          />
        </label>
        {running && <div className="progress" aria-live="polite"><span className="spinner" /> Uploading up to three files at a time</div>}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="button primary"
            disabled={running || !items.some((x) => x.status === "queued" || x.status === "failed")}
          >
            {replacement ? "Replace" : `Upload ${items.filter((x) => x.status === "queued" || x.status === "failed").length || ""} file(s)`}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function DocumentDetails({
  document,
  role,
  onClose,
  onChange,
}: {
  document: DocumentItem;
  role: string;
  onClose(): void;
  onChange(): void;
}) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [replace, setReplace] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void api<Version[]>(
      `/collections/${document.collection_id}/documents/${document.id}/versions`,
    )
      .then(setVersions)
      .catch((e) => setError(errorText(e)));
  }, [document]);
  async function action(kind: "reindex" | "delete") {
    if (busy) return;
    setBusy(true);
    try {
      await api(
        `/collections/${document.collection_id}/documents/${document.id}${kind === "reindex" ? "/reindex" : ""}`,
        {
          method: kind === "delete" ? "DELETE" : "POST",
          headers:
            kind === "reindex" ? { "idempotency-key": key() } : undefined,
        },
      );
      onChange();
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={document.filename || "Document details"} onClose={onClose}>
      <div className="detail-grid">
        <div>
          <span>Status</span>
          <Status value={document.status} />
        </div>
        <div>
          <span>Active version</span>
          <b>
            {document.active_version_number
              ? `Version ${document.active_version_number}`
              : "None"}
          </b>
        </div>
        <div>
          <span>Active generation</span>
          <code>{document.active_generation_id?.slice(0, 8) ?? "None"}</code>
        </div>
      </div>
      <h3>Version history</h3>
      <ol className="versions">
        {versions.map((v) => (
          <li key={v.id}>
            <div>
              <b>Version {v.version_number}</b> · {v.filename}
              <small>
                {(v.size_bytes / 1024).toFixed(1)} KB · {v.id}
              </small>
            </div>
            <Status value={v.active ? "active" : v.status} />
            {v.failure_category && (
              <p>
                Processing failed safely. The prior active version remains
                available.
              </p>
            )}
          </li>
        ))}
      </ol>
      {error && (
        <p role="alert" className="field-error">
          {error}
        </p>
      )}
      <div className="dialog-actions split">
        {["manager", "admin", "owner"].includes(role) && (
          <button className="danger" onClick={() => setConfirm(true)}>
            Delete
          </button>
        )}
        <span />
        {role !== "viewer" && (
          <>
            <button onClick={() => setReplace(true)}>Replace</button>
            <button
              className="button primary"
              onClick={() => void action("reindex")}
            >
              Reindex
            </button>
          </>
        )}
      </div>
      {replace && (
        <Upload
          collectionId={document.collection_id}
          replacement={document.id}
          onClose={() => setReplace(false)}
          onDone={() => {
            setReplace(false);
            onChange();
          }}
        />
      )}
      {confirm && (
        <Dialog title="Delete document?" onClose={() => setConfirm(false)}>
          <p>
            Permanently delete <strong>{document.filename || "this document"}</strong>? This irreversible action removes the source and every retrieval index. Historical citations remain only as redacted deleted-source notices.
          </p>
          <label>Type DELETE to confirm<input autoComplete="off" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          <div className="dialog-actions">
            <button onClick={() => setConfirm(false)}>Cancel</button>
            <button
              className="button danger-fill"
              disabled={confirmation !== "DELETE" || busy}
              onClick={() => void action("delete")}
            >
              Delete document
            </button>
          </div>
        </Dialog>
      )}
    </Dialog>
  );
}

function Chat({ collectionId }: { collectionId: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [current, setCurrent] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [citation, setCitation] = useState<Citation>();
  const [conversationToDelete, setConversationToDelete] = useState<Conversation>();
  const answerRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const [showScrollLatest, setShowScrollLatest] = useState(false);
  function scrollToLatest(behavior: ScrollBehavior = "smooth") {
    const element = messagesRef.current;
    if (!element) return;
    nearBottomRef.current = true;
    setShowScrollLatest(false);
    element.scrollTo({ top: element.scrollHeight, behavior });
  }
  function trackMessageScroll() {
    const element = messagesRef.current;
    if (!element) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
    nearBottomRef.current = nearBottom;
    setShowScrollLatest(!nearBottom);
  }
  async function loadConversations() {
    try {
      const data = await api<{ conversations: Conversation[] }>(
        `/collections/${collectionId}/conversations`,
      );
      setConversations(data.conversations);
      const saved = sessionStorage.getItem(`conversation:${collectionId}`);
      const id =
        saved && data.conversations.some((c) => c.id === saved)
          ? saved
          : data.conversations[0]?.id || "";
      setCurrent(id);
    } catch (e) {
      setError(errorText(e));
    }
  }
  useEffect(() => {
    void loadConversations();
  }, [collectionId]);
  useEffect(() => {
    nearBottomRef.current = true;
    setShowScrollLatest(false);
    if (!current) {
      setMessages([]);
      return;
    }
    sessionStorage.setItem(`conversation:${collectionId}`, current);
    void api<{ messages: Message[] }>(
      `/collections/${collectionId}/conversations/${current}/messages?limit=100`,
    )
      .then((x) => setMessages(x.messages))
      .catch((e) => setError(errorText(e)));
  }, [current, collectionId]);
  useEffect(() => {
    if (nearBottomRef.current) {
      requestAnimationFrame(() => scrollToLatest("auto"));
    } else if (messages.length || pending) {
      setShowScrollLatest(true);
    }
  }, [messages, pending]);
  async function create() {
    try {
      const c = await api<Conversation>(
        `/collections/${collectionId}/conversations`,
        { method: "POST" },
      );
      setConversations((x) => [c, ...x]);
      setCurrent(c.id);
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function removeConversation() {
    if (!conversationToDelete) return;
    try {
      await api(
        `/collections/${collectionId}/conversations/${conversationToDelete.id}`,
        { method: "DELETE" },
      );
      const remaining = conversations.filter(
        (conversation) => conversation.id !== conversationToDelete.id,
      );
      setConversations(remaining);
      if (current === conversationToDelete.id) {
        setCurrent(remaining[0]?.id ?? "");
        setMessages([]);
      }
      setConversationToDelete(undefined);
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (pending || !query.trim() || !current) return;
    const text = query.trim();
    setQuery("");
    setPending(true);
    setError("");
    setMessages((x) => [
      ...x,
      {
        id: key(),
        sequence_number: 999,
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
        citations: [],
      },
    ]);
    try {
      const result = await api<Turn>(
        `/collections/${collectionId}/conversations/${current}/messages`,
        {
          method: "POST",
          headers: { "idempotency-key": key() },
          body: JSON.stringify({ query: text, top_k: 8 }),
        },
      );
      const content =
        result.deterministic_message ||
        result.clarification_question ||
        result.answer?.answer ||
        "No answer was returned.";
      const citations = result.answer?.citations || [];
      setMessages((x) => [
        ...x,
        {
          id: result.assistant_message_id,
          sequence_number: 1000,
          role: "assistant",
          content,
          created_at: new Date().toISOString(),
          citations,
          answer_status: result.clarification_question
            ? "clarification_required"
            : result.answer?.status,
          rewriting_applied: result.rewriting_applied,
        },
      ]);
      requestAnimationFrame(() => answerRef.current?.focus());
    } catch (e) {
      setError(
        `${errorText(e)} Your question was not duplicated; you can retry.`,
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="chat-layout">
      <aside className="conversation-list">
        <div>
          <h2>Conversations</h2>
          <button aria-label="New conversation" onClick={() => void create()}>
            ＋
          </button>
        </div>
        {conversations.map((c, i) => (
          <div className={`conversation-item ${current === c.id ? "selected" : ""}`} key={c.id}>
            <button className="conversation-select" onClick={() => setCurrent(c.id)}>
              <b>{i === 0 ? "Latest conversation" : `Conversation ${conversations.length - i}`}</b>
              <small>{new Date(c.updated_at ?? c.created_at).toLocaleDateString()}</small>
            </button>
            <button className="conversation-delete" aria-label={`Delete ${i === 0 ? "latest conversation" : `conversation ${conversations.length - i}`}`} onClick={() => setConversationToDelete(c)}>×</button>
          </div>
        ))}
        {!conversations.length && <p>No conversations yet.</p>}
      </aside>
      <section className="chat-main">
        <header className="page-head compact">
          <div>
            <p className="eyebrow">GROUNDED ASSISTANT</p>
            <h1>Ask your knowledge base</h1>
          </div>
          <button className="button" onClick={() => void create()}>
            ＋ New chat
          </button>
        </header>
        <div className="messages" aria-live="polite" ref={messagesRef} onScroll={trackMessageScroll}>
          {!current ? (
            <div className="empty">
              <div className="empty-icon">✦</div>
              <h2>Start a conversation</h2>
              <p>
                Create a chat, then ask a question grounded in this collection.
              </p>
              <button className="button primary" onClick={() => void create()}>
                New conversation
              </button>
            </div>
          ) : !messages.length ? (
            <div className="chat-welcome">
              <h2>What would you like to know?</h2>
              <p>Answers use only authorized, active document versions.</p>
            </div>
          ) : (
            messages.map((m, i) => (
              <article
                key={m.id}
                className={`message ${m.role} ${m.answer_status || ""}`}
                ref={
                  i === messages.length - 1 && m.role === "assistant"
                    ? answerRef
                    : undefined
                }
                tabIndex={
                  i === messages.length - 1 && m.role === "assistant"
                    ? -1
                    : undefined
                }
              >
                <span className="message-role">
                  {m.role === "user" ? "You" : "Atlas"}
                </span>
                {m.answer_status && m.answer_status !== "answered" && (
                  <strong className="answer-state">
                    {m.answer_status === "clarification_required"
                      ? "Clarification needed"
                      : m.answer_status === "insufficient_context"
                        ? "Not enough document context"
                        : "Sources conflict"}
                  </strong>
                )}
                {m.rewriting_applied && (
                  <small className="rewrite-note">
                    Follow-up interpreted using this conversation
                  </small>
                )}
                <p>{m.content}</p>
                {m.citations.length > 0 && (
                  <div className="citation-row" aria-label="Citations">
                    {m.citations.map((c) => (
                      <button
                        key={c.citation_number}
                        onClick={() => setCitation(c)}
                        aria-label={`Open citation ${c.citation_number}`}
                      >
                        [{c.citation_number}]{" "}
                        {c.document_name || "Deleted source"}
                      </button>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && m.answer_status === "answered" && (
                  <FeedbackControls
                    collectionId={collectionId}
                    conversationId={current}
                    messageId={m.id}
                  />
                )}
              </article>
            ))
          )}
          {pending && (
            <div className="message assistant pending">
              <span className="spinner" />
              <span>Finding grounded evidence…</span>
            </div>
          )}
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
        </div>
        {showScrollLatest && (
          <button className="scroll-to-latest" type="button" onClick={() => scrollToLatest()}>
            Scroll to latest
          </button>
        )}
        <form className="composer" onSubmit={send}>
          <label className="sr-only" htmlFor="question">
            Ask a question
          </label>
          <textarea
            id="question"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              current
                ? "Ask a question about your documents…"
                : "Create a conversation first"
            }
            disabled={!current}
            maxLength={8000}
          />
          <button
            className="send"
            aria-label="Send question"
            disabled={pending || !query.trim() || !current}
          >
            ↑
          </button>
          <small>
            {pending
              ? "This turn is processing. Other navigation remains available."
              : "Enter to add context · Answers include validated sources"}
          </small>
        </form>
      </section>
      {citation && (
        <CitationDrawer
          citation={citation}
          collectionId={collectionId}
          onClose={() => setCitation(undefined)}
        />
      )}
      {conversationToDelete && (
        <Dialog title="Delete conversation" onClose={() => setConversationToDelete(undefined)}>
          <p>Delete this conversation and its complete message history? This cannot be undone.</p>
          <div className="dialog-actions">
            <button type="button" onClick={() => setConversationToDelete(undefined)}>Cancel</button>
            <button className="button danger-fill" type="button" onClick={() => void removeConversation()}>Delete conversation</button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function FeedbackControls({
  collectionId,
  conversationId,
  messageId,
}: {
  collectionId: string;
  conversationId: string;
  messageId: string;
}) {
  const [rating, setRating] = useState<"helpful" | "not_helpful">();
  const [reason, setReason] = useState("incorrect");
  const [status, setStatus] = useState("");
  async function submit(next: "helpful" | "not_helpful") {
    try {
      await api(
        `/collections/${collectionId}/conversations/${conversationId}/messages/${messageId}/feedback`,
        {
          method: "PUT",
          body: JSON.stringify({
            rating: next,
            reason: next === "not_helpful" ? reason : null,
          }),
        },
      );
      setRating(next);
      setStatus("Feedback saved.");
    } catch (error) {
      setStatus(errorText(error));
    }
  }
  return (
    <div className="feedback" aria-label="Answer feedback">
      <span>Was this answer helpful?</span>
      <button
        aria-pressed={rating === "helpful"}
        onClick={() => void submit("helpful")}
      >
        Helpful
      </button>
      <button
        aria-pressed={rating === "not_helpful"}
        onClick={() => void submit("not_helpful")}
      >
        Not helpful
      </button>
      {rating === "not_helpful" && (
        <label>
          Reason
          <select value={reason} onChange={(event) => setReason(event.target.value)}>
            <option value="incorrect">Incorrect</option>
            <option value="incomplete">Incomplete</option>
            <option value="irrelevant_sources">Irrelevant sources</option>
            <option value="citation_problem">Citation problem</option>
            <option value="outdated_source">Outdated source</option>
            <option value="other">Other</option>
          </select>
        </label>
      )}
      {status && <small role="status">{status}</small>}
    </div>
  );
}
function CitationDrawer({
  citation,
  collectionId,
  onClose,
}: {
  citation: Citation;
  collectionId: string;
  onClose(): void;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => ref.current?.focus(), []);
  const source =
    citation.document_id && citation.document_version_id
      ? `/api/backend/collections/${collectionId}/documents/${citation.document_id}/versions/${citation.document_version_id}/source${citation.page_number ? `#page=${citation.page_number}` : ""}`
      : null;
  return (
    <aside
      className="drawer"
      aria-label={`Citation ${citation.citation_number}`}
      tabIndex={-1}
      ref={ref}
    >
      <div className="drawer-head">
        <div>
          <p className="eyebrow">SOURCE [{citation.citation_number}]</p>
          <h2>{citation.document_name || "Deleted source"}</h2>
        </div>
        <button aria-label="Close citation" onClick={onClose}>
          ×
        </button>
      </div>
      {citation.source_status === "deleted" ? (
        <div className="tombstone">
          <b>This source was deleted</b>
          <p>Its private excerpt and identifiers are no longer available.</p>
        </div>
      ) : (
        <>
          <dl>
            <div>
              <dt>Version ID</dt>
              <dd>
                <code>{citation.document_version_id}</code>
              </dd>
            </div>
            <div>
              <dt>Location</dt>
              <dd>
                {citation.page_number
                  ? `Page ${citation.page_number}`
                  : citation.section_path || "Document section"}
              </dd>
            </div>
            <div>
              <dt>Offsets</dt>
              <dd>
                {citation.start_offset}–{citation.end_offset}
              </dd>
            </div>
          </dl>
          <h3>Exact excerpt</h3>
          <blockquote>{citation.source_excerpt}</blockquote>
          {Object.keys(citation.metadata || {}).length > 0 && (
            <>
              <h3>Metadata</h3>
              <dl>
                {Object.entries(citation.metadata).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{Array.isArray(v) ? v.join(", ") : String(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          {source && (
            <a
              className="button primary wide"
              href={source}
              target="_blank"
              rel="noreferrer"
            >
              Open source{" "}
              {citation.page_number ? `at page ${citation.page_number}` : ""}
            </a>
          )}
        </>
      )}
    </aside>
  );
}
