import { expect, test } from "@playwright/test";

test("real Docker workspace cleanup is idempotent and audited", async ({ page, baseURL }) => {
  await page.goto(`${baseURL}/api/auth/login?returnTo=%2Fdashboard`);
  await page.getByText("Development role preview").click();
  await expect(page.getByLabel("View workspace as")).toBeVisible();
  const result = await page.evaluate(async () => {
    const csrf = await fetch("/api/auth/csrf").then((response) => response.json()) as { token: string };
    const me = await fetch("/api/backend/auth/me").then((response) => response.json()) as { memberships: Array<{ tenant_id: string }> };
    const tenant = me.memberships[0].tenant_id;
    const headers = { "content-type": "application/json", "x-csrf-token": csrf.token };
    const suffix = crypto.randomUUID().slice(0, 8);
    async function createCollection(name: string) {
      return fetch("/api/backend/collections", { method: "POST", headers, body: JSON.stringify({ tenant_id: tenant, name: `${name}-${suffix}` }) }).then((response) => response.json()) as Promise<{ id: string }>;
    }
    const removed = await createCollection("cleanup");
    const retained = await createCollection("retained");
    async function upload(collection: string, filename: string) {
      const form = new FormData();
      form.set("file", new File(["%PDF-1.4\n%%EOF"], filename, { type: "application/pdf" }));
      return fetch(`/api/backend/collections/${collection}/documents`, { method: "POST", headers: { "x-csrf-token": csrf.token }, body: form });
    }
    const removedUpload = await upload(removed.id, "removed.pdf");
    const retainedUpload = await upload(retained.id, "retained.pdf");
    const conversation = await fetch(`/api/backend/collections/${removed.id}/conversations`, { method: "POST", headers }).then((response) => response.json()) as { id: string };
    const conversationDelete = await fetch(`/api/backend/collections/${removed.id}/conversations/${conversation.id}`, { method: "DELETE", headers });
    const conversationReplay = await fetch(`/api/backend/collections/${removed.id}/conversations/${conversation.id}`, { method: "DELETE", headers });
    const collectionDelete = await fetch(`/api/backend/collections/${removed.id}`, { method: "DELETE", headers });
    const collectionReplay = await fetch(`/api/backend/collections/${removed.id}`, { method: "DELETE", headers });
    const collections = await fetch(`/api/backend/collections?tenant_id=${tenant}`).then((response) => response.json()) as Array<{ id: string }>;
    const retainedDocuments = await fetch(`/api/backend/collections/${retained.id}/documents`).then((response) => response.json()) as Array<{ id: string }>;
    const audit = await fetch(`/api/backend/organizations/${tenant}/audit-events?limit=100`).then((response) => response.json()) as { items: Array<{ action: string; target_id: string }> };
    await fetch(`/api/backend/collections/${retained.id}`, { method: "DELETE", headers });
    return {
      removedUpload: removedUpload.status,
      retainedUpload: retainedUpload.status,
      conversationDelete: conversationDelete.status,
      conversationReplay: conversationReplay.status,
      collectionDelete: collectionDelete.status,
      collectionReplay: collectionReplay.status,
      removedAbsent: !collections.some((item) => item.id === removed.id),
      retainedPresent: collections.some((item) => item.id === retained.id) && retainedDocuments.length === 1,
      conversationAudit: audit.items.some((item) => item.action === "conversation.deleted" && item.target_id === conversation.id),
      collectionAudit: audit.items.some((item) => item.action === "collection.deleted" && item.target_id === removed.id),
    };
  });
  expect(result).toEqual({
    removedUpload: 202,
    retainedUpload: 202,
    conversationDelete: 204,
    conversationReplay: 204,
    collectionDelete: 204,
    collectionReplay: 204,
    removedAbsent: true,
    retainedPresent: true,
    conversationAudit: true,
    collectionAudit: true,
  });
});
