import { expect, test } from "@playwright/test";

const storyTabs = (page: import("@playwright/test").Page) =>
  page.getByRole("tablist", { name: "Stories" }).getByRole("tab");

test("every story tab loads and skip shows the final state", async ({ page }) => {
  await page.goto("/");
  await expect(storyTabs(page).first()).toBeVisible();
  const count = await storyTabs(page).count();
  for (let i = 0; i < count; i++) {
    await storyTabs(page).nth(i).click();
    await page.getByRole("button", { name: /Skip to results/ }).click();
    await expect(page.getByRole("status")).toHaveText(/(\d+) of \1 mutants finished/);
  }
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("nothing autoplays", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /^Play/ })).toBeVisible();
    await expect(page.getByRole("status")).toHaveText(/(\d+) of \1 mutants finished/);
  });
});

test("tab order reaches Pause/Play third, not the tab panel", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("tablist", { name: "Stories" })).toBeVisible();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /^(Pause|Play)/ })).toBeFocused();
});
