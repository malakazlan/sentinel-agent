import { test, expect } from "@playwright/test";

/**
 * Drives the fraud-fp-burst scenario end-to-end against the real backend.
 *
 * Timeline: ~3-5 minutes (depends on Gemini latency). The test polls the
 * UI until each acceptance gate fires, then moves to the next.
 */
test("fraud-fp-burst pipeline produces a validated postmortem", async ({ page }) => {
  // 1) Scenarios page renders 3 cards
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Incident response scenarios" })).toBeVisible();
  await expect(page.getByText("False-positive burst on transaction classifier")).toBeVisible();
  await expect(page.getByText("Sanctions-list hallucination on PEP screener")).toBeVisible();
  await expect(page.getByText("Latency regression after model deploy")).toBeVisible();

  // 2) Click the fraud scenario card
  const fraudCard = page.locator("a", { hasText: "False-positive burst on transaction classifier" });
  await fraudCard.click();

  // 3) Wait for redirect to /incidents/<id> (the run page POSTs then redirects)
  await page.waitForURL(/\/incidents\/fraud-fp-spike-/, { timeout: 30_000 });

  // 4) Live console header renders with the actual scenario title from SSE.
  // Backend emits the scenario.title verbatim (e.g. "Fraud detection — false-positive burst");
  // match case-insensitively so the test isn't brittle to backend-side copy edits.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/false-positive/i, {
    timeout: 60_000,
  });
  // Matches both the topbar status pill and the disabled CTA button when running —
  // first() scopes to whichever Playwright resolves first (topbar in DOM order).
  await expect(page.getByText(/Pipeline running|Pipeline finished/).first()).toBeVisible();

  // 5) Stepper shows Coordinator done within first minute
  await expect(page.locator("text=Coordinator").first()).toBeVisible({ timeout: 60_000 });

  // 6) Wait for the pipeline to finish — "View postmortem →" button activates
  const viewPostmortem = page.getByRole("button", { name: /View postmortem/ });
  await expect(viewPostmortem).toBeVisible({ timeout: 8 * 60_000 });
  await expect(viewPostmortem).toBeEnabled({ timeout: 30_000 });

  // 7) Click into the postmortem
  await viewPostmortem.click();
  await page.waitForURL(/\/postmortem$/);

  // 8) Postmortem document renders with severity + electronics root cause
  await expect(page.locator("h1")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("P1").first()).toBeVisible();
  await expect(page.getByText(/electronic/i).first()).toBeVisible();

  // 9) All 9 sections rendered
  for (const label of [
    "Summary",
    "Impact",
    "Timeline",
    "Root cause",
    "Detection",
    "Resolution",
    "Action items",
    "Lessons learned",
  ]) {
    await expect(page.getByText(label).first()).toBeVisible();
  }
});
