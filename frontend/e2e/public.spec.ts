import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
test("dedicated login is responsive, accessible, and has no password form", async ({ page }, testInfo) => {
  await page.goto("/login?returnTo=%2Fdocuments");
  await expect(page.getByRole("heading", { name: /trusted decisions/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Enter Atlas/ })).toHaveAttribute("href", /returnTo=%2Fdocuments/);
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByText(/never asks for or stores your password/i)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `qa/login-${testInfo.project.name}.png`, fullPage: true });
});

test("anonymous invitation is secured before sign-in without leaking its token", async ({ page }) => {
  const syntheticToken = `synthetic-invitation-capability-${"x".repeat(40)}`;
  const exchange = page.waitForResponse((response) => response.url().endsWith("/api/invitations/continue"));
  await page.goto(`/invitations/accept#token=${syntheticToken}`);
  const exchangeResponse = await exchange;
  expect(exchangeResponse.status()).toBe(200);
  await expect(page).toHaveURL("http://127.0.0.1:3100/invitations/accept");
  await expect(page.getByRole("link", { name: "Sign in to accept invitation" })).toBeVisible();
  expect(await page.evaluate(() => ({ local: Object.values(localStorage), session: Object.values(sessionStorage) }))).toEqual({ local: [], session: [] });
  expect(await page.content()).not.toContain(syntheticToken);
  await page.reload();
  await expect(page.getByRole("link", { name: "Sign in to accept invitation" })).toBeVisible();
});
