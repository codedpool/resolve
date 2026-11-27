import { createCapture } from "./capture";
import { createPlayback } from "./playback";
import { createVoiceClient, restCalls } from "./voiceClient";

/** Wires the voice client to the real browser: microphone, audio output and WebSocket. */
export function createBrowserVoiceClient(api) {
  // Browser objects are looked up when the call starts, so this is safe to build while rendering on the server.
  const audioContextClass = () => window.AudioContext || window.webkitAudioContext;
  return createVoiceClient({
    ...restCalls(api),
    WebSocketImpl: function BrowserSocket(url) {
      return new window.WebSocket(url);
    },
    wsRoot: process.env.NEXT_PUBLIC_WS_URL || process.env.NEXT_PUBLIC_API_URL?.replace(/^http/, "ws") || "",
    createCapture: ({ onFrame }) =>
      createCapture({
        mediaDevices: navigator.mediaDevices,
        AudioContextClass: audioContextClass(),
        AudioWorkletNodeClass: window.AudioWorkletNode,
        onFrame,
      }),
    createPlayback: () => createPlayback({ context: new (audioContextClass())() }),
  });
}
