/**
 * Everything the browser and the voice gateway have to agree on lives here, so a rename on the
 * server is a one-file change. Names follow the documented voice protocol.
 */

// REST
export const CALLS_PATH = "/calls";
export const endCallPath = (callId) => `/calls/${callId}/end`;
export const CALL_ROLE = "consumer";

// WebSocket
export const WS_PATH = "/voice/ws";
export const WS_TOKEN_PARAM = "token";

// Audio formats. Browser to server is PCM16 mono 16 kHz, server to browser is PCM16 mono 24 kHz.
export const RATE_IN = 16000;
export const RATE_OUT = 24000;
export const FRAME_MS = 20;
export const FRAME_SAMPLES = (RATE_IN * FRAME_MS) / 1000;

// Client to server JSON frames
export const CLIENT = {
  start: "start",
  done: "done_narration",
  flushed: "playback_flushed",
  mute: "mute",
  end: "end",
};

// Server to client JSON frames
export const SERVER = {
  ready: "ready",
  phase: "phase",
  caption: "caption",
  card: "card",
  approval: "approval",
  progress: "progress",
  error: "error",
  closed: "closed",
};

// Frames that mean "stop playing right now". `cancel` is accepted as a synonym of `flush`.
export const FLUSH_TYPES = ["flush", "cancel"];

export const CARD_CONFIRM_FIELD = "confirm_field";

// Error codes that end the call.
export const FATAL_ERRORS = [
  "token_expired",
  "token_invalid",
  "budget_reached",
  "voice_unavailable",
  "voice_killed",
  "session_ended",
];

// WebSocket close codes the gateway may use when it refuses a connection.
export const TOKEN_CLOSE_CODES = [1008, 4401, 4403];

// Phases the server reports. Narration is the only one where the Done button makes sense.
export const PHASE_NARRATION = "narration";

export const WORKLET_URL = "/audio/capture-worklet.js";
export const WORKLET_NAME = "capture-processor";
