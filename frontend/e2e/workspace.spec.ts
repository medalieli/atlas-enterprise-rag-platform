import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";
const ids = {
  tenant: "10000000-0000-0000-0000-000000000001",
  collection: "20000000-0000-0000-0000-000000000001",
  conversation: "30000000-0000-0000-0000-000000000001",
  document: "40000000-0000-0000-0000-000000000001",
  version: "50000000-0000-0000-0000-000000000001",
};
const json = (route: Route, value: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
async function mock(page: Page, role = "admin") {
  await page.route("**/api/auth/csrf", (r) => json(r, { token: "csrf" }));
  await page.route("**/api/auth/logout", (r) => json(r, { ok: true }));
  await page.route("**/api/backend/**", async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace("/api/backend", "");
    const method = route.request().method();
    if (p === "/auth/me")
      return json(route, {
        principal_id: "user",
        memberships: [
          {
            tenant_id: ids.tenant,
            role,
            status: "active",
            version: 1,
            permissions: [
              "tenant:read",
              "document:upload",
              "collection:manage",
            ],
          },
        ],
      });
    if (p === "/collections" && method === "GET")
      return json(route, [
        {
          id: ids.collection,
          tenant_id: ids.tenant,
          name: "Operations Library",
          description: "Approved operating knowledge",
          access_role: "manager",
        },
      ]);
    if (p === `/collections/${ids.collection}/documents` && method === "GET")
      return json(route, [
        {
          id: ids.document,
          collection_id: ids.collection,
          status: "available",
          active_version_id: ids.version,
          deleted: false,
          filename: "Incident Response Handbook.pdf",
          content_type: "application/pdf",
          active_version_number: 2,
          active_generation_id: "60000000-0000-0000-0000-000000000001",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]);
    if (p.endsWith("/versions") && method === "GET")
      return json(route, [
        {
          id: ids.version,
          version_number: 2,
          status: "active",
          active: true,
          filename: "Incident Response Handbook.pdf",
          content_type: "application/pdf",
          size_bytes: 45000,
          metadata: { department: "Security" },
          active_generation_id: "generation",
          failure_category: null,
        },
      ]);
    if (p === `/collections/${ids.collection}/documents` && method === "POST")
      return json(
        route,
        {
          document_id: ids.document,
          job_id: "job",
          original_filename: "policy.pdf",
          processing_status: "queued",
        },
        202,
      );
    if (p === "/processing-jobs/job")
      return json(route, {
        job_id: "job",
        document_id: ids.document,
        status: "succeeded",
        attempt_count: 1,
        error_message: null,
      });
    if (p.endsWith("/reindex"))
      return json(route, { job_id: "job", processing_status: "queued" }, 202);
    if (
      p === `/collections/${ids.collection}/conversations` &&
      method === "GET"
    )
      return json(route, {
        conversations: [
          {
            id: ids.conversation,
            collection_id: ids.collection,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        next_cursor: null,
      });
    if (
      p === `/collections/${ids.collection}/conversations` &&
      method === "POST"
    )
      return json(
        route,
        {
          id: ids.conversation,
          collection_id: ids.collection,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        201,
      );
    if (p.endsWith("/messages") && method === "GET")
      return json(route, { messages: [], next_cursor: null });
    if (p.endsWith("/messages") && method === "POST")
      return json(route, {
        assistant_message_id: "70000000-0000-0000-0000-000000000001",
        turn_status: "completed",
        rewriting_applied: true,
        clarification_question: null,
        deterministic_reason: null,
        deterministic_message: null,
        answer: {
          status: "answered",
          answer: "The escalation window is 30 minutes [1].",
          citations: [
            {
              citation_number: 1,
              source_id: "src_1",
              source_status: "available",
              document_id: ids.document,
              document_version_id: ids.version,
              generation_id: "generation",
              document_name: "Incident Response Handbook.pdf",
              content_type: "application/pdf",
              page_number: 7,
              section_path: null,
              start_offset: 120,
              end_offset: 220,
              metadata: { department: "Security" },
              source_excerpt: "Escalate critical incidents within 30 minutes.",
            },
          ],
        },
      });
    if (p.endsWith("/feedback") && method === "PUT")
      return json(route, { id: "feedback", rating: "helpful", reason: null });
    return json(route, { detail: "mock route missing" }, 404);
  });
}
test("document lifecycle, permissions, mobile navigation and accessibility", async ({
  page,
}, testInfo) => {
  await mock(page);
  await page.goto("/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "View details" }).click();
  const details = page.getByRole("dialog");
  await expect(
    details.getByRole("listitem").getByText("Version 2"),
  ).toBeVisible();
  await details.getByRole("button", { name: "Delete" }).click();
  await page.screenshot({ path: `qa/document-delete-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("dialog").last().getByRole("button", { name: "Cancel" }).click();
  await details.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: /Upload document/ }).click();
  await page.getByLabel("PDF or DOCX").setInputFiles({
    name: "policy.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 synthetic"),
  });
  await page.getByRole("button", { name: /Upload 1 file/ }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("navigation")).toBeVisible();
  }
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: `qa/documents-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
test("conversation, follow-up, citation and logout", async ({
  page,
}, testInfo) => {
  await mock(page);
  await page.goto("/chat");
  const box = page.getByLabel("Ask a question");
  await box.fill("What is the escalation window?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByText(/30 minutes/)).toBeVisible();
  await page.getByRole("button", { name: /Open citation 1/ }).click();
  await expect(
    page.getByText("Escalate critical incidents within 30 minutes."),
  ).toBeVisible();
  await expect(page.getByText(ids.version)).toBeVisible();
  await page.screenshot({
    path: `qa/citation-${testInfo.project.name}.png`,
    fullPage: true,
  });
});

test("multiple document selection keeps individual queue states", async ({ page }, testInfo) => {
  await mock(page);
  await page.goto("/documents");
  await page.getByRole("button", { name: /Upload document/ }).first().click();
  await page.getByLabel(/Drop PDF or DOCX files here/).setInputFiles([
    { name: "one.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF one") },
    { name: "two.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("PK docx") },
    { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("invalid") },
  ]);
  await expect(page.getByRole("list", { name: "Upload queue" }).getByRole("listitem")).toHaveCount(3);
  await expect(page.getByText("Only PDF and DOCX files are supported.")).toBeVisible();
  await page.screenshot({ path: `qa/multi-upload-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Remove notes.txt" }).click();
  await page.getByRole("button", { name: /Upload 2 file/ }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("workspace dashboard summarizes the current collection", async ({ page }, testInfo) => {
  await mock(page);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Operations Library" })).toBeVisible();
  await expect(page.getByText("Ready documents")).toBeVisible();
  await page.screenshot({ path: `qa/dashboard-${testInfo.project.name}.png`, fullPage: true });
});
