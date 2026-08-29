# Post-v1 enterprise administration upgrade

This is a bounded post-v1 release, not Milestone 16. The original 15-milestone
roadmap remains complete.

## Decision and identity boundary

Tenants remain the company/organization boundary. Users are keyed only by immutable
OIDC `(issuer, subject)`; email and display name are mutable profile fields. Atlas
does not create passwords, store password hashes, reset passwords, perform MFA or
replace the IdP. A verified email is used only once to match an invitation.

Existing `admin` memberships backfill to `owner`, preserving administrator access.
Existing `editor` and `viewer` memberships backfill to `member` plus equivalent
grants on every existing tenant collection. This preserves access without widening
it. Deployment applies revision `d4e5f6a7b8c9` before new application images; the
migration is transactional, reversible and safe to repeat through Alembic.

## Permission matrices

| Organization action | Owner | Admin | Member |
| --- | ---: | ---: | ---: |
| Manage owners/admins | Yes | No | No |
| Manage members and invitations | Yes | Yes | No |
| Create/administer collections | Yes | Yes | No |
| View audit and analytics | Yes | Yes | No |
| Collection access without grant | Yes | Yes | No |

The final active owner cannot be demoted, suspended or revoked. Users cannot change
their own authorization.

| Collection action | Manager | Editor | Viewer |
| --- | ---: | ---: | ---: |
| View collection/documents, search, ask and citations | Yes | Yes | Yes |
| Upload, replace and reindex | Yes | Yes | No |
| Archive/delete documents | Yes | No | No |
| Manage collection grants | Yes | No | No |

Missing grants deny access. Cross-tenant, ungranted, revoked conversation and source
requests use the established safe `404` behavior. Access is revalidated on every
request and conversation turn.

## Invitations

Owners/admins create bounded-lifetime invitations for their own OIDC issuer. Tokens
use cryptographically random values, are shown once, never logged, and only SHA-256
hashes are stored. Acceptance requires an exact issuer and verified normalized-email
match, locks the invitation for concurrency safety, binds the immutable subject,
and rejects expiry, revocation, replacement and replay. Replacing an expired or
pending invitation invalidates its predecessor. Copy-link delivery is intentionally
the only adapter in this release; SMTP and IdP management APIs are deferred.

## Audit, feedback and analytics privacy

Tenant-scoped business events cover invitations, membership/grant changes,
collection/document administration, feedback, audit access and analytics access.
Events contain stable IDs, action/outcome, bounded reason codes, request ID and
role snapshots. They explicitly exclude document/chunk text, filenames, questions,
answers, prompts, excerpts, vectors, tokens, passwords, cookies, headers and raw
provider responses. PostgreSQL rejects direct event update/delete; tenant removal
can cascade records under an administrative data-lifecycle operation. This is
append-only application behavior, not a claim of cryptographic or external WORM
immutability. Retention follows the organization database retention policy.

One current feedback record exists per user and assistant answer. Re-submission
updates it deterministically and is audited. Feedback is evaluation/product data,
not RLHF, factual proof or automatic model training.

Analytics are owner/admin-only, tenant-filtered aggregates over at most 366 days.
Active users means active enabled memberships. Counts include roles, invitations,
collections, document lifecycle, versions/chunks, turns/statuses, feedback,
ingestion failures and available latency percentiles. Unavailable measures return
`null`, never a misleading zero. No raw private content or high-cardinality query
labels are stored.

## Deterministic onboarding behavior

Greeting/help-only English, French and Arabic messages are normalized and answered
without embedding, rewriting, reranking or generation calls and without citations.
A greeting plus a factual question still uses normal RAG. Empty collections return
machine reason `empty_collection` with zero provider calls; editors/managers see an
upload action while viewers are directed to an administrator. Nonempty collections
retain strict grounding and `insufficient_context`.

## Deferred limitations

SMTP delivery, IdP-specific management APIs, SCIM, multi-organization session
switching, external connectors, action tools, billing, general autonomous agents,
public deployment and automated learning from feedback remain explicitly deferred.

## API surface

All mutations pass through the BFF CSRF boundary. List endpoints use bounded cursor
pagination.

```text
GET/PATCH  /organizations/{tenant}/members[/{membership}]
GET/POST   /organizations/{tenant}/invitations
DELETE     /organizations/{tenant}/invitations/{invitation}
POST       /organizations/{tenant}/invitations/{invitation}/replace
POST       /invitations/accept
GET/PUT/DELETE /organizations/{tenant}/collections/{collection}/grants[/{membership}]
GET        /organizations/{tenant}/audit-events
GET        /organizations/{tenant}/analytics?days=30&collection_id=...
PUT        /collections/{collection}/conversations/{conversation}/messages/{answer}/feedback
```

## Professional workspace finishing pass

Atlas now uses a dedicated `/login` experience before any private workspace UI.
It starts the existing OIDC Authorization Code with PKCE flow and preserves a
validated relative return destination. Atlas hosts no password form, stores no
passwords or browser tokens, and ships no default identity.

The document workspace queues up to 20 PDF/DOCX files and 100 MiB per batch with
three uploads in flight; the backend retains its 20 MiB per-file bound. Per-file
validation, ingestion state, partial success, removal, and retry stay visible.

Editing a pending invitation replaces its claims and rotates its single-use token.
Removal invalidates the token, hides it from the active view, redacts email PII to
a tombstone, and preserves immutable audit history. Accepted identities are managed
through Memberships.

Audit filters cover inclusive UTC dates, actor, action, target type, and outcome.
CSV export is ordered and formula-safe, creates its own audit event, and is bounded
by `AUDIT_EXPORT_MAX_DAYS` (366), `AUDIT_EXPORT_MAX_ROWS` (10,000), and
`AUDIT_EXPORT_RATE_LIMIT_SECONDS` (30). Tokens, prompts, questions, answers, and
document content are never exported.

Atlas endpoints and the normal application database role cannot update or delete
audit history because of the append-only trigger. This does not claim a database
superuser or infrastructure owner is technically incapable of storage changes;
backups and infrastructure access controls protect that wider trust boundary.
