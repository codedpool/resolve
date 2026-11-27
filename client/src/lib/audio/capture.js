import { FRAME_MS, FRAME_SAMPLES, RATE_IN, WORKLET_NAME, WORKLET_URL } from "./constants";
import { createFramer, createResampler } from "./resampler";

export class CaptureError extends Error {
  constructor(code, message) {
    super(message || code);
    this.name = "CaptureError";
    this.code = code;
  }
}

function describeFailure(error) {
  const name = error?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return new CaptureError("microphone_denied");
  }
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") {
    return new CaptureError("microphone_missing");
  }
  return new CaptureError("microphone_unavailable", error?.message);
}

export const MIC_CONSTRAINTS = {
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

/**
 * Microphone capture. Asks for the microphone, runs it through the worklet, resamples to 16 kHz
 * PCM16 and calls `onFrame(Int16Array)` with fixed frames of `frameMs` milliseconds.
 * While muted nothing is sent and the microphone track is switched off.
 *
 * Everything the browser provides is injected: `mediaDevices`, `AudioContextClass` and
 * `AudioWorkletNodeClass`, so tests can use fakes.
 */
export function createCapture({
  mediaDevices,
  AudioContextClass,
  AudioWorkletNodeClass,
  onFrame,
  frameMs = FRAME_MS,
  workletUrl = WORKLET_URL,
} = {}) {
  const frameSize = frameMs === FRAME_MS ? FRAME_SAMPLES : Math.round((RATE_IN * frameMs) / 1000);
  let muted = false;
  let stopped = false;
  let stream = null;
  let context = null;
  let source = null;
  let node = null;
  let sink = null;
  let resampler = null;
  const framer = createFramer(frameSize, (frame) => {
    if (!muted && !stopped) onFrame(frame);
  });

  function handleChunk(event) {
    if (muted || stopped) return;
    const { samples, sampleRate } = event.data || {};
    if (!samples) return;
    if (!resampler || resampler.inputRate !== sampleRate) resampler = createResampler(sampleRate, RATE_IN);
    framer.push(resampler.process(samples));
  }

  function release() {
    try {
      if (node?.port) node.port.onmessage = null;
      source?.disconnect();
      node?.disconnect();
      sink?.disconnect();
    } catch {
      // Nodes that are already disconnected throw. Nothing to do.
    }
    stream?.getTracks().forEach((track) => track.stop());
    if (context && context.state !== "closed") Promise.resolve(context.close?.()).catch(() => {});
    stream = context = source = node = sink = null;
  }

  return {
    get muted() {
      return muted;
    },
    get active() {
      return Boolean(stream) && !stopped;
    },
    async start() {
      if (!mediaDevices?.getUserMedia || !AudioContextClass || !AudioWorkletNodeClass) {
        throw new CaptureError("microphone_unsupported");
      }
      stopped = false;
      // The context is made first so it still counts as started by the person's click.
      context = new AudioContextClass();
      if (!context.audioWorklet) {
        release();
        throw new CaptureError("microphone_unsupported");
      }
      context.resume?.();
      try {
        stream = await mediaDevices.getUserMedia(MIC_CONSTRAINTS);
      } catch (error) {
        release();
        throw describeFailure(error);
      }
      if (stopped) {
        release();
        return;
      }
      try {
        await context.audioWorklet.addModule(workletUrl);
        source = context.createMediaStreamSource(stream);
        node = new AudioWorkletNodeClass(context, WORKLET_NAME, { processorOptions: { chunkMs: frameMs } });
        node.port.onmessage = handleChunk;
        // The node is wired to the output through a silent gain, otherwise some browsers stop pulling audio.
        sink = context.createGain();
        sink.gain.value = 0;
        source.connect(node);
        node.connect(sink);
        sink.connect(context.destination);
      } catch (error) {
        release();
        throw new CaptureError("microphone_unavailable", error?.message);
      }
      stream.getAudioTracks?.().forEach((track) => {
        track.enabled = !muted;
      });
    },
    mute(on) {
      muted = Boolean(on);
      if (muted) framer.clear();
      stream?.getAudioTracks?.().forEach((track) => {
        track.enabled = !muted;
      });
    },
    stop() {
      stopped = true;
      framer.clear();
      release();
    },
  };
}
