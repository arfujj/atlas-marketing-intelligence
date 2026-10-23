import { expect, test } from "@playwright/test";

const PAGES = [
  ["/halden", "Performance"],
  ["/halden/changes", "Changes"],
  ["/halden/evidence", "Evidence"],
  ["/halden/decision", "Decision: next quarter's $500K"],
  ["/ga4", "Google Merchandise Store"],
  ["/criteo", "Criteo incrementality test"],
] as const;

for (const width of [1400, 390]) {
  test(`every page renders without errors or page-level horizontal scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    for (const [path, title] of PAGES) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      await expect(page.getByText("Data unavailable")).toHaveCount(0);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${path} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
    }
    expect(errors).toEqual([]);
  });
}

test("re-optimising a smaller budget spends exactly that budget", async ({ page }) => {
  await page.goto("/halden/decision");
  const budget = page.getByLabel("Quarterly budget");
  await budget.fill("300000");
  await page.getByRole("button", { name: "Re-optimise" }).click();
  await expect(page.getByRole("button", { name: "Re-optimise" })).toBeDisabled();
  const rows = page.locator("table.data").first().locator("tbody tr");
  await expect(rows).toHaveCount(6);
  const recommended = await rows.evaluateAll((trs) =>
    trs.map((tr) => tr.querySelectorAll("td")[2].firstChild?.textContent ?? ""),
  );
  const total = recommended.reduce((s, t) => s + Number(t.replace(/[$K,]/g, "")) * (t.includes("K") ? 1000 : 1), 0);
  expect(total).toBeCloseTo(300_000, -3);
});

test("evidence hides the truth until asked", async ({ page }) => {
  await page.goto("/halden/evidence");
  await expect(page.getByText("True ROI", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Reveal truth" }).click();
  await expect(page.getByText("True ROI", { exact: true })).toBeVisible();
  await expect(page.getByText("What each method's plan would really earn")).toBeVisible();
});

test("allowing underspend never spends more than the budget and says how much it keeps", async ({ page }) => {
  await page.goto("/halden/decision");
  await expect(page.getByText("The budget is larger than the model can spend profitably")).toBeVisible();
  await page.getByLabel("Allow spending less than the budget").check();
  await page.getByRole("button", { name: "Re-optimise" }).click();
  await expect(page.getByText(/The most profitable plan spends \$[\d.]+K of the \$500K available/)).toBeVisible();
});

test("the analyst answers a suggested question with cited facts and links to the page", async ({ page }) => {
  await page.goto("/ga4");
  await page.getByRole("button", { name: "Ask ATLAS" }).click();
  const panel = page.getByRole("dialog", { name: "Ask ATLAS" });
  await panel.getByRole("button", { name: "Why did revenue fall last week?" }).click();
  await expect(panel.getByText(/Site-wide conversion failure/)).toBeVisible();
  await expect(panel.getByText(/anomaly-/).first()).toBeVisible();
  await panel.getByLabel("Your question").fill("How should we spend $400K?");
  await panel.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(panel.getByText(/For a \$400K quarter/)).toBeVisible();
  await panel.getByRole("link", { name: "Open Decision →" }).last().click();
  await expect(page).toHaveURL(/\/halden\/decision/);
});
