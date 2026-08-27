import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
test("login and session-expired states are responsive and accessible",async({page})=>{await page.goto("/");await expect(page.getByRole("heading",{name:/grounded in evidence/i})).toBeVisible();await expect(page.getByRole("link",{name:/continue/i})).toBeVisible();expect((await new AxeBuilder({page}).analyze()).violations).toEqual([]);await page.goto("/session-expired");await expect(page.getByRole("heading",{name:"Session expired"})).toBeVisible();});
