import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, it, vi } from "vitest";

import { createCapture } from "../../src/lib/audio/capture";
import { FRAME_SAMPLES } from "../../src/lib/audio/constants";

function setup({ sampleRate = 48000, getUserMedia } = {}) {
  const track = { enabled: true, stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  const nodes = {};

  class FakeContext {
    constructor() {
      this.sampleRate = sampleRate;
      this.state = "running";
      this.destination = {};
      this.audioWorklet = { addModule: vi.fn(async () => {}) };
      nodes.context = this;
    }
    resume() {}
    createMediaStreamSource() {
      return (nodes.source = { connect: vi.fn(), disconnect: vi.fn() });
    }
    createGain() {
      return (nodes.sink = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() });
    }
    close() {
      this.state = "closed";
      return Promise.resolve();
    }
  }
  class FakeNode {
    constructor(context, name, options) {
      this.name = name;
      this.options = options;
      this.port = {};
      this.connect = vi.fn();
      this.disconnect = vi.fn();
      nodes.node = this;
    }
  }

  const mediaDevices = { getUserMedia: getUserMedia || vi.fn(async () => stream) };
  const frames = [];
  const capture = createCapture({
    mediaDevices,
    AudioContextClass: FakeContext,
    AudioWorkletNodeClass: FakeNode,
    onFrame: (frame) => frames.push(frame),
  });
  const send = (length = 960) =>
    nodes.node.port.onmessage({ data: { samples: new Float32Array(length).fill(0.25), sampleRate } });
  return { capture, frames, nodes, mediaDevices, track, send };
}

it("asks for echo cancellation, noise suppression and automatic gain", async () => {
  const { capture, mediaDevices, nodes } = setup();
  await capture.start();
  const { audio } = mediaDevices.getUserMedia.mock.calls[0][0];
  expect(audio).toMatchObject({ echoCancellation: true, noiseSuppression: true, autoGainControl: true });
  expect(nodes.context.audioWorklet.addModule).toHaveBeenCalledWith("/audio/capture-worklet.js");
  expect(nodes.node.name).toBe("capture-processor");
});

it("sends fixed 20 ms frames of 16 kHz PCM16", async () => {
  const { capture, frames, send } = setup();
  await capture.start();
  for (let i = 0; i < 10; i += 1) send(960);
  expect(frames.length).toBeGreaterThanOrEqual(9);
  expect(frames.every((frame) => frame instanceof Int16Array && frame.length === FRAME_SAMPLES)).toBe(true);
  expect(FRAME_SAMPLES).toBe(320);
});

it("stops sending while muted and switches the microphone track off", async () => {
  const { capture, frames, send, track } = setup();
  await capture.start();
  send();
  send();
  const before = frames.length;

  capture.mute(true);
  expect(track.enabled).toBe(false);
  send();
  send();
  send();
  expect(frames.length).toBe(before);

  capture.mute(false);
  expect(track.enabled).toBe(true);
  for (let i = 0; i < 4; i += 1) send();
  expect(frames.length).toBeGreaterThan(before);
});

it("reports a blocked microphone with its own code", async () => {
  const denied = Object.assign(new Error("no"), { name: "NotAllowedError" });
  const { capture } = setup({ getUserMedia: vi.fn(async () => Promise.reject(denied)) });
  await expect(capture.start()).rejects.toMatchObject({ code: "microphone_denied" });
});

it("reports a missing microphone with its own code", async () => {
  const missing = Object.assign(new Error("none"), { name: "NotFoundError" });
  const { capture } = setup({ getUserMedia: vi.fn(async () => Promise.reject(missing)) });
  await expect(capture.start()).rejects.toMatchObject({ code: "microphone_missing" });
});

it("reports a browser without audio worklets", async () => {
  const capture = createCapture({
    mediaDevices: { getUserMedia: vi.fn() },
    AudioContextClass: undefined,
    AudioWorkletNodeClass: undefined,
    onFrame() {},
  });
  await expect(capture.start()).rejects.toMatchObject({ code: "microphone_unsupported" });
});

it("stops the tracks and closes the audio context on stop", async () => {
  const { capture, frames, track, nodes } = setup();
  await capture.start();
  const handler = nodes.node.port.onmessage;
  capture.stop();
  expect(track.stop).toHaveBeenCalled();
  expect(nodes.context.state).toBe("closed");
  expect(nodes.node.port.onmessage).toBeNull();
  const before = frames.length;
  handler({ data: { samples: new Float32Array(960), sampleRate: 48000 } });
  expect(frames.length).toBe(before);
});

it("the worklet gathers about 20 ms of samples per message and registers itself", () => {
  const source = readFileSync(path.resolve(__dirname, "../../public/audio/capture-worklet.js"), "utf8");
  let registered;
  class AudioWorkletProcessor {
    constructor() {
      this.port = { posted: [], postMessage: (message) => this.port.posted.push(message) };
    }
  }
  new Function("AudioWorkletProcessor", "registerProcessor", "sampleRate", source)(
    AudioWorkletProcessor,
    (name, processor) => {
      registered = { name, processor };
    },
    48000,
  );

  expect(registered.name).toBe("capture-processor");
  const processor = new registered.processor({ processorOptions: { chunkMs: 20 } });
  const block = [new Float32Array(128).fill(0.1)];
  for (let i = 0; i < 8; i += 1) processor.process([block]);
  // 8 blocks of 128 samples is 1024; one 960-sample chunk is ready and 64 samples are waiting.
  expect(processor.port.posted).toHaveLength(1);
  expect(processor.port.posted[0].samples).toHaveLength(960);
  expect(processor.port.posted[0].sampleRate).toBe(48000);
  expect(processor.process([])).toBe(true);
});
