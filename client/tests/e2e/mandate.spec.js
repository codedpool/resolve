const { expect, test } = require("@playwright/test");

const API = process.env.E2E_API_URL || "http://localhost:8000";

test("set the mandate with a password, then decide an image approval", async ({ page, request }) => {
  const health = await request.get(`${API}/health`).catch(() => null);
  test.skip(!health || !health.ok(), "The server is not reachable, so this flow cannot run.");

  const email = `mandate-${Date.now()}@example.com`;
  const password = "correct-horse";

  // Set up a case with an image approval straight through the API.
  await request.post(`${API}/auth/signup`, { data: { email, password, language: "en" } });
  const login = await (await request.post(`${API}/auth/login`, { data: { email, password } })).json();
  const auth = { Authorization: `Bearer ${login.access_token}` };
  const made = await (await request.post(`${API}/cases`, { headers: auth })).json();
  const evidence = await (
    await request.post(`${API}/cases/${made.id}/evidence`, {
      headers: auth,
      multipart: { type: "document", file: { name: "receipt.png", mimeType: "image/png", buffer: Buffer.from("png") } },
    })
  ).json();
  await request.post(`${API}/cases/${made.id}/evidence/${evidence.id}/approve-vision`, { headers: auth });

  // Sign in through the page and open the case without a full reload, so the token stays in memory.
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Cases" }).first().click();
  await page.getByRole("link", { name: `Case ${made.id.slice(0, 8)}` }).click();

  // The image approval names the image and says where it goes.
  await expect(page.getByRole("heading", { name: "Send this image to a vision model?" })).toBeVisible();
  await expect(page.getByText(/Your uploaded document/)).toBeVisible();
  await expect(page.getByText(/will be sent to a vision model/)).toBeVisible();

  // The mandate needs a password before it is saved.
  await page.getByRole("button", { name: "Set up permission" }).click();
  await page.getByRole("button", { name: "Read it back" }).click();
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await page.getByRole("button", { name: "Save permission" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Password").fill(password);
  await dialog.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(/Mandate saved/)).toBeVisible();

  // The password is still fresh, so the approval goes through without asking again.
  await page.getByRole("button", { name: "Send the image" }).click();
  await expect(page.getByText("You approved this.")).toBeVisible();

  // The decision shows up in the inbox, and the nav count drops after reading it.
  await page.getByRole("link", { name: /Messages/ }).click();
  await expect(page.getByText("You approved a request.")).toBeVisible();
  await page.getByRole("button", { name: "Mark as read" }).click();
  await expect(page.getByText("You have no unread messages.")).toBeVisible();
});
