import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ApprovalList } from "../../src/components/ApprovalList";
import { PracticeCall } from "../../src/components/PracticeCall";
import { ApiError } from "../../src/lib/api";

const OPENING = "Hello, I am an AI assistant calling on behalf of a customer about order OD43817265. This is a simulated practice call.";

/** A scripted API. `turns` are returned one per provider turn. */
function fakeApi({ turns = [], approvals = [], endReply, startError } = {}) {
  const calls = [];
  const queue = [...turns];
  const send = vi.fn(async (path, options = {}) => {
    calls.push({ path, method: options.method || "GET", body: options.body });
    if (path === "/cases/c1/outreach/calls") {
      if (startError) throw startError;
      return { call_id: "call-1", simulated: true, sentences: [OPENING], phase: "provider_call", ended: false };
    }
    if (path === "/calls/call-1/provider-turn") {
      const next = queue.shift();
      if (next instanceof Error) throw next;
      return next;
    }
    if (path === "/calls/call-1/end") return endReply || { call_id: "call-1", state: "closed", sentences: [], phase: "summary", ended: true, approval_id: "ap-1" };
    if (path === "/approvals?case=c1") return { approvals };
    throw new Error(`unexpected ${path}`);
  });
  return { send, calls };
}

function type(text) {
  fireEvent.change(screen.getByLabelText("What the company says"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

it("asks for permission first and keeps the start button off", () => {
  const { send } = fakeApi();
  render(<PracticeCall caseId="c1" mandateActive={false} send={send} />);
  expect(screen.getByText(/Give the assistant permission above first/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start practice call" })).toBeDisabled();
  expect(send).not.toHaveBeenCalled();
});

it("starts a practice call and shows the assistant's opening line", async () => {
  const { send, calls } = fakeApi();
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  expect(await screen.findByText(OPENING)).toBeInTheDocument();
  expect(calls[0]).toMatchObject({ path: "/cases/c1/outreach/calls", method: "POST" });
  expect(screen.getByText("Practice call in progress")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "End call" })).toBeInTheDocument();
});

it("shows a start error in plain words and stays on the start screen", async () => {
  const { send } = fakeApi({ startError: new ApiError(409, "mandate_required", "A current permission from you is needed before the call") });
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not start the practice call. A current permission from you is needed before the call");
  expect(screen.getByRole("button", { name: "Start practice call" })).toBeInTheDocument();
});

it("sends each typed turn and shows the assistant's sentences as bubbles", async () => {
  const { send, calls } = fakeApi({ turns: [{ sentences: ["Could you share the reference number?", "Thank you."], phase: "provider_call", ended: false }] });
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  type("Your refund has been processed.");
  expect(await screen.findByText("Could you share the reference number?")).toBeInTheDocument();
  expect(screen.getByText("Thank you.")).toBeInTheDocument();
  expect(screen.getByText("Your refund has been processed.")).toBeInTheDocument();
  expect(screen.getByText("You, as the company")).toBeInTheDocument();
  const turn = calls.find((call) => call.path === "/calls/call-1/provider-turn");
  expect(turn.body).toEqual({ text: "Your refund has been processed." });
  await waitFor(() => expect(screen.getByLabelText("What the company says")).toHaveValue(""));
});

it("shows a held sentence plainly as a holding message", async () => {
  const held = "I will need to check that with the customer.";
  const { send } = fakeApi({ turns: [{ sentences: [held], phase: "provider_call", ended: false }] });
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  type("Please read out the OTP.");
  const bubble = (await screen.findByText(held)).closest(".bubble");
  expect(bubble).toHaveClass("bubble-held");
  expect(within(bubble).getByText("Assistant, holding")).toBeInTheDocument();
});

it("ends on an outside offer: no more turns, the reason is plain, and the summary is pointed to", async () => {
  const onChange = vi.fn();
  const { send } = fakeApi({
    turns: [{ sentences: ["I am not able to accept or counter it on my own."], phase: "summary", ended: true, end_reason: "offer_outside_mandate", approval_id: "ap-1" }],
    approvals: [{ id: "ap-1", kind: "summary", status: "pending", payload: "{}" }],
  });
  render(<PracticeCall caseId="c1" mandateActive send={send} onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  type("We can offer 2000 rupees as a final settlement.");
  expect(await screen.findByText("The call has ended")).toBeInTheDocument();
  expect(screen.getByText(/The assistant did not accept it/)).toBeInTheDocument();
  expect(screen.queryByLabelText("What the company says")).not.toBeInTheDocument();
  expect(await screen.findByText(/summary of the call is waiting for your approval/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Go to Approvals" })).toHaveAttribute("href", "#approvals");
  expect(onChange).toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Start a new practice call" })).toBeEnabled();
});

it("tells the owner when the company asked for details outside the permission", async () => {
  const { send } = fakeApi({
    turns: [{ sentences: ["I will need to check that with the customer."], phase: "provider_call", ended: false }],
    approvals: [{ id: "ap-2", kind: "disclosure", status: "pending", payload: "{}" }],
  });
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  type("Give me the phone number.");
  expect(await screen.findByText(/asked for details that are not on your permission/)).toBeInTheDocument();
});

it("ends the call with the End call button", async () => {
  const { send, calls } = fakeApi({ approvals: [{ id: "ap-1", kind: "summary", status: "pending", payload: "{}" }] });
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  fireEvent.click(screen.getByRole("button", { name: "End call" }));
  expect(await screen.findByText("The call has ended")).toBeInTheDocument();
  expect(calls.some((call) => call.path === "/calls/call-1/end" && call.method === "POST")).toBe(true);
  expect(screen.getByText(/summary of the call is waiting/)).toBeInTheDocument();
});

it("keeps what was typed when a turn fails", async () => {
  const { send } = fakeApi({ turns: [new ApiError(500, "request_failed", "Request failed")] });
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  type("Hello?");
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not send that. Your words are still in the box.");
  expect(screen.getByLabelText("What the company says")).toHaveValue("Hello?");
});

it("fills the box from an idea without sending it", async () => {
  const { send, calls } = fakeApi();
  render(<PracticeCall caseId="c1" mandateActive send={send} />);
  fireEvent.click(screen.getByRole("button", { name: "Start practice call" }));
  await screen.findByText(OPENING);
  fireEvent.click(screen.getByRole("button", { name: "Offer a part payment" }));
  expect(screen.getByLabelText("What the company says")).toHaveValue("We can offer a voucher of 2000 rupees as a final settlement.");
  expect(calls.some((call) => call.path === "/calls/call-1/provider-turn")).toBe(false);
});

it("shows the summary and disclosure approvals a call creates, and reloads them when told", async () => {
  const lists = [
    [],
    [
      { id: "d1", kind: "disclosure", status: "pending", payload: JSON.stringify({ fields: ["phone", "email"], asked_by: "provider" }) },
      { id: "s1", kind: "summary", status: "pending", payload: JSON.stringify({ summary: "The call ended with no promise.", simulated: true }) },
    ],
  ];
  const send = vi.fn(async (path) => {
    if (path === "/approvals?case=c1") return { approvals: lists.length > 1 ? lists.shift() : lists[0] };
    return { evidence: [] };
  });
  const { rerender } = render(<ApprovalList caseId="c1" version={0} send={send} />);
  expect(await screen.findByText("Nothing is waiting for your approval.")).toBeInTheDocument();
  rerender(<ApprovalList caseId="c1" version={1} send={send} />);
  expect(await screen.findByRole("heading", { name: "The company asked for more details" })).toBeInTheDocument();
  expect(screen.getByText("phone, email")).toBeInTheDocument();
  expect(screen.getByText("The call ended with no promise.")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(2);
});
