import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
test("dedicated login is responsive, accessible, and has no password form", async ({ page }, testInfo) => {
  await page.goto("/login?returnTo=%2Fdocuments");
  await expect(page.getByRole("heading", { name: /answers your team can verify/i })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in to Atlas" })).toHaveAttribute("href", /returnTo=%2Fdocuments/);
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByText(/never asks for or stores your password/i)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `qa/login-${testInfo.project.name}.png`, fullPage: true });
});
