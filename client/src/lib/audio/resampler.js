/**
 * Microphone audio arrives as Float32 at whatever rate the device runs (often 44100 or 48000).
 * The voice gateway wants PCM16 mono at 16 kHz. This resampler keeps its state between chunks,
 * so a stream cut into pieces at any place gives the same samples as one long piece.
 *
 * Going down in rate, the signal first passes a windowed-sinc low-pass filter so that content
 * above the new Nyquist limit does not fold back into the speech band. Then it is read out at the
 * new rate with linear interpolation. No dependencies.
 */

export const TARGET_RATE = 16000;
const FILTER_TAPS = 63;

export function floatToPcm16(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    out[i] = Math.round(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
  }
  return out;
}

function lowPassTaps(cutoff) {
  // `cutoff` is a fraction of the input sample rate.
  const taps = new Float64Array(FILTER_TAPS);
  const mid = (FILTER_TAPS - 1) / 2;
  let sum = 0;
  for (let k = 0; k < FILTER_TAPS; k += 1) {
    const x = k - mid;
    const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
    const hann = 0.5 - 0.5 * Math.cos((2 * Math.PI * k) / (FILTER_TAPS - 1));
    taps[k] = sinc * hann;
    sum += taps[k];
  }
  for (let k = 0; k < FILTER_TAPS; k += 1) taps[k] /= sum;
  return taps;
}

export function createResampler(inputRate, outputRate = TARGET_RATE) {
  if (!(inputRate > 0) || !(outputRate > 0)) throw new Error("Sample rates must be positive numbers");

  const step = inputRate / outputRate;
  const filtering = inputRate > outputRate;
  const taps = filtering ? lowPassTaps((0.45 * outputRate) / inputRate) : null;

  let history = new Float32Array(FILTER_TAPS - 1);
  let phase = 0; // position of the next output sample, in input samples, relative to the current chunk
  let previous = 0; // last sample of the previous chunk (index -1 of the next chunk)
  let started = false;

  function filter(chunk) {
    const combined = new Float32Array(history.length + chunk.length);
    combined.set(history, 0);
    combined.set(chunk, history.length);
    const out = new Float32Array(chunk.length);
    const lead = FILTER_TAPS - 1;
    for (let i = 0; i < chunk.length; i += 1) {
      let acc = 0;
      for (let k = 0; k < FILTER_TAPS; k += 1) acc += taps[k] * combined[lead + i - k];
      out[i] = acc;
    }
    history = combined.slice(combined.length - lead);
    return out;
  }

  function readFloat(input) {
    const n = input.length;
    if (n === 0) return new Float32Array(0);
    if (!started) {
      previous = input[0];
      started = true;
    }
    const out = [];
    while (Math.floor(phase) + 1 <= n - 1) {
      const index = Math.floor(phase);
      const fraction = phase - index;
      const a = index < 0 ? previous : input[index];
      const b = input[index + 1];
      out.push(a + (b - a) * fraction);
      phase += step;
    }
    phase -= n;
    previous = input[n - 1];
    return Float32Array.from(out);
  }

  return {
    inputRate,
    outputRate,
    /** Float32 samples in, Int16 samples at the output rate out. */
    process(chunk) {
      if (inputRate === outputRate) return floatToPcm16(chunk);
      const source = filtering ? filter(chunk) : chunk;
      return floatToPcm16(readFloat(source));
    },
    reset() {
      history = new Float32Array(FILTER_TAPS - 1);
      phase = 0;
      previous = 0;
      started = false;
    },
  };
}

/** Collects Int16 samples and hands out fixed-size frames. Leftovers wait for the next chunk. */
export function createFramer(frameSize, onFrame) {
  let pending = new Int16Array(0);

  return {
    push(samples) {
      const merged = new Int16Array(pending.length + samples.length);
      merged.set(pending, 0);
      merged.set(samples, pending.length);
      let offset = 0;
      while (merged.length - offset >= frameSize) {
        onFrame(merged.slice(offset, offset + frameSize));
        offset += frameSize;
      }
      pending = merged.slice(offset);
    },
    clear() {
      pending = new Int16Array(0);
    },
    get pending() {
      return pending.length;
    },
  };
}
