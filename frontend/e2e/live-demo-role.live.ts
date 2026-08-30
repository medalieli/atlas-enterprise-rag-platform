import { expect, test } from "@playwright/test";

test("real OIDC owner previews backend-enforced roles", async ({ page, baseURL }) => {
  await page.goto(`${baseURL}/api/auth/login?returnTo=%2Fdashboard`);
  await expect(page.getByLabel("View workspace as")).toBeVisible();

  async function select(role: "owner" | "admin" | "editor" | "viewer") {
    await page.getByLabel("View workspace as").selectOption(role);
    await page.waitForLoadState("domcontentloaded");
    await expect(page.getByLabel("View workspace as")).toHaveValue(role);
  }

  await select("admin");
  await expect(page.getByRole("link", { name: "Analytics", exact: true })).toHaveCount(1);
  await select("editor");
  const editorCreateStatus = await page.evaluate(async () => {
    const csrf = await fetch("/api/auth/csrf").then((response) => response.json()) as { token: string };
    const me = await fetch("/api/backend/auth/me").then((response) => response.json()) as { memberships: Array<{ tenant_id: string }> };
    return (await fetch("/api/backend/collections", { method: "POST", headers: { "content-type": "application/json", "x-csrf-token": csrf.token }, body: JSON.stringify({ tenant_id: me.memberships[0].tenant_id, name: "Must not be created" }) })).status;
  });
  expect(editorCreateStatus).toBe(403);
  await select("viewer");
  const viewerUploadStatus = await page.evaluate(async () => {
    const csrf = await fetch("/api/auth/csrf").then((response) => response.json()) as { token: string };
    const me = await fetch("/api/backend/auth/me").then((response) => response.json()) as { memberships: Array<{ tenant_id: string }> };
    const collections = await fetch(`/api/backend/collections?tenant_id=${me.memberships[0].tenant_id}`).then((response) => response.json()) as Array<{ id: string }>;
    const form = new FormData();
    form.set("file", new File(["%PDF-1.4"], "forbidden.pdf", { type: "application/pdf" }));
    return (await fetch(`/api/backend/collections/${collections[0].id}/documents`, { method: "POST", headers: { "x-csrf-token": csrf.token }, body: form })).status;
  });
  expect(viewerUploadStatus).toBe(403);
  await page.getByRole("button", { name: "Return to Owner" }).first().click();
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByLabel("View workspace as")).toHaveValue("owner");
});
