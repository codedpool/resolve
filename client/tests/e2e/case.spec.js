const { expect, test } = require("@playwright/test");

test("create a case and upload evidence", async ({ page }) => {
  const email = `case-${Date.now()}@example.com`;
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByRole("link", { name: "Cases" }).click();
  await page.getByRole("button", { name: "Open a case" }).click();
  await expect(page.getByText("Simulated resolution")).toBeVisible();
  await expect(page.getByText("intake")).toBeVisible();

  await page.getByLabel("Evidence file").setInputFiles({
    name: "receipt.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("order 12"),
  });
  await page.getByRole("button", { name: "Upload evidence" }).click();
  await expect(page.getByText("Uploaded document")).toBeVisible();
});
