import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";

import { IntakeChat } from "../../src/components/IntakeChat";

const quiet = { text: null, phase: "narrating", status: "intake", handoff_fields: [] };
const asking = { text: "What did you pay?", phase: "asking", status: "intake", handoff_fields: [] };
const confirming = {
  text: "Thanks. Please check the details below.",
  phase: "confirming",
  status: "intake",
  handoff_fields: [],
};

function fakeSend(replies) {
  return vi.fn(async (path) => {
    for (const [suffix, reply] of Object.entries(replies)) {
      if (path.endsWith(suffix)) return reply;
    }
    throw new Error(`unexpected ${path}`);
  });
}

function paths(send, suffix) {
  return send.mock.calls.filter((call) => String(call[0]).endsWith(suffix));
}

function type(value) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value } });
}

async function click(name) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

async function say(value) {
  type(value);
  await click("Send");
}

it("shows no assistant bubble while the reply text is null", async () => {
  const send = fakeSend({ "/intake/messages": quiet });
  render(<IntakeChat caseId="c1" send={send} />);
  await say("The phone never arrived");
  expect(screen.getByText("The phone never arrived")).toBeInTheDocument();
  expect(screen.queryByText("Resolve")).not.toBeInTheDocument();
});

it("shows the first question after Done", async () => {
  const send = fakeSend({ "/narration-done": asking });
  render(<IntakeChat caseId="c1" send={send} />);
  await click("Done");
  expect(screen.getByText("What did you pay?")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Your answer" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument();
});

it("posts the answer to messages while asking", async () => {
  const send = fakeSend({ "/narration-done": asking, "/intake/messages": quiet });
  render(<IntakeChat caseId="c1" send={send} />);
  await click("Done");
  await say("1200 rupees");
  expect(paths(send, "/intake/messages")).toEqual([
    ["/cases/c1/intake/messages", { method: "POST", body: { text: "1200 rupees" } }],
  ]);
  expect(screen.getByText("1200 rupees")).toBeInTheDocument();
});

it("renders Hindi text with automatic direction", async () => {
  const send = fakeSend({ "/intake/messages": quiet });
  render(<IntakeChat caseId="c1" send={send} />);
  await say("फोन कभी नहीं आया");
  expect(screen.getByText("फोन कभी नहीं आया")).toHaveAttribute("dir", "auto");
});

it("sends narration-done only once, even on a double click", async () => {
  const send = fakeSend({ "/narration-done": asking });
  render(<IntakeChat caseId="c1" send={send} />);
  const button = screen.getByRole("button", { name: "Done" });
  await act(async () => {
    fireEvent.click(button);
    fireEvent.click(button);
  });
  expect(paths(send, "/narration-done")).toHaveLength(1);
});

it("sends the words in the box before Done", async () => {
  const send = fakeSend({ "/intake/messages": quiet, "/narration-done": asking });
  render(<IntakeChat caseId="c1" send={send} />);
  type("one more thing");
  await click("Done");
  expect(send.mock.calls.map((call) => call[0])).toEqual(["/cases/c1/intake/messages", "/cases/c1/narration-done"]);
});

it("asks once after the idle period and not again", async () => {
  vi.useFakeTimers();
  try {
    const send = fakeSend({
      "/intake/messages": quiet,
      "/intake/silence": { ...quiet, text: "Shall I go ahead?" },
    });
    render(<IntakeChat caseId="c1" send={send} idleMs={25000} />);
    await say("The phone never arrived");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(24000);
    });
    expect(paths(send, "/intake/silence")).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(paths(send, "/intake/silence")).toHaveLength(1);
    expect(screen.getByText("Shall I go ahead?")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000);
    });
    expect(paths(send, "/intake/silence")).toHaveLength(1);
  } finally {
    vi.useRealTimers();
  }
});

it("does not ask about silence before anything is written, or while typing", async () => {
  vi.useFakeTimers();
  try {
    const send = fakeSend({ "/intake/messages": quiet, "/intake/silence": quiet });
    render(<IntakeChat caseId="c1" send={send} idleMs={25000} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(paths(send, "/intake/silence")).toHaveLength(0);
    await say("first");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    type("still typing");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(paths(send, "/intake/silence")).toHaveLength(0);
  } finally {
    vi.useRealTimers();
  }
});

it("does not ask about silence after the phase changes", async () => {
  vi.useFakeTimers();
  try {
    const send = fakeSend({ "/intake/messages": quiet, "/narration-done": asking, "/intake/silence": quiet });
    render(<IntakeChat caseId="c1" send={send} idleMs={25000} />);
    await say("first");
    await click("Done");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(paths(send, "/intake/silence")).toHaveLength(0);
  } finally {
    vi.useRealTimers();
  }
});

it("uses a timer prop when one is given", async () => {
  const send = fakeSend({ "/intake/messages": quiet, "/intake/silence": quiet });
  const timers = { set: vi.fn(() => 7), clear: vi.fn() };
  render(<IntakeChat caseId="c1" send={send} timers={timers} idleMs={25000} />);
  await say("first");
  expect(timers.set).toHaveBeenLastCalledWith(expect.any(Function), 25000);
  await act(async () => {
    await timers.set.mock.calls.at(-1)[0]();
  });
  expect(paths(send, "/intake/silence")).toHaveLength(1);
});

it("disables the box when confirming and shows the closing text", async () => {
  const send = fakeSend({ "/narration-done": confirming });
  render(<IntakeChat caseId="c1" send={send} />);
  await click("Done");
  expect(screen.getByText("Thanks. Please check the details below.")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Add or correct a detail" })).toBeEnabled();
});

it("lets the person go to the cards to add or correct a detail", async () => {
  const onEditDetails = vi.fn();
  const send = fakeSend({ "/narration-done": confirming });
  render(<IntakeChat caseId="c1" send={send} onEditDetails={onEditDetails} />);
  await click("Done");
  fireEvent.click(screen.getByRole("button", { name: "Add or correct a detail" }));
  expect(onEditDetails).toHaveBeenCalledTimes(1);
});

it("names the fields the chat could not get and offers a form for them", async () => {
  const send = fakeSend({
    "/narration-done": { ...confirming, handoff_fields: ["order_id", "amount"] },
    "/facts": { id: "f1", version: 1, confirmation_state: "unconfirmed" },
  });
  const onFactsChanged = vi.fn();
  render(<IntakeChat caseId="c1" send={send} onFactsChanged={onFactsChanged} />);
  await click("Done");
  expect(screen.getByTestId("handoff-line")).toHaveTextContent("Order id, Amount");
  fireEvent.change(screen.getByLabelText("Order id"), { target: { value: "OD-123" } });
  await click("Save details");
  expect(paths(send, "/facts")).toEqual([
    ["/cases/c1/facts", { method: "POST", body: { field: "order_id", value: "OD-123", certainty: "stated", phrase: "" } }],
  ]);
  expect(onFactsChanged).toHaveBeenCalledTimes(2);
});

it("shows no handoff line when nothing is missing", async () => {
  const send = fakeSend({ "/narration-done": confirming });
  render(<IntakeChat caseId="c1" send={send} />);
  await click("Done");
  expect(screen.queryByTestId("handoff-line")).not.toBeInTheDocument();
});

it("calls onFactsChanged after a reply and after Done", async () => {
  const send = fakeSend({ "/intake/messages": quiet, "/narration-done": confirming });
  const onFactsChanged = vi.fn();
  render(<IntakeChat caseId="c1" send={send} onFactsChanged={onFactsChanged} />);
  await say("hello");
  expect(onFactsChanged).toHaveBeenCalledTimes(1);
  await click("Done");
  expect(onFactsChanged).toHaveBeenCalledTimes(2);
});

it("shows a readable error when a message fails and keeps the words", async () => {
  const send = vi.fn().mockRejectedValue(new Error("The server is busy"));
  render(<IntakeChat caseId="c1" send={send} />);
  await say("my words");
  expect(screen.getByRole("alert")).toHaveTextContent("We could not send your message");
  expect(screen.getByRole("alert")).toHaveTextContent("The server is busy");
  expect(screen.getByRole("textbox")).toHaveValue("my words");
});

it("shows an error when Done fails and allows another try", async () => {
  const send = vi.fn().mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce(asking);
  render(<IntakeChat caseId="c1" send={send} />);
  await click("Done");
  expect(screen.getByRole("alert")).toHaveTextContent("Offline");
  await click("Done");
  expect(screen.getByText("What did you pay?")).toBeInTheDocument();
  expect(send).toHaveBeenCalledTimes(2);
});

it("never calls a confirm endpoint, even after a long wait", async () => {
  vi.useFakeTimers();
  try {
    const send = fakeSend({
      "/intake/messages": quiet,
      "/intake/silence": { ...quiet, text: "Shall I go ahead?" },
      "/narration-done": { ...confirming, handoff_fields: ["amount"] },
      "/facts": { id: "f1", version: 1, confirmation_state: "unconfirmed" },
    });
    render(<IntakeChat caseId="c1" send={send} />);
    await say("hello");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    await click("Done");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(send.mock.calls.some((call) => String(call[0]).includes("/confirm"))).toBe(false);
  } finally {
    vi.useRealTimers();
  }
});

const doneCalls = [];
const server = setupServer(
  http.post("http://localhost:3000/cases/:id/narration-done", () => {
    doneCalls.push("done");
    return HttpResponse.json(asking);
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

it("posts narration-done once through the real client", async () => {
  process.env.NEXT_PUBLIC_API_URL = "http://localhost:3000";
  doneCalls.length = 0;
  render(<IntakeChat caseId="case-9" />);
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  await waitFor(() => expect(screen.getByText("What did you pay?")).toBeInTheDocument());
  expect(doneCalls).toEqual(["done"]);
  delete process.env.NEXT_PUBLIC_API_URL;
});
