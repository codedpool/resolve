import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { CallPanel } from "../../src/components/CallPanel";
import { CallWorkspace } from "../../src/components/CallWorkspace";
import { applyCaption } from "../../src/lib/audio/captions";
import { createEmitter } from "../../src/lib/audio/emitter";

function fakeClient() {
  const events = createEmitter();
  const client = {
    state: "idle",
    on: events.on,
    fire(name, payload) {
      if (name === "state") client.state = payload;
      act(() => events.emit(name, payload));
    },
    start: vi.fn(async () => {}),
    end: vi.fn(async () => {}),
    done: vi.fn(() => true),
    setMuted: vi.fn(),
  };
  return client;
}

function live(client) {
  client.fire("state", "connecting");
  client.fire("state", "live");
}

it("starts the call from the button", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  expect(screen.getByText("Not connected")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Mute microphone" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Start the call" }));
  expect(client.start).toHaveBeenCalledWith("c1");
});

it("shows the connection and speaking indicators", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  client.fire("state", "connecting");
  expect(screen.getByText("Connecting")).toBeInTheDocument();
  client.fire("state", "live");
  expect(screen.getByText("Connected")).toBeInTheDocument();
  expect(screen.getByTestId("speaking")).toHaveTextContent("Listening");
  client.fire("speaking", true);
  expect(screen.getByTestId("speaking")).toHaveTextContent("Resolve is speaking");
  client.fire("speaking", false);
  expect(screen.getByTestId("speaking")).toHaveTextContent("Listening");
});

it("shows live captions for both speakers, with Hindi text set to follow its own direction", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  live(client);
  client.fire("caption", { who: "user", text: "मेरा ऑर्डर नहीं आया", final: false });
  client.fire("caption", { who: "user", text: "मेरा ऑर्डर नहीं आया, order 4471", final: true });
  client.fire("caption", { who: "agent", text: "Thank you. Which company was it?", final: true });

  const hindi = screen.getByText("मेरा ऑर्डर नहीं आया, order 4471");
  expect(hindi).toHaveAttribute("dir", "auto");
  expect(screen.queryByText("मेरा ऑर्डर नहीं आया")).not.toBeInTheDocument();
  expect(screen.getByText("Thank you. Which company was it?")).toHaveAttribute("dir", "auto");
  expect(screen.getByRole("log", { name: "Captions" })).toBeInTheDocument();
  expect(screen.getByText("You")).toBeInTheDocument();
  expect(screen.getByText("Resolve")).toBeInTheDocument();
});

it("toggles mute through the client and shows the muted state", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  live(client);
  fireEvent.click(screen.getByRole("button", { name: "Mute microphone" }));
  expect(client.setMuted).toHaveBeenCalledWith(true);
  client.fire("muted", true);
  const button = screen.getByRole("button", { name: "Unmute microphone" });
  expect(button).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("speaking")).toHaveTextContent("muted");
  fireEvent.click(button);
  expect(client.setMuted).toHaveBeenLastCalledWith(false);
});

it("sends Done once and then disables the button", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  live(client);
  const done = screen.getByRole("button", { name: "Done" });
  fireEvent.click(done);
  client.fire("done");
  expect(client.done).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Done" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(client.done).toHaveBeenCalledTimes(1);
});

it("hides Done once narration is over", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  live(client);
  client.fire("phase", { phase: "gap_filling" });
  expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument();
  expect(screen.getByText(/asking about anything that is missing/i)).toBeInTheDocument();
});

it("ends the call from the End call button", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  live(client);
  expect(screen.queryByRole("button", { name: "Start the call" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "End call" }));
  expect(client.end).toHaveBeenCalled();
});

it("shows errors in plain language as an alert and lets the person start again", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  client.fire("state", "connecting");
  client.fire("state", "error");
  client.fire("error", { code: "microphone_denied", message: "The microphone is blocked. Allow it." });
  expect(screen.getByRole("alert")).toHaveTextContent("The microphone is blocked");
  expect(screen.getByRole("button", { name: "Start the call" })).toBeEnabled();
  client.fire("state", "connecting");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("shows how the call ended and reports it", () => {
  const client = fakeClient();
  const onEnded = vi.fn();
  render(<CallPanel client={client} caseId="c1" onEnded={onEnded} />);
  live(client);
  client.fire("state", "ended");
  client.fire("ended", { reason: "user", message: "The call has ended." });
  expect(screen.getByText("The call has ended.")).toBeInTheDocument();
  expect(onEnded).toHaveBeenCalled();
});

it("points to the case for an approval and shows progress", () => {
  const client = fakeClient();
  render(<CallPanel client={client} caseId="c1" />);
  live(client);
  client.fire("progress", { text: "Checking the order date" });
  client.fire("approval", { approvalId: "a1" });
  expect(screen.getByText("Checking the order date")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /review it/i })).toHaveAttribute("href", "/cases/c1");
});

it("folds live caption updates into one line and drops empty ones", () => {
  let list = applyCaption([], { who: "user", text: "hel", final: false }, 1);
  list = applyCaption(list, { who: "user", text: "hello", final: false }, 2);
  expect(list).toEqual([{ id: 1, who: "user", text: "hello", final: false }]);
  list = applyCaption(list, { who: "user", text: "hello there", final: true }, 3);
  expect(list).toEqual([{ id: 1, who: "user", text: "hello there", final: true }]);
  list = applyCaption(list, { who: "agent", text: "  ", final: true }, 4);
  expect(list).toHaveLength(1);
  list = applyCaption(list, { who: "agent", text: "Hi", final: true }, 5);
  expect(list).toHaveLength(2);
});

const fact = (over = {}) => ({
  id: "f1",
  field: "amount",
  value: "1200",
  certainty: "stated",
  phrase: "",
  version: 1,
  confirmation_state: "unconfirmed",
  ...over,
});

function fakeApi(facts) {
  return {
    request: vi.fn(async (path, options = {}) => {
      if (path.endsWith("/confirm")) return { confirmed_version: 2 };
      if (options.method === "POST") return { id: "f2", version: 3, confirmation_state: "unconfirmed" };
      return { id: "c1", facts };
    }),
  };
}

it("shows a confirmation card when a card event arrives, and does not confirm it by itself", async () => {
  const client = fakeClient();
  const api = fakeApi([fact()]);
  render(<CallWorkspace caseId="c1" client={client} api={api} />);
  live(client);
  expect(screen.getByText(/will appear here during the call/i)).toBeInTheDocument();

  client.fire("card", { kind: "confirm_field", factId: "f1" });
  expect(await screen.findByText("1200")).toBeInTheDocument();

  expect(screen.getByText("unconfirmed")).toBeInTheDocument();
  const confirms = api.request.mock.calls.filter(([path]) => String(path).endsWith("/confirm"));
  expect(confirms).toHaveLength(0);
});

it("confirms only when the person presses Accept", async () => {
  const client = fakeClient();
  const api = fakeApi([fact()]);
  render(<CallWorkspace caseId="c1" client={client} api={api} />);
  client.fire("card", { kind: "confirm_field", factId: "f1" });
  await screen.findByText("1200");

  fireEvent.click(screen.getByRole("button", { name: "Accept" }));

  await waitFor(() => expect(screen.getByText("confirmed")).toBeInTheDocument());
  expect(api.request).toHaveBeenCalledWith("/cases/c1/facts/f1/confirm", { method: "POST" });
});

it("links back to the case and tells the person when a card cannot be loaded", async () => {
  const client = fakeClient();
  const api = {
    request: vi
      .fn()
      .mockResolvedValueOnce({ id: "c1", facts: [] })
      .mockRejectedValueOnce(new Error("Server is busy")),
  };
  render(<CallWorkspace caseId="c1" client={client} api={api} />);
  expect(screen.getByRole("link", { name: "Back to the case" })).toHaveAttribute("href", "/cases/c1");
  client.fire("card", { kind: "confirm_field", factId: "f1" });
  expect(await screen.findByRole("alert")).toHaveTextContent("Server is busy");
});
