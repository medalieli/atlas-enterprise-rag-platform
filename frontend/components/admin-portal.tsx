"use client";
/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */

import { useEffect, useState } from "react";
import { api, type Collection } from "@/lib/api";

export type AdminView = "members" | "invitations" | "audit" | "analytics";
type Member = {
  id: string;
  email: string | null;
  display_name: string | null;
  role: "owner" | "admin" | "member";
  status: string;
  version: number;
};
type Invitation = {
  id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
};
type Audit = {
  id: string;
  actor_id: string | null;
  action: string;
  target_type: string;
  outcome: string;
  created_at: string;
};
type Analytics = {
  period_days: number;
  total_users: number;
  active_users: number;
  users_by_role: Record<string, number>;
  pending_invitations: number;
  collections: number;
  active_documents: number;
  archived_documents: number;
  chunks: number;
  questions: number;
  answer_statuses: Record<string, number>;
  positive_feedback: number;
  negative_feedback: number;
  positive_feedback_rate: number | null;
  ingestion_failures: number;
  median_response_ms: number | null;
  p95_response_ms: number | null;
};

export function AdminPortal({
  view,
  tenantId,
  collections,
}: {
  view: AdminView;
  tenantId: string;
  collections: Collection[];
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [events, setEvents] = useState<Audit[]>([]);
  const [analytics, setAnalytics] = useState<Analytics>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [link, setLink] = useState("");
  const [grantMember, setGrantMember] = useState("");
  const [grantCollection, setGrantCollection] = useState("");
  const [grantRole, setGrantRole] = useState("viewer");
  async function load() {
    setError("");
    try {
      if (view === "members")
        setMembers(
          (
            await api<{ items: Member[] }>(
              `/organizations/${tenantId}/members?limit=100`,
            )
          ).items,
        );
      if (view === "invitations")
        setInvitations(
          (
            await api<{ items: Invitation[] }>(
              `/organizations/${tenantId}/invitations?limit=100`,
            )
          ).items,
        );
      if (view === "audit")
        setEvents(
          (
            await api<{ items: Audit[] }>(
              `/organizations/${tenantId}/audit-events?limit=100`,
            )
          ).items,
        );
      if (view === "analytics")
        setAnalytics(
          await api<Analytics>(`/organizations/${tenantId}/analytics?days=30`),
        );
    } catch {
      setError("Administration data could not be loaded.");
    }
  }
  useEffect(() => {
    void load();
  }, [view, tenantId]);
  async function update(
    member: Member,
    next: Partial<Pick<Member, "role" | "status">>,
  ) {
    if (!confirm("Apply this authorization change immediately?")) return;
    try {
      await api(`/organizations/${tenantId}/members/${member.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...next, expected_version: member.version }),
      });
      setNotice("Membership updated.");
      void load();
    } catch {
      setError("Membership could not be updated.");
    }
  }
  if (view === "members")
    return (
      <AdminPage
        title="Organization members"
        description="Roles and suspensions apply on the next request."
        error={error}
        notice={notice}
      >
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id}>
                  <td>{m.display_name || m.email || "OIDC principal"}</td>
                  <td>
                    <select
                      aria-label={`Role for ${m.email || m.id}`}
                      value={m.role}
                      onChange={(e) =>
                        void update(m, {
                          role: e.target.value as Member["role"],
                        })
                      }
                    >
                      <option>owner</option>
                      <option>admin</option>
                      <option>member</option>
                    </select>
                  </td>
                  <td>{m.status}</td>
                  <td>
                    <button
                      onClick={() =>
                        void update(m, {
                          status:
                            m.status === "active" ? "suspended" : "active",
                        })
                      }
                    >
                      {m.status === "active" ? "Suspend" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!members.length && <p>No members found.</p>}
        </div>
        <p className="muted">
          Collection access is managed per collection by managers and
          organization administrators. {collections.length} collection(s)
          available.
        </p>
        <form
          className="panel admin-form"
          onSubmit={async (event) => {
            event.preventDefault();
            try {
              await api(
                `/organizations/${tenantId}/collections/${grantCollection}/grants/${grantMember}`,
                { method: "PUT", body: JSON.stringify({ role: grantRole }) },
              );
              setNotice("Collection access updated.");
            } catch {
              setError("Collection access could not be updated.");
            }
          }}
        >
          <label>
            Member
            <select
              required
              value={grantMember}
              onChange={(event) => setGrantMember(event.target.value)}
            >
              <option value="">Select member</option>
              {members
                .filter((member) => member.role === "member")
                .map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.display_name || member.email || "OIDC principal"}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Collection
            <select
              required
              value={grantCollection}
              onChange={(event) => setGrantCollection(event.target.value)}
            >
              <option value="">Select collection</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Access
            <select
              value={grantRole}
              onChange={(event) => setGrantRole(event.target.value)}
            >
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              <option value="manager">Manager</option>
            </select>
          </label>
          <button className="button primary">Save access</button>
        </form>
      </AdminPage>
    );
  if (view === "invitations")
    return (
      <AdminPage
        title="Invitations"
        description="Tokens are stored only as hashes and each link is shown once."
        error={error}
        notice={notice}
      >
        <form
          className="panel admin-form"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const result = await api<{ invitation_link: string }>(
                `/organizations/${tenantId}/invitations`,
                {
                  method: "POST",
                  body: JSON.stringify({ email, role, grants: [] }),
                },
              );
              setLink(`${window.location.origin}${result.invitation_link}`);
              setEmail("");
              setNotice(
                "Invitation created. Copy this link now; it will not be shown again.",
              );
              void load();
            } catch {
              setError("Invitation could not be created.");
            }
          }}
        >
          <label>
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Organization role
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <button className="button primary">Create invitation</button>
        </form>
        {link && (
          <div className="alert success" role="status">
            <label>
              One-time invitation link
              <input
                readOnly
                value={link}
                onFocus={(e) => e.currentTarget.select()}
              />
            </label>
          </div>
        )}
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Expires</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invitations.map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td>
                  <td>{i.role}</td>
                  <td>{i.status}</td>
                  <td>{new Date(i.expires_at).toLocaleString()}</td>
                  <td>
                    {i.status === "pending" && (
                      <button
                        onClick={async () => {
                          if (!confirm("Revoke this invitation?")) return;
                          try {
                            await api(
                              `/organizations/${tenantId}/invitations/${i.id}`,
                              { method: "DELETE" },
                            );
                            setNotice("Invitation revoked.");
                            void load();
                          } catch {
                            setError("Invitation could not be revoked.");
                          }
                        }}
                      >
                        Revoke
                      </button>
                    )}
                    {["pending", "expired"].includes(i.status) && (
                      <button
                        onClick={async () => {
                          try {
                            const replacement = await api<{
                              invitation_link: string;
                            }>(
                              `/organizations/${tenantId}/invitations/${i.id}/replace`,
                              { method: "POST" },
                            );
                            setLink(
                              `${window.location.origin}${replacement.invitation_link}`,
                            );
                            setNotice("Replacement created. Copy the link now.");
                            void load();
                          } catch {
                            setError("Invitation could not be replaced.");
                          }
                        }}
                      >
                        Replace
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AdminPage>
    );
  if (view === "audit")
    return (
      <AdminPage
        title="Audit activity"
        description="Tenant-scoped, append-only business events exclude private content."
        error={error}
        notice={notice}
      >
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Target</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td>{e.action}</td>
                  <td>{e.target_type}</td>
                  <td>{e.outcome}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!events.length && <p>No activity in this page.</p>}
        </div>
      </AdminPage>
    );
  const cards = analytics
    ? [
        ["Active users", analytics.active_users],
        ["Pending invitations", analytics.pending_invitations],
        ["Collections", analytics.collections],
        ["Active documents", analytics.active_documents],
        ["Indexed chunks", analytics.chunks],
        ["Questions (30 days)", analytics.questions],
        ["Positive feedback", analytics.positive_feedback],
        ["Ingestion failures", analytics.ingestion_failures],
      ]
    : [];
  return (
    <AdminPage
      title="Product analytics"
      description="Bounded, privacy-safe organization aggregates for the last 30 days."
      error={error}
      notice={notice}
    >
      <div className="metric-grid">
        {cards.map(([label, value]) => (
          <div className="panel metric" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      {analytics && (
        <div className="panel">
          <h2>Response quality</h2>
          <p>
            Positive feedback rate:{" "}
            {analytics.positive_feedback_rate === null
              ? "Unavailable"
              : `${Math.round(analytics.positive_feedback_rate * 100)}%`}
          </p>
          <p>
            Median / p95 latency:{" "}
            {analytics.median_response_ms === null
              ? "Unavailable"
              : `${Math.round(analytics.median_response_ms)} / ${Math.round(analytics.p95_response_ms!)} ms`}
          </p>
        </div>
      )}
    </AdminPage>
  );
}

function AdminPage({
  title,
  description,
  error,
  notice,
  children,
}: {
  title: string;
  description: string;
  error: string;
  notice: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <header className="page-head">
        <div>
          <p className="eyebrow">ENTERPRISE ADMINISTRATION</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </header>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert success" role="status">
          {notice}
        </div>
      )}
      {children}
    </>
  );
}
