import { expect, test } from "playwright/test";

// The browser suite performs exactly one data-entry round trip per scenario:
// fill the form once, submit once, verify the displayed result; plus one 422
// scenario that must clear the stale result.
test.describe("duty review console", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  async function weekdayState(row, index) {
    const cls = await row.locator("button").nth(index).evaluate(
      (el) => getComputedStyle(el).backgroundColor,
    );
    return cls !== "rgb(255, 255, 255)";
  }

  async function setWeekday(row, index, selected) {
    if ((await weekdayState(row, index)) !== selected) {
      await row.locator("button").nth(index).click();
    }
  }

  test("single entry: cross-midnight night + special, exact result shown", async ({ page }) => {
    // --- one and only data entry ---
    await page.locator('input[type="datetime-local"]').nth(0).fill("2026-09-25T22:00");
    await page.locator('input[type="datetime-local"]').nth(1).fill("2026-09-26T06:00");
    await page.locator('input[type="number"]').first().fill("1000");

    const nightRow = page.getByTestId("rule-row-0");
    await nightRow.locator("input").first().fill("night");
    for (let i = 0; i < 7; i++) await setWeekday(nightRow, i, true);
    await nightRow.locator('input[type="time"]').nth(0).fill("22:00");
    await nightRow.locator('input[type="time"]').nth(1).fill("06:00");
    await nightRow.locator('input[type="number"]').nth(0).fill("1");
    await nightRow.locator('input[type="number"]').nth(1).fill("13000");

    await page.getByRole("button", { name: "+ 添加规则" }).click();
    const spRow = page.getByTestId("rule-row-1");
    await spRow.locator("input").first().fill("special");
    for (let i = 0; i < 7; i++) await setWeekday(spRow, i, i === 5); // Sat only
    await spRow.locator('input[type="time"]').nth(0).fill("00:00");
    await spRow.locator('input[type="time"]').nth(1).fill("04:00");
    await spRow.locator('input[type="number"]').nth(0).fill("2");
    await spRow.locator('input[type="number"]').nth(1).fill("20000");

    // --- one submit ---
    await page.getByTestId("submit").click();

    // --- result display ---
    await expect(page.getByTestId("result-panel")).toBeVisible();
    await expect(page.getByTestId("error-panel")).toHaveCount(0);

    // Exact total: 240 min @13000 + 240 min @20000 at 1000 cents/h = 13200/1
    await expect(page.getByTestId("total-fraction")).toContainText("13200/1");

    const rows = page.getByTestId(/^seg-row-/);
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("09-25 22:00");
    await expect(rows.nth(0)).toContainText("09-26 00:00");
    await expect(rows.nth(0)).toContainText("night");
    await expect(rows.nth(1)).toContainText("special");
    await expect(rows.nth(1)).toContainText("240");
    await expect(rows.nth(2)).toContainText("night");

    await page.getByTestId("seg-1").hover();
    await expect(page.getByTestId("hover-info")).toContainText("special");
    await expect(page.getByTestId("hover-info")).toContainText("20000");
  });

  test("422 over-36h interval clears the previously displayed result", async ({ page }) => {
    // First produce a valid result with one rule entry.
    await page.locator('input[type="datetime-local"]').nth(0).fill("2026-09-23T09:00");
    await page.locator('input[type="datetime-local"]').nth(1).fill("2026-09-23T10:00");
    const row = page.getByTestId("rule-row-0");
    await setWeekday(row, 5, false); // deselect Sat; Wed remains selected
    await page.getByTestId("submit").click();
    await expect(page.getByTestId("result-panel")).toBeVisible();

    // Over-36h interval (widget accepts it; client does not pre-check the
    // cap) -> backend 422, and the stale result must be removed.
    await page.locator('input[type="datetime-local"]').nth(1).fill("2026-09-24T21:01");
    await page.getByTestId("submit").click();
    await expect(page.getByTestId("error-panel")).toBeVisible();
    await expect(page.getByTestId("error-panel")).toContainText("422");
    await expect(page.getByTestId("result-panel")).toHaveCount(0);
  });
});
