import { expect, it, vi } from "vitest";

import { createPlayback, START_LEAD_SECONDS } from "../../src/lib/audio/playback";
import { fakeAudioContext, pcmBytes } from "./fakes-audio";

const chunk = (samples) => pcmBytes(new Array(samples).fill(1000));

it("schedules chunks back to back with no gap", () => {
  const context = fakeAudioContext();
  context.currentTime = 2;
  const playback = createPlayback({ context });

  playback.enqueue(chunk(2400)); // 0.1 s at 24 kHz
  playback.enqueue(chunk(4800)); // 0.2 s
  playback.enqueue(chunk(2400));

  const [a, b, c] = context.sources;
  expect(a.startedAt).toBeCloseTo(2 + START_LEAD_SECONDS, 6);
  expect(b.startedAt).toBeCloseTo(a.startedAt + 0.1, 6);
  expect(c.startedAt).toBeCloseTo(b.startedAt + 0.2, 6);
  expect(playback.queued).toBe(3);
});

it("plays at 24 kHz and decodes little-endian PCM16", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  playback.enqueue(pcmBytes([0, 16384, -32768]));

  expect(context.buffers[0].sampleRate).toBe(24000);
  expect(Array.from(context.buffers[0].data)).toEqual([0, 0.5, -1]);
});

it("keeps a stray odd byte for the next chunk instead of losing it", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  const bytes = new Uint8Array(pcmBytes([100, 200, 300]));

  playback.enqueue(bytes.slice(0, 3)); // one whole sample and half of the next
  playback.enqueue(bytes.slice(3));

  expect(context.buffers).toHaveLength(2);
  expect(Array.from(context.buffers[0].data)).toEqual([100 / 32768]);
  expect(Array.from(context.buffers[1].data)).toEqual([200 / 32768, 300 / 32768]);
});

it("starts a fresh run after the queue has gone quiet", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  playback.enqueue(chunk(2400));
  context.sources[0].onended();
  context.currentTime = 10;
  playback.enqueue(chunk(2400));

  expect(context.sources[1].startedAt).toBeCloseTo(10 + START_LEAD_SECONDS, 6);
});

it("reports playing and not playing", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  const states = [];
  playback.on("playing", (value) => states.push(value));

  playback.enqueue(chunk(2400));
  playback.enqueue(chunk(2400));
  expect(playback.playing).toBe(true);
  context.sources[0].onended();
  expect(playback.playing).toBe(true);
  context.sources[1].onended();
  expect(playback.playing).toBe(false);
  expect(states).toEqual([true, false]);
});

it("flush stops every source at once and empties the queue", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  const states = [];
  playback.on("playing", (value) => states.push(value));
  for (let i = 0; i < 3; i += 1) playback.enqueue(chunk(2400));

  expect(playback.flush()).toBe(3);

  expect(context.sources.every((source) => source.stopped)).toBe(true);
  expect(playback.queued).toBe(0);
  expect(playback.playing).toBe(false);
  expect(states).toEqual([true, false]);
});

it("does not report a late ended event from a flushed source", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  playback.enqueue(chunk(2400));
  const [source] = context.sources;
  playback.flush();
  expect(source.onended).toBeNull();
});

it("starts the next sentence right away after a flush", () => {
  const context = fakeAudioContext();
  context.currentTime = 1;
  const playback = createPlayback({ context });
  playback.enqueue(chunk(24000)); // a full second queued
  playback.flush();
  playback.enqueue(chunk(2400));

  expect(context.sources[1].startedAt).toBeCloseTo(1 + START_LEAD_SECONDS, 6);
  expect(playback.queued).toBe(1);
});

it("flush while idle is harmless", () => {
  const playback = createPlayback({ context: fakeAudioContext() });
  const listener = vi.fn();
  playback.on("playing", listener);

  expect(playback.flush()).toBe(0);
  expect(playback.flush()).toBe(0);
  expect(listener).not.toHaveBeenCalled();
  expect(playback.playing).toBe(false);
});

it("flush survives a source that throws when stopped", () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  playback.enqueue(chunk(2400));
  context.sources[0].stop = () => {
    throw new Error("already ended");
  };
  expect(() => playback.flush()).not.toThrow();
  expect(playback.queued).toBe(0);
});

it("closes the audio context when closed", async () => {
  const context = fakeAudioContext();
  const playback = createPlayback({ context });
  playback.enqueue(chunk(2400));
  await playback.close();
  expect(context.state).toBe("closed");
  expect(context.sources[0].stopped).toBe(true);
});
