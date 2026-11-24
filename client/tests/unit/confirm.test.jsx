import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { ConfirmationCard } from "../../src/components/ConfirmationCard";
import { applyCorrection } from "../../src/components/facts";
import { IntakeChat } from "../../src/components/IntakeChat";

const fact = {
  id: "1",
  field: "amount",
  value: "around 1200",
  phrase: "around 1200",
  certainty: "approximate",
  confirmation_state: "confirmed",
  version: 1,
};

it("does not accept a fact on a timer", () => {
  vi.useFakeTimers();
  const onAccept = vi.fn();
  render(<ConfirmationCard fact={fact} onAccept={onAccept} onEdit={vi.fn()} />);
  vi.advanceTimersByTime(30000);
  expect(onAccept).not.toHaveBeenCalled();
  vi.useRealTimers();
});

it("shows the value and the original phrase", () => {
  render(<ConfirmationCard fact={fact} onAccept={vi.fn()} onEdit={vi.fn()} />);
  expect(screen.getByText("around 1200")).toBeInTheDocument();
  expect(screen.getByText("You said “around 1200”.")).toBeInTheDocument();
});

it("edit creates a new version and clears the confirmation", () => {
  const onEdit = vi.fn();
  render(<ConfirmationCard fact={fact} onAccept={vi.fn()} onEdit={onEdit} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Edit amount"), { target: { value: "1250" } });
  fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
  expect(onEdit).toHaveBeenCalledWith(fact, "1250");
  const next = applyCorrection([fact], fact, { id: "2", version: 2, confirmation_state: "unconfirmed" }, "1250");
  render(<ConfirmationCard fact={next[0]} onAccept={vi.fn()} onEdit={vi.fn()} />);
  expect(screen.getByText("1250")).toBeInTheDocument();
  expect(screen.getByText("unconfirmed")).toBeInTheDocument();
  expect(screen.getByText("Version 2")).toBeInTheDocument();
});

it("sends narration-done only once", () => {
  const send = vi.fn();
  render(<IntakeChat caseId="case-1" send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  const doneCalls = send.mock.calls.filter((call) => String(call[0]).endsWith("/narration-done"));
  expect(doneCalls).toHaveLength(1);
});

const doneCalls = [];
const server = setupServer(
  http.post("http://localhost:3000/cases/:id/narration-done", () => {
    doneCalls.push("done");
    return HttpResponse.json({ ok: true });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it("mocks narration-done with the service worker", async () => {
  process.env.NEXT_PUBLIC_API_URL = "http://localhost:3000";
  doneCalls.length = 0;
  render(<IntakeChat caseId="case-9" />);
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  await vi.waitFor(() => expect(doneCalls).toEqual(["done"]));
  delete process.env.NEXT_PUBLIC_API_URL;
});
