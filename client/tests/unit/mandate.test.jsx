import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { MandateCard } from "../../src/components/MandateCard";
import { StepUpDialog } from "../../src/components/StepUpDialog";

function reply(status, payload) {
  return { ok: status < 400, status, json: async () => payload };
}

const saved = {
  id: "m1",
  version: 1,
  goal: "refund",
  disclosure: ["order_id", "amount", "order_date", "issue_summary", "consumer_name"],
  call_limit_seconds: 600,
  expires_at: "2026-12-27T00:00:00Z",
  revoked_at: null,
  active: true,
};

let calls;

beforeEach(() => {
  calls = [];
  let mandatePosts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path, options) => {
      calls.push({ path, method: options.method, body: options.body ? JSON.parse(options.body) : null });
      if (path === "/cases/c1/mandate" && options.method === "GET") return reply(200, { mandate: null });
      if (path === "/cases/c1/mandate") {
        mandatePosts += 1;
        if (mandatePosts === 1) return reply(403, { error: { code: "step_up_required", message: "Enter your password again" } });
        return reply(200, { mandate: saved });
      }
      if (path === "/auth/step-up") return reply(200, { step_up_until: "2026-11-27T00:10:00Z" });
      return reply(404, { error: { code: "not_found", message: "Not found" } });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openReadBack() {
  render(
    <>
      <MandateCard caseId="c1" />
      <StepUpDialog />
    </>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Set up permission" }));
  fireEvent.click(screen.getByRole("button", { name: "Read it back" }));
}

it("ticks the default disclosure fields and leaves the rest off", async () => {
  render(<MandateCard caseId="c1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Set up permission" }));
  expect(screen.getByLabelText("Order number")).toBeChecked();
  expect(screen.getByLabelText("Your name")).toBeChecked();
  expect(screen.getByLabelText("Your phone number")).not.toBeChecked();
  expect(screen.getByLabelText("Your address")).not.toBeChecked();
});

it("cannot be saved until every read-back line is ticked", async () => {
  await openReadBack();
  const save = screen.getByRole("button", { name: "Save permission" });
  expect(save).toBeDisabled();
  const boxes = screen.getAllByRole("checkbox");
  boxes.slice(0, -1).forEach((box) => fireEvent.click(box));
  expect(save).toBeDisabled();
  fireEvent.click(boxes[boxes.length - 1]);
  expect(save).toBeEnabled();
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
});

it("opens the password dialog and retries the save once after the password", async () => {
  await openReadBack();
  screen.getAllByRole("checkbox").forEach((box) => fireEvent.click(box));
  fireEvent.click(screen.getByRole("button", { name: "Save permission" }));

  const dialog = await screen.findByRole("dialog");
  // The save is held back: no success message while the password is missing.
  expect(screen.queryByText(/Mandate saved/)).not.toBeInTheDocument();

  fireEvent.change(within(dialog).getByLabelText("Password"), { target: { value: "correct-horse" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));

  expect(await screen.findByText(/Mandate saved/)).toBeInTheDocument();
  const order = calls.filter((call) => call.method === "POST").map((call) => call.path);
  expect(order).toEqual(["/cases/c1/mandate", "/auth/step-up", "/cases/c1/mandate"]);
  const body = calls.filter((call) => call.path === "/cases/c1/mandate" && call.method === "POST")[1].body;
  expect(body).toMatchObject({
    action: "grant",
    goal: "refund",
    call_limit_seconds: 600,
    expires_in_days: 30,
    limits: { accept_partial: false },
  });
  expect(body.disclosure).toEqual(["order_id", "amount", "order_date", "issue_summary", "consumer_name"]);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("does not save when the password step is cancelled", async () => {
  await openReadBack();
  screen.getAllByRole("checkbox").forEach((box) => fireEvent.click(box));
  fireEvent.click(screen.getByRole("button", { name: "Save permission" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Your mandate was not changed"));
  expect(calls.filter((call) => call.path === "/cases/c1/mandate" && call.method === "POST")).toHaveLength(1);
});
