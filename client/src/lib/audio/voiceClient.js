import {
  CALL_ROLE,
  CALLS_PATH,
  CLIENT,
  FATAL_ERRORS,
  FLUSH_TYPES,
  PHASE_NARRATION,
  SERVER,
  TOKEN_CLOSE_CODES,
  WS_PATH,
  WS_TOKEN_PARAM,
  endCallPath,
} from "./constants";
import { createEmitter } from "./emitter";
import { codeForRequestError, describeEnded, describeVoiceError } from "./errors";

export function buildSocketUrl(call, wsRoot = "") {
  let base = call.ws_url || WS_PATH;
  if (/^https?:\/\//.test(base)) base = base.replace(/^http/, "ws");
  else if (!/^wss?:\/\//.test(base)) base = `${wsRoot.replace(/\/$/, "")}${base.startsWith("/") ? "" : "/"}${base}`;
  const joiner = base.includes("?") ? "&" : "?";
  return `${base}${joiner}${WS_TOKEN_PARAM}=${encodeURIComponent(call.ws_token)}`;
}

/** The functions that talk to the REST API, built on the app's api client. */
export function restCalls(api) {
  return {
    requestCall: (caseId) => api.request(CALLS_PATH, { method: "POST", body: { case_id: caseId, role: CALL_ROLE } }),
    requestEnd: (callId) => api.request(endCallPath(callId), { method: "POST" }),
  };
}

/**
 * One voice call, one WebSocket, no reconnecting. Events:
 *   state     "idle" | "connecting" | "live" | "ended" | "error"
 *   caption   { who: "user" | "agent", text, final }  (text is redacted by the server)
 *   card      { kind, factId }
 *   approval  { approvalId }
 *   phase     { phase }
 *   progress  { text, runId }
 *   speaking  true | false
 *   muted     true | false
 *   done      (the Done trigger was sent)
 *   error     { code, message }
 *   ended     { reason, message }
 *
 * All browser pieces are injected so tests can use fakes:
 *   requestCall(caseId) -> { call_id, ws_url, ws_token }     requestEnd(callId)
 *   WebSocketImpl                                              wsRoot
 *   createCapture({ onFrame }) -> { start, mute, stop }        createPlayback() -> playback queue
 *
 * Nothing here confirms a fact. Cards only ask the page to show a confirmation card.
 */
export function createVoiceClient({ requestCall, requestEnd, WebSocketImpl, createCapture, createPlayback, wsRoot = "" }) {
  const events = createEmitter();
  let state = "idle";
  let socket = null;
  let capture = null;
  let playback = null;
  let callId = null;
  let sending = false;
  let muted = false;
  let doneSent = false;
  let phase = null;
  let finished = false;
  let session = 0;

  function setState(next) {
    if (state === next) return;
    state = next;
    events.emit("state", next);
  }

  function sendJson(message) {
    if (!socket || socket.readyState !== 1) return false;
    socket.send(JSON.stringify(message));
    return true;
  }

  function sendFrame(frame) {
    // Only PCM16 frames go out as binary, and only while the call is live and the microphone is on.
    if (!sending || muted || !socket || socket.readyState !== 1) return;
    const bytes = frame.buffer.byteLength === frame.byteLength ? frame.buffer : frame.slice().buffer;
    socket.send(bytes);
  }

  function release() {
    sending = false;
    if (capture) capture.stop();
    if (playback) {
      const finishing = playback;
      finishing.flush();
      Promise.resolve(finishing.close?.()).catch(() => {});
    }
    capture = null;
    playback = null;
    if (socket) {
      const closing = socket;
      socket = null;
      closing.onopen = closing.onmessage = closing.onerror = closing.onclose = null;
      try {
        if (closing.readyState === 0 || closing.readyState === 1) closing.close(1000);
      } catch {
        // The socket is gone already.
      }
    }
  }

  function fail(code, rawMessage) {
    if (finished) return;
    finished = true;
    const id = callId;
    release();
    setState("error");
    events.emit("error", { code, message: describeVoiceError(code, rawMessage) });
    if (id && code === "connection_lost") Promise.resolve(requestEnd?.(id)).catch(() => {});
  }

  function finish(reason) {
    if (finished) return;
    finished = true;
    release();
    setState("ended");
    events.emit("ended", { reason, message: describeEnded(reason) });
  }

  function handleJson(message) {
    switch (message.type) {
      case SERVER.ready:
        if (message.rate_out && playback) playback.setSampleRate?.(message.rate_out);
        sending = true;
        if (muted) sendJson({ type: CLIENT.mute, on: true });
        setState("live");
        break;
      case SERVER.phase:
        phase = message.phase;
        events.emit("phase", { phase: message.phase });
        break;
      case SERVER.caption:
        events.emit("caption", { who: message.who, text: message.text, final: message.final !== false });
        break;
      case SERVER.card:
        events.emit("card", { kind: message.kind, factId: message.fact_id });
        break;
      case SERVER.approval:
        events.emit("approval", { approvalId: message.approval_id });
        break;
      case SERVER.progress:
        events.emit("progress", { text: message.text, runId: message.run_id });
        break;
      case SERVER.error:
        if (FATAL_ERRORS.includes(message.code)) fail(message.code);
        else events.emit("error", { code: message.code, message: describeVoiceError(message.code) });
        break;
      case SERVER.closed:
        if (message.reason && FATAL_ERRORS.includes(message.reason)) fail(message.reason);
        else finish(message.reason || "completed");
        break;
      default:
        if (FLUSH_TYPES.includes(message.type)) {
          // Barge-in: stop speaking at once, then tell the server the queue is empty.
          playback?.flush();
          sendJson({ type: CLIENT.flushed });
        }
    }
  }

  function handleMessage(event) {
    if (finished) return;
    const { data } = event;
    if (typeof data === "string") {
      let message;
      try {
        message = JSON.parse(data);
      } catch {
        return;
      }
      if (message && typeof message === "object") handleJson(message);
      return;
    }
    if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) playback?.enqueue(data);
  }

  function openSocket(url, mine) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocketImpl(url);
      ws.binaryType = "arraybuffer";
      socket = ws;
      ws.onopen = () => resolve();
      ws.onerror = () => {};
      ws.onclose = (event) => {
        if (mine !== session) return;
        if (socket === ws && state === "connecting") reject(Object.assign(new Error("closed"), { closeCode: event?.code }));
        else if (!finished) fail("connection_lost");
      };
      ws.onmessage = handleMessage;
    });
  }

  return {
    on: events.on,
    get state() {
      return state;
    },
    get muted() {
      return muted;
    },
    get doneSent() {
      return doneSent;
    },
    get phase() {
      return phase;
    },

    /** Starts the call. Call this from a click so the browser lets audio play. */
    async start(caseId) {
      if (state === "connecting" || state === "live") return;
      session += 1;
      const mine = session;
      finished = false;
      doneSent = false;
      muted = false;
      phase = null;
      callId = null;
      setState("connecting");

      playback = createPlayback();
      playback.on?.("playing", (value) => events.emit("speaking", value));
      playback.resume?.();
      capture = createCapture({ onFrame: sendFrame });

      try {
        // The microphone comes first, so a denied permission never wastes the single-use token.
        await capture.start();
      } catch (error) {
        if (mine === session) fail(error?.code || "microphone_unavailable", error?.message);
        return;
      }
      if (mine !== session || finished) return;

      let call;
      try {
        call = await requestCall(caseId);
      } catch (error) {
        if (mine === session) fail(codeForRequestError(error));
        return;
      }
      if (mine !== session || finished) return;
      callId = call.call_id;

      try {
        await openSocket(buildSocketUrl(call, wsRoot), mine);
      } catch (error) {
        if (mine === session) fail(TOKEN_CLOSE_CODES.includes(error?.closeCode) ? "token_expired" : "connect_failed");
        return;
      }
      if (mine !== session || finished) return;
      sendJson({ type: CLIENT.start });
    },

    /** Narration is finished. Sent at most once per call. Returns true when it was sent. */
    done() {
      if (doneSent || state !== "live") return false;
      if (phase && phase !== PHASE_NARRATION) return false;
      if (!sendJson({ type: CLIENT.done })) return false;
      doneSent = true;
      events.emit("done");
      return true;
    },

    setMuted(on) {
      muted = Boolean(on);
      capture?.mute(muted);
      sendJson({ type: CLIENT.mute, on: muted });
      events.emit("muted", muted);
    },

    /** Ends the call from this side. Safe to call twice. */
    async end() {
      if (finished || state === "idle") return;
      const id = callId;
      sendJson({ type: CLIENT.end });
      session += 1;
      finish("user");
      if (id && requestEnd) {
        try {
          await requestEnd(id);
        } catch {
          // The socket is closed already, so the server ends the call on its own.
        }
      }
    },

    /** Leaving the page: close everything without any events or requests. */
    dispose() {
      session += 1;
      finished = true;
      release();
      events.clear();
    },
  };
}
