import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const tenant = "81000000-0000-0000-0000-000000000001";
const collection = "82000000-0000-0000-0000-000000000001";
const json = (route: Route, value: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

async function rolePreviewMock(page: Page) {
  let role = "owner";
  await page.route("**/api/auth/csrf", (route) => json(route, { token: "csrf" }));
  await page.route("**/api/demo-role", async (route) => {
    const requested = (await route.request().postDataJSON()) as { role: string };
    role = requested.role;
    return json(route, { effective_role: role });
  });
  await page.route("**/api/backend/**", (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/backend", "");
    if (path === "/auth/me") return json(route, {
      principal_id: "real-owner",
      demo_role_preview_enabled: true,
      effective_demo_role: role,
      memberships: [{ tenant_id: tenant, role, real_role: "owner", status: "active", version: 1, permissions: ["tenant:read"] }],
    });
    if (path === "/collections") return json(route, [{ id: collection, tenant_id: tenant, name: "Demo knowledge", description: "", access_role: role === "viewer" ? "viewer" : role === "editor" ? "editor" : "manager" }]);
    if (path.endsWith("/documents")) return json(route, []);
    if (path.endsWith("/conversations")) return json(route, { conversations: [], next_cursor: null });
    return json(route, { detail: "missing mock" }, 404);
  });
}

async function openRolePreview(page: Page) {
  const mobileNavigation = page.getByRole("button", { name: "Open navigation" });
  if ((page.viewportSize()?.width ?? 1000) <= 900) {
    await mobileNavigation.click();
    await expect(page.locator(".sidebar")).toHaveClass(/open/);
  }
  const details = page.locator(".demo-role-control");
  if (!(await details.evaluate((element: HTMLDetailsElement) => element.open))) {
    await page.getByText("Development role preview").click();
  }
}

test("owner previews every real role and returns to owner", async ({ page }, testInfo) => {
  await rolePreviewMock(page);
  await page.goto("/dashboard");
  for (const role of ["owner", "admin", "editor", "viewer"] as const) {
    await openRolePreview(page);
    await page.getByLabel("View workspace as").selectOption(role);
    await page.waitForLoadState("domcontentloaded");
    if (role === "owner") await expect(page.getByText(/Viewing as/)).toHaveCount(0);
    else {
      await expect(page.getByText(`Viewing as ${role[0].toUpperCase()}${role.slice(1)}`)).toBeVisible();
      await expect(page.getByRole("button", { name: "Return to Owner" }).first()).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "People" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Settings" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Invitations" })).toHaveCount(0);
    if (role === "owner" || role === "admin")
      await expect(page.getByRole("link", { name: "Insights", exact: true })).toHaveCount(1);
    else await expect(page.getByRole("link", { name: "Insights", exact: true })).toHaveCount(0);
    await page.screenshot({ path: `qa/demo-role-${role}-${testInfo.project.name}.png`, fullPage: true });
  }
  await page.locator(".demo-role-banner").getByRole("button", { name: "Return to Owner" }).click();
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByText(/Viewing as/)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Demo knowledge" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

async function longChatMock(page: Page) {
  const conversations = Array.from({ length: 100 }, (_, index) => ({
    id: `83000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    collection_id: collection,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  }));
  const messages = Array.from({ length: 100 }, (_, index) => ({
    id: `84000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    sequence_number: index + 1,
    role: index % 2 ? "assistant" : "user",
    content: `${index % 2 ? "A long grounded answer" : "A detailed question"} ${index}. ${"Evidence remains readable while scrolling. ".repeat(12)}`,
    created_at: new Date().toISOString(), answer_status: index % 2 ? "answered" : undefined,
    rewriting_applied: false,
    citations: index % 2 ? [{ citation_number: 1, source_id: `source-${index}`, source_status: "available", document_id: collection, document_version_id: collection, generation_id: collection, document_name: "A very long policy filename that must never cause horizontal overflow.pdf", content_type: "application/pdf", page_number: index, section_path: null, start_offset: 0, end_offset: 20, metadata: {}, source_excerpt: "Bounded cited evidence." }] : [],
  }));
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/backend", "");
    if (path === "/auth/me") return json(route, { principal_id: "user", demo_role_preview_enabled: false, effective_demo_role: null, memberships: [{ tenant_id: tenant, role: "viewer", real_role: "viewer", status: "active", version: 1, permissions: ["tenant:read"] }] });
    if (path === "/collections") return json(route, [{ id: collection, tenant_id: tenant, name: "Long chat", description: "", access_role: "viewer" }]);
    if (path.endsWith("/conversations")) return json(route, { conversations, next_cursor: null });
    if (path.includes("/messages") && route.request().method() === "GET") return json(route, { messages, next_cursor: null });
    return json(route, { detail: "missing mock" }, 404);
  });
}

test("long conversations scroll independently while composer stays visible", async ({ page }, testInfo) => {
  await longChatMock(page);
  await page.goto("/chat");
  await expect(page.getByText("A long grounded answer 99.")).toBeVisible();
  const composer = page.locator(".composer");
  const conversationList = page.locator(".conversation-list");
  const messages = page.locator(".messages");
  await expect.poll(async () => messages.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  expect(await conversationList.evaluate((element) => element.scrollHeight > element.clientHeight || element.scrollWidth > element.clientWidth)).toBe(true);
  const box = page.getByLabel("Ask a question");
  await box.fill("Draft text remains intact");
  await messages.evaluate((element) => element.scrollTo({ top: 0 }));
  await expect(page.getByRole("button", { name: "Scroll to latest" })).toBeVisible();
  await expect(box).toHaveValue("Draft text remains intact");
  const viewportHeight = await page.evaluate(() => window.visualViewport?.height ?? window.innerHeight);
  expect((await composer.boundingBox())!.y + (await composer.boundingBox())!.height).toBeLessThanOrEqual(viewportHeight + 1);
  await page.setViewportSize({ width: testInfo.project.name === "mobile" ? 390 : 900, height: 520 });
  await expect(composer).toBeVisible();
  await page.getByRole("button", { name: "Scroll to latest" }).click();
  await expect(page.getByRole("button", { name: "Scroll to latest" })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.screenshot({ path: `qa/long-chat-${testInfo.project.name}.png`, fullPage: true });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("role notice floats without displacing chat", async ({ page }) => {
  await rolePreviewMock(page);
  await page.goto("/chat");
  await openRolePreview(page);
  await page.getByLabel("View workspace as").selectOption("editor");
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByText("Viewing as Editor")).toBeVisible();
  expect(await page.locator(".demo-role-banner").evaluate((element) => getComputedStyle(element).position)).toBe("fixed");
  expect(await page.locator(".chat-layout").evaluate((element) => element.clientHeight > 0)).toBe(true);
  await expect(page.locator(".composer")).toBeVisible();
});
