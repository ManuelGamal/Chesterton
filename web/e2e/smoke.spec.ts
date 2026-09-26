import { expect, test } from "@playwright/test";

const storyTabs = (page: import("@playwright/test").Page) =>
  page.getByRole("tablist", { name: "Stories" }).getByRole("tab");

test("every story opens on its answer, finished, and can replay", async ({ page }) => {
  await page.goto("/");
  await expect(storyTabs(page)).toHaveText([/Wrong patch, caught/, /The correct fix/, /Checking our own tests/]);
  for (let i = 0; i < 3; i++) {
    await storyTabs(page).nth(i).click();
    const card = page.getByRole("region", { name: "What Chesterton found" });
    await expect(card).toBeVisible();
    await expect(page.getByRole("status")).toHaveText(/(\d+) of \1 changes tested/);
    await page.getByRole("button", { name: /^Replay/ }).click();
    await page.getByRole("button", { name: /Skip to results/ }).click();
    await expect(page.getByRole("status")).toHaveText(/(\d+) of \1 changes tested/);
  }
});

test("a capsule opens its change, and Escape closes it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("region", { name: "Mutants by hunk" }).getByRole("button", { name: /missed/ }).first().click();
  const detail = page.getByRole("region", { name: "The selected change" });
  await expect(detail).toContainText(/missed: the \d+ tests? that runs? this line still pass/);
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("nothing moves until the viewer acts", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /^Replay/ })).toBeVisible();
    const before = await page.getByRole("status").textContent();
    await page.waitForTimeout(800);
    await expect(page.getByRole("status")).toHaveText(before ?? "");
  });
});
