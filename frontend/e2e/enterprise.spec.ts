import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const tenant = "10000000-0000-0000-0000-000000000001",
  collection = "20000000-0000-0000-0000-000000000001",
  member = "30000000-0000-0000-0000-000000000001";
const json = (route: Route, value: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
async function mock(page: Page) {
  await page.route("**/api/auth/csrf", (r) => json(r, { token: "csrf" }));
  await page.route("**/api/backend/**", (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname.replace("/api/backend", "");
    if (path === "/auth/me")
      return json(route, {
        principal_id: "owner",
        memberships: [
          {
            tenant_id: tenant,
            role: "owner",
            status: "active",
            version: 1,
            permissions: ["tenant:read", "membership:manage"],
          },
        ],
      });
    if (path === "/collections")
      return json(route, [
        {
          id: collection,
          tenant_id: tenant,
          name: "Policies",
          description: null,
          access_role: "manager",
        },
      ]);
    if (path.includes("/members") && route.request().method() === "GET")
      return json(route, {
        items: [
          {
            id: member,
            email: "viewer@example.test",
            display_name: "Synthetic Viewer",
            role: "member",
            status: "active",
            version: 1,
          },
        ],
        next_cursor: null,
      });
    if (path.includes("/grants/") && route.request().method() === "PUT")
      return json(route, {
        id: "grant",
        collection_id: collection,
        membership_id: member,
        role: "viewer",
      });
    if (path.endsWith("/invitations") && route.request().method() === "GET")
      return json(route, { items: [], next_cursor: null });
    if (path.endsWith("/invitations") && route.request().method() === "POST")
      return json(
        route,
        {
          id: "invite",
          status: "pending",
          expires_at: new Date().toISOString(),
          invitation_link: "/invitations/accept?token=one-time-synthetic",
        },
        201,
      );
    if (path.endsWith("/audit-events"))
      return json(route, {
        items: [
          {
            id: "event",
            actor_id: "owner",
            action: "collection_grant.changed",
            target_type: "collection_grant",
            outcome: "success",
            created_at: new Date().toISOString(),
          },
        ],
        next_cursor: null,
      });
    if (path.includes("/analytics"))
      return json(route, {
        period_days: 30,
        total_users: 2,
        active_users: 2,
        users_by_role: { owner: 1, member: 1 },
        pending_invitations: 0,
        collections: 1,
        active_documents: 2,
        archived_documents: 0,
        chunks: 12,
        questions: 4,
        answer_statuses: { answered: 4 },
        positive_feedback: 1,
        negative_feedback: 0,
        positive_feedback_rate: 1,
        ingestion_failures: 0,
        median_response_ms: 120,
        p95_response_ms: 240,
      });
    return json(route, { detail: "missing" }, 404);
  });
}

test("owner administers members, invitations, audit and analytics accessibly", async ({
  page,
}, testInfo) => {
  await mock(page);
  await page.goto("/admin/members");
  await expect(
    page.getByRole("heading", { name: "Organization members" }),
  ).toBeVisible();
  await page.getByLabel("Member").selectOption(member);
  await page.locator(".admin-form select").nth(1).selectOption(collection);
  await page.getByRole("button", { name: "Save access" }).click();
  await expect(page.getByText("Collection access updated.")).toBeVisible();
  await page.screenshot({ path: `qa/members-${testInfo.project.name}.png`, fullPage: true });
  await page.goto("/admin/invitations");
  await page.getByLabel("Email").fill("invitee@example.test");
  await page.getByRole("button", { name: "Create invitation" }).click();
  await expect(page.getByLabel("One-time invitation link")).toHaveValue(
    /one-time-synthetic/,
  );
  await page.screenshot({ path: `qa/invitations-${testInfo.project.name}.png`, fullPage: true });
  await page.goto("/admin/audit");
  await expect(page.getByText("collection_grant.changed")).toBeVisible();
  await page.screenshot({ path: `qa/audit-${testInfo.project.name}.png`, fullPage: true });
  await page.goto("/admin/analytics");
  await expect(page.getByText("Active users")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Answer latency" })).toBeVisible();
  await expect(page.getByText("0.1s", { exact: true })).toBeVisible();
  await expect(page.getByText("0.2s", { exact: true })).toBeVisible();
  await expect(page.getByText(/Positive feedback rate|Unavailable/)).toHaveCount(0);
  await page.screenshot({ path: `qa/analytics-${testInfo.project.name}.png`, fullPage: true });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
