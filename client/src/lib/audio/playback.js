import { RATE_OUT } from "./constants";
import { createEmitter } from "./emitter";

/** Time kept between "now" and the first scheduled sample, so the first chunk is not clipped. */
export const START_LEAD_SECONDS = 0.05;

/**
 * Plays the assistant's voice: PCM16 mono chunks (24 kHz by default) are scheduled back to back
 * on an AudioContext. `flush()` is barge-in: everything stops at once and the queue is emptied.
 *
 * Events: `playing` with `true` when sound is scheduled after silence and `false` when the queue
 * has run dry or been flushed.
 *
 * `context` is any object shaped like an AudioContext, so tests can pass a fake.
 */
export function createPlayback({ context, sampleRate = RATE_OUT } = {}) {
  const events = createEmitter();
  const active = new Set();
  let rate = sampleRate;
  let nextTime = 0;
  let playing = false;
  let leftoverByte = null;
  let output = null;

  function destination() {
    if (!output) {
      output = context.createGain ? context.createGain() : null;
      if (output) output.connect(context.destination);
    }
    return output || context.destination;
  }

  function setPlaying(value) {
    if (playing === value) return;
    playing = value;
    events.emit("playing", value);
  }

  function toBytes(chunk) {
    const bytes = chunk instanceof ArrayBuffer ? new Uint8Array(chunk) : new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength);
    if (leftoverByte === null) return bytes;
    const merged = new Uint8Array(bytes.length + 1);
    merged[0] = leftoverByte;
    merged.set(bytes, 1);
    leftoverByte = null;
    return merged;
  }

  function toFloat(bytes) {
    let usable = bytes.length;
    if (usable % 2 === 1) {
      // A frame can be cut in the middle of a sample. Keep the odd byte for the next chunk.
      leftoverByte = bytes[usable - 1];
      usable -= 1;
    }
    const view = new DataView(bytes.buffer, bytes.byteOffset, usable);
    const out = new Float32Array(usable / 2);
    for (let i = 0; i < out.length; i += 1) out[i] = view.getInt16(i * 2, true) / 0x8000;
    return out;
  }

  return {
    get playing() {
      return playing;
    },
    /** Number of scheduled chunks that have not finished yet. */
    get queued() {
      return active.size;
    },
    get sampleRate() {
      return rate;
    },
    setSampleRate(value) {
      if (value > 0) rate = value;
    },
    on: events.on,
    resume() {
      return context.state === "suspended" && context.resume ? context.resume() : Promise.resolve();
    },
    /** Accepts an ArrayBuffer or a typed array of little-endian PCM16 bytes. Returns the seconds scheduled. */
    enqueue(chunk) {
      const samples = toFloat(toBytes(chunk));
      if (samples.length === 0) return 0;

      const buffer = context.createBuffer(1, samples.length, rate);
      buffer.getChannelData(0).set(samples);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(destination());

      const now = context.currentTime;
      // If the queue ran dry the next chunk starts a little after now. Otherwise it follows the last one exactly.
      const startAt = active.size === 0 || nextTime < now ? now + START_LEAD_SECONDS : nextTime;
      nextTime = startAt + buffer.duration;

      source.onended = () => {
        active.delete(source);
        if (active.size === 0) setPlaying(false);
      };
      active.add(source);
      source.start(startAt);
      setPlaying(true);
      return buffer.duration;
    },
    /** Barge-in. Stops every scheduled source now and empties the queue. Safe when nothing is playing. */
    flush() {
      const stopped = active.size;
      for (const source of [...active]) {
        source.onended = null;
        try {
          source.stop();
        } catch {
          // A source that already ended throws when stopped. That is fine.
        }
        try {
          source.disconnect();
        } catch {
          // Already disconnected.
        }
      }
      active.clear();
      nextTime = 0;
      leftoverByte = null;
      setPlaying(false);
      return stopped;
    },
    async close() {
      this.flush();
      events.clear();
      if (context.close && context.state !== "closed") await context.close();
    },
  };
}
