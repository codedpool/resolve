import { expect, it } from "vitest";

import { createFramer, createResampler, floatToPcm16 } from "../../src/lib/audio/resampler";

function sine(rate, hz, seconds, amplitude = 0.5) {
  const out = new Float32Array(Math.round(rate * seconds));
  for (let i = 0; i < out.length; i += 1) out[i] = amplitude * Math.sin((2 * Math.PI * hz * i) / rate);
  return out;
}

/** Counts rising zero crossings to estimate frequency. Skips the start, where the filter settles. */
function estimateHz(samples, rate, skip = 400) {
  let crossings = 0;
  let first = -1;
  let last = -1;
  for (let i = skip + 1; i < samples.length; i += 1) {
    if (samples[i - 1] < 0 && samples[i] >= 0) {
      crossings += 1;
      if (first < 0) first = i;
      last = i;
    }
  }
  return ((crossings - 1) * rate) / (last - first);
}

function rms(samples, skip = 400) {
  let sum = 0;
  for (let i = skip; i < samples.length; i += 1) sum += (samples[i] / 32768) ** 2;
  return Math.sqrt(sum / (samples.length - skip));
}

function runInChunks(resampler, input, sizes) {
  const parts = [];
  let offset = 0;
  let turn = 0;
  while (offset < input.length) {
    const size = sizes[turn % sizes.length];
    parts.push(resampler.process(input.subarray(offset, offset + size)));
    offset += size;
    turn += 1;
  }
  const merged = new Int16Array(parts.reduce((total, part) => total + part.length, 0));
  let at = 0;
  for (const part of parts) {
    merged.set(part, at);
    at += part.length;
  }
  return merged;
}

it.each([48000, 44100, 16000])("turns a 440 Hz tone at %i Hz into 16 kHz PCM16 of the right length and pitch", (rate) => {
  const input = sine(rate, 440, 1);
  const output = createResampler(rate).process(input);

  expect(output).toBeInstanceOf(Int16Array);
  expect(Math.abs(output.length - 16000)).toBeLessThanOrEqual(2);
  expect(Math.abs(estimateHz(output, 16000) - 440)).toBeLessThan(5);
  // The tone keeps its loudness: a 0.5 amplitude sine has an rms of about 0.354.
  expect(rms(output)).toBeGreaterThan(0.33);
  expect(rms(output)).toBeLessThan(0.38);
});

it("also handles a 1 kHz tone from 48 kHz without shifting its pitch", () => {
  const output = createResampler(48000).process(sine(48000, 1000, 1));
  expect(Math.abs(estimateHz(output, 16000) - 1000)).toBeLessThan(8);
});

it("passes 16 kHz audio through unchanged apart from the PCM16 conversion", () => {
  const input = sine(16000, 300, 0.1);
  expect(createResampler(16000).process(input)).toEqual(floatToPcm16(input));
});

it("gives the same samples whatever the chunk sizes are", () => {
  const input = sine(44100, 523, 0.5);
  const whole = createResampler(44100).process(input);
  const chunked = runInChunks(createResampler(44100), input, [128, 441, 1, 977, 300]);
  const tiny = runInChunks(createResampler(44100), input, [7]);

  expect(chunked.length).toBe(whole.length);
  expect(tiny.length).toBe(whole.length);
  for (let i = 0; i < whole.length; i += 1) {
    expect(Math.abs(chunked[i] - whole[i])).toBeLessThanOrEqual(1);
    expect(Math.abs(tiny[i] - whole[i])).toBeLessThanOrEqual(1);
  }
});

it("has no jump at chunk boundaries", () => {
  const output = runInChunks(createResampler(48000), sine(48000, 200, 0.5, 0.8), [128]);
  let biggest = 0;
  for (let i = 1; i < output.length; i += 1) biggest = Math.max(biggest, Math.abs(output[i] - output[i - 1]));
  // A 200 Hz sine at 16 kHz moves at most about 2*pi*200/16000 of its amplitude per sample.
  const limit = 0.8 * 32768 * ((2 * Math.PI * 200) / 16000) * 1.2;
  expect(biggest).toBeLessThan(limit);
});

it("keeps high frequencies from folding back into the voice band when going down", () => {
  // 12 kHz is above the 8 kHz limit of a 16 kHz stream and would alias to 4 kHz without the filter.
  const output = createResampler(48000).process(sine(48000, 12000, 0.5, 0.8));
  expect(rms(output)).toBeLessThan(0.02);
});

it("clamps out-of-range samples", () => {
  expect(Array.from(floatToPcm16(Float32Array.from([2, -2, 0])))).toEqual([32767, -32768, 0]);
});

it("returns nothing for an empty chunk and survives a reset", () => {
  const resampler = createResampler(48000);
  expect(resampler.process(new Float32Array(0)).length).toBe(0);
  resampler.process(sine(48000, 440, 0.05));
  resampler.reset();
  expect(resampler.process(sine(48000, 440, 0.05)).length).toBeGreaterThan(0);
});

it("rejects a bad rate", () => {
  expect(() => createResampler(0)).toThrow();
});

it("hands out fixed frames and keeps the remainder for the next chunk", () => {
  const frames = [];
  const framer = createFramer(320, (frame) => frames.push(frame));
  framer.push(new Int16Array(200));
  expect(frames).toHaveLength(0);
  framer.push(new Int16Array(500));
  expect(frames).toHaveLength(2);
  expect(frames.every((frame) => frame.length === 320)).toBe(true);
  expect(framer.pending).toBe(60);
});
