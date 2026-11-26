import { beforeEach, expect, it, vi } from "vitest";

import { createVoiceClient, buildSocketUrl, restCalls } from "../../src/lib/audio/voiceClient";
import { describeVoiceError } from "../../src/lib/audio/errors";
import { FakeSocket, pcmBytes } from "./fakes-audio";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function fakeCapture() {
  const capture = {
    onFrame: null,
    started: false,
    muted: false,
    stopped: false,
    start: vi.fn(async () => {
      capture.started = true;
    }),
    mute: vi.fn((on) => {
      capture.muted = on;
    }),
    stop: vi.fn(() => {
      capture.stopped = true;
    }),
  };
  return capture;
}

function fakePlayback() {
  const listeners = [];
  return {
    enqueue: vi.fn(),
    flush: vi.fn(),
    resume: vi.fn(),
    setSampleRate: vi.fn(),
    close: vi.fn(async () => {}),
    on: (name, fn) => listeners.push(fn),
    emitPlaying: (value) => listeners.forEach((fn) => fn(value)),
  };
}

function build(overrides = {}) {
  const capture = fakeCapture();
  const playback = fakePlayback();
  const requestCall = vi.fn(async () => ({ call_id: "call-1", ws_url: "/voice/ws", ws_token: "tok en" }));
  const requestEnd = vi.fn(async () => ({}));
  const client = createVoiceClient({
    requestCall,
    requestEnd,
    WebSocketImpl: FakeSocket,
    wsRoot: "ws://localhost:8000",
    createCapture: ({ onFrame }) => {
      capture.onFrame = onFrame;
      return capture;
    },
    createPlayback: () => playback,
    ...overrides,
  });
  const seen = { events: [], errors: [], ended: [], states: [], captions: [], cards: [] };
  client.on("error", (e) => seen.errors.push(e));
  client.on("ended", (e) => seen.ended.push(e));
  client.on("state", (e) => seen.states.push(e));
  client.on("caption", (e) => seen.captions.push(e));
  client.on("card", (e) => seen.cards.push(e));
  return { client, capture, playback, requestCall, requestEnd, seen };
}

/** Starts a call and takes it to the live state. */
async function goLive(parts) {
  const starting = parts.client.start("case-1");
  await tick();
  const socket = FakeSocket.instances.at(-1);
  socket.open();
  await starting;
  socket.receive({ type: "ready", rate_in: 16000, rate_out: 24000 });
  return socket;
}

const frame = () => new Int16Array(320).fill(5);

beforeEach(() => {
  FakeSocket.instances = [];
});

it("builds the socket address from the ws_url and puts the token in the query", () => {
  expect(buildSocketUrl({ ws_url: "/voice/ws", ws_token: "a b" }, "ws://host:1/")).toBe("ws://host:1/voice/ws?token=a%20b");
  expect(buildSocketUrl({ ws_url: "wss://x.test/voice/ws", ws_token: "t" })).toBe("wss://x.test/voice/ws?token=t");
  expect(buildSocketUrl({ ws_url: "https://x.test/voice/ws?v=1", ws_token: "t" })).toBe("wss://x.test/voice/ws?v=1&token=t");
});

it("asks for the call with the case and the consumer role", async () => {
  const request = vi.fn(async () => ({}));
  restCalls({ request }).requestCall("case-1");
  restCalls({ request }).requestEnd("call-1");
  expect(request).toHaveBeenNthCalledWith(1, "/calls", { method: "POST", body: { case_id: "case-1", role: "consumer" } });
  expect(request).toHaveBeenNthCalledWith(2, "/calls/call-1/end", { method: "POST" });
});

it("gets the microphone first, then the call, then opens one socket with the token and sends start", async () => {
  const parts = build();
  const order = [];
  parts.capture.start.mockImplementation(async () => order.push("mic"));
  parts.requestCall.mockImplementation(async () => {
    order.push("call");
    return { call_id: "call-1", ws_url: "/voice/ws", ws_token: "tok en" };
  });

  const socket = await goLive(parts);

  expect(order).toEqual(["mic", "call"]);
  expect(FakeSocket.instances).toHaveLength(1);
  expect(socket.url).toBe("ws://localhost:8000/voice/ws?token=tok%20en");
  expect(socket.binaryType).toBe("arraybuffer");
  expect(socket.json).toEqual([{ type: "start" }]);
  expect(parts.seen.states).toEqual(["connecting", "live"]);
  expect(parts.playback.setSampleRate).toHaveBeenCalledWith(24000);
});

it("sends only PCM16 frames, and only once the server is ready", async () => {
  const parts = build();
  const starting = parts.client.start("case-1");
  await tick();
  const socket = FakeSocket.instances[0];
  socket.open();
  await starting;

  parts.capture.onFrame(frame()); // before ready
  expect(socket.binary).toHaveLength(0);

  socket.receive({ type: "ready" });
  parts.capture.onFrame(frame());
  parts.capture.onFrame(frame());

  expect(socket.binary).toHaveLength(2);
  for (const sent of socket.binary) {
    expect(sent).toBeInstanceOf(ArrayBuffer);
    expect(sent.byteLength).toBe(640);
    expect(new Int16Array(sent)[0]).toBe(5);
  }
  expect(socket.json.every((message) => typeof message.type === "string")).toBe(true);
});

it("sends Done once and no more", async () => {
  const parts = build();
  const socket = await goLive(parts);

  expect(parts.client.done()).toBe(true);
  expect(parts.client.done()).toBe(false);
  expect(parts.client.done()).toBe(false);

  expect(socket.json.filter((message) => message.type === "done_narration")).toHaveLength(1);
  expect(parts.client.doneSent).toBe(true);
});

it("does not send Done before the call is live or after narration has ended", async () => {
  const parts = build();
  expect(parts.client.done()).toBe(false);
  const socket = await goLive(parts);
  socket.receive({ type: "phase", phase: "gap_filling" });
  expect(parts.client.done()).toBe(false);
  expect(socket.json.filter((message) => message.type === "done_narration")).toHaveLength(0);
});

it("clears playback and answers with playback_flushed on a flush message", async () => {
  const parts = build();
  const socket = await goLive(parts);

  socket.receive({ type: "flush" });

  expect(parts.playback.flush).toHaveBeenCalledTimes(1);
  expect(socket.json.at(-1)).toEqual({ type: "playback_flushed" });
});

it("treats a cancel message like a flush", async () => {
  const parts = build();
  const socket = await goLive(parts);
  socket.receive({ type: "cancel" });
  expect(parts.playback.flush).toHaveBeenCalledTimes(1);
  expect(socket.json.at(-1)).toEqual({ type: "playback_flushed" });
});

it("hands binary agent audio to playback", async () => {
  const parts = build();
  const socket = await goLive(parts);
  const audio = pcmBytes([1, 2, 3]);
  socket.receive(audio);
  expect(parts.playback.enqueue).toHaveBeenCalledWith(audio);
});

it("reports the speaking state from playback", async () => {
  const parts = build();
  const speaking = [];
  parts.client.on("speaking", (value) => speaking.push(value));
  await goLive(parts);
  parts.playback.emitPlaying(true);
  parts.playback.emitPlaying(false);
  expect(speaking).toEqual([true, false]);
});

it("passes captions and cards on as events and never confirms anything", async () => {
  const parts = build();
  const socket = await goLive(parts);
  socket.receive({ type: "caption", who: "user", text: "mera order nahi aaya", final: false });
  socket.receive({ type: "caption", who: "agent", text: "Got it.", final: true });
  socket.receive({ type: "card", kind: "confirm_field", fact_id: "f1" });

  expect(parts.seen.captions).toEqual([
    { who: "user", text: "mera order nahi aaya", final: false },
    { who: "agent", text: "Got it.", final: true },
  ]);
  expect(parts.seen.cards).toEqual([{ kind: "confirm_field", factId: "f1" }]);
  expect(socket.json).toEqual([{ type: "start" }]);
});

it("ignores malformed text frames", async () => {
  const parts = build();
  const socket = await goLive(parts);
  expect(() => socket.receive("not json {")).not.toThrow();
  expect(parts.client.state).toBe("live");
});

it("stops sending frames while muted, tells the server, and resumes after unmute", async () => {
  const parts = build();
  const socket = await goLive(parts);

  parts.client.setMuted(true);
  parts.capture.onFrame(frame());
  parts.capture.onFrame(frame());
  expect(socket.binary).toHaveLength(0);
  expect(parts.capture.mute).toHaveBeenCalledWith(true);
  expect(socket.json.at(-1)).toEqual({ type: "mute", on: true });

  parts.client.setMuted(false);
  parts.capture.onFrame(frame());
  expect(socket.binary).toHaveLength(1);
  expect(socket.json.at(-1)).toEqual({ type: "mute", on: false });
});

it("closes cleanly when the person ends the call", async () => {
  const parts = build();
  const socket = await goLive(parts);

  await parts.client.end();
  await parts.client.end();

  expect(socket.json.at(-1)).toEqual({ type: "end" });
  expect(socket.json.filter((message) => message.type === "end")).toHaveLength(1);
  expect(socket.closedWith).toBe(1000);
  expect(parts.capture.stop).toHaveBeenCalled();
  expect(parts.playback.flush).toHaveBeenCalled();
  expect(parts.playback.close).toHaveBeenCalled();
  expect(parts.requestEnd).toHaveBeenCalledTimes(1);
  expect(parts.requestEnd).toHaveBeenCalledWith("call-1");
  expect(parts.client.state).toBe("ended");
  expect(parts.seen.ended).toHaveLength(1);
  expect(parts.seen.ended[0].reason).toBe("user");
  expect(parts.seen.errors).toHaveLength(0);
  // Late frames and messages do nothing.
  parts.capture.onFrame(frame());
  expect(socket.binary).toHaveLength(0);
});

it("ends cleanly when the server sends closed", async () => {
  const parts = build();
  const socket = await goLive(parts);
  socket.receive({ type: "closed", reason: "completed" });
  expect(parts.client.state).toBe("ended");
  expect(parts.seen.ended[0]).toMatchObject({ reason: "completed" });
  expect(parts.capture.stop).toHaveBeenCalled();
  expect(socket.closedWith).toBe(1000);
});

it("maps a lost connection to readable text without reconnecting", async () => {
  const parts = build();
  const socket = await goLive(parts);
  socket.drop(1006);

  expect(parts.client.state).toBe("error");
  expect(parts.seen.errors[0].code).toBe("connection_lost");
  expect(parts.seen.errors[0].message).toMatch(/connection dropped/i);
  expect(FakeSocket.instances).toHaveLength(1);
  expect(parts.capture.stop).toHaveBeenCalled();
  await tick();
  expect(parts.requestEnd).toHaveBeenCalledWith("call-1");
});

it("maps a blocked microphone to readable text and never asks for a call", async () => {
  const parts = build();
  parts.capture.start.mockRejectedValue(Object.assign(new Error("denied"), { code: "microphone_denied" }));
  await parts.client.start("case-1");

  expect(parts.requestCall).not.toHaveBeenCalled();
  expect(FakeSocket.instances).toHaveLength(0);
  expect(parts.client.state).toBe("error");
  expect(parts.seen.errors[0].message).toMatch(/microphone is blocked/i);
});

it("maps a refused token to a readable expired-link message", async () => {
  const parts = build();
  const starting = parts.client.start("case-1");
  await tick();
  FakeSocket.instances[0].drop(4401);
  await starting;

  expect(parts.seen.errors[0].code).toBe("token_expired");
  expect(parts.seen.errors[0].message).toMatch(/expired/i);
  expect(parts.client.state).toBe("error");
});

it("maps any other failed connection to a connection message", async () => {
  const parts = build();
  const starting = parts.client.start("case-1");
  await tick();
  FakeSocket.instances[0].drop(1006);
  await starting;
  expect(parts.seen.errors[0].code).toBe("connect_failed");
});

it("maps a server error for a used-up budget and closes the call", async () => {
  const parts = build();
  const socket = await goLive(parts);
  socket.receive({ type: "error", code: "budget_reached" });

  expect(parts.seen.errors[0].message).toMatch(/voice time/i);
  expect(parts.client.state).toBe("error");
  expect(parts.capture.stop).toHaveBeenCalled();
  expect(socket.closedWith).toBe(1000);
});

it("keeps the call going after a small server error", async () => {
  const parts = build();
  const socket = await goLive(parts);
  socket.receive({ type: "error", code: "stt_slow" });
  expect(parts.client.state).toBe("live");
  expect(parts.seen.errors[0].code).toBe("stt_slow");
  expect(parts.seen.errors[0].message).toMatch(/something went wrong/i);
});

it("maps failed call requests by code or status", async () => {
  const parts = build();
  parts.requestCall.mockRejectedValue(Object.assign(new Error("x"), { status: 429, code: "request_failed" }));
  await parts.client.start("case-1");
  expect(parts.seen.errors[0].code).toBe("rate_limited");
  expect(parts.capture.stop).toHaveBeenCalled();
});

it("every known error has plain text with no raw code in it", () => {
  for (const code of [
    "microphone_denied",
    "microphone_missing",
    "microphone_unsupported",
    "token_expired",
    "budget_reached",
    "voice_killed",
    "connection_lost",
    "connect_failed",
  ]) {
    const text = describeVoiceError(code);
    expect(text).not.toContain("_");
    expect(text.length).toBeGreaterThan(20);
  }
});

it("a call can be started again after it ended", async () => {
  const parts = build();
  await goLive(parts);
  await parts.client.end();
  const socket = await goLive(parts);
  expect(FakeSocket.instances).toHaveLength(2);
  expect(socket.json).toEqual([{ type: "start" }]);
  expect(parts.client.doneSent).toBe(false);
});

it("ending while still connecting stops the microphone and never opens a socket", async () => {
  const parts = build();
  let release;
  parts.requestCall.mockImplementation(() => new Promise((resolve) => (release = resolve)));
  const starting = parts.client.start("case-1");
  await tick();
  await parts.client.end();
  release({ call_id: "c", ws_url: "/voice/ws", ws_token: "t" });
  await tick();
  void starting;

  expect(FakeSocket.instances).toHaveLength(0);
  expect(parts.capture.stop).toHaveBeenCalled();
  expect(parts.client.state).toBe("ended");
});
