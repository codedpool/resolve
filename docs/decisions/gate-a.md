# Gate A: own voice pipeline or Rumik managed agent

Decided 26 Nov 2026 on synthetic audio and live vendor calls.

## Stop conditions

| Condition | Measured | Result |
|---|---|---|
| Best speech-to-text critical-field accuracy below 80% | 55% on synthetic Hinglish (order ids 20%) | Trips on paper. The measurement is a floor: the audio is TTS output with its own misreadings, and no real voices were tested. |
| p95 time to first audio above 4 s | 0.87 s without the guard, 1.31 s with a per-sentence policy check, 12 turns each | Passes with wide margin. Median stage times: speech 215-240 ms, classify 125-155 ms, first sentence 145 ms, guard 445 ms, speech synthesis first chunk 280 ms. |
| Rumik speech synthesis unacceptable for Hindi and Hinglish | First chunk 275-303 ms; Hinglish and Hindi both returned audio; not judged by ear | Passes on speed. Quality by ear is not assessed. |
| Credits not covering the plan | Balance not read | Unknown. |

## Decision

Stay on the own pipeline, and finish the text-first product (intake, evidence, legal check, outreach) before the voice phase. Reasons:
1. Everything before the voice phase is text and does not depend on this choice.
2. The failing condition is about speech recognition accuracy. The managed Rumik agent would face the same problem, and it gives less control over confirming ids. The product's answer to weak id recognition is the same under both options: each critical field is confirmed by the user on a card, and ids can be typed.
3. Latency is not the risk. A hand-built gateway is fast enough with margin.
4. The measurement is too weak to justify a switch. The fallback stays documented, and the final voice gate is rerun with real recordings. If real-voice field accuracy is still far below the text reference there, switch to the fallback then.

## Transport, speech detection, framework

- Transport: hand-built FastAPI WebSocket gateway; the browser sends 16 kHz PCM. A framework such as Pipecat puts turn-taking in its own pipeline, which conflicts with the rule that LangGraph owns every turn. It was not trialled; this is a design decision, not a measurement.
- Speech detection: the energy-modulation gate (`app/voice/gate.py`) now, tested on the synthetic set. Silero ONNX is evaluated in the voice phase on real recordings.
- Rumik protocol facts for the gateway: one websocket stays open for the whole call; one frame per sentence; a single frame's audio is cut at about 25 seconds, so long text must be split by sentence; `cancel` was acknowledged in 28 ms with at most one late chunk; a `done` frame for the cancelled request can still arrive afterwards, so the gateway must match frames by `request_id` and must not treat the first `done` as the end of the next request.
- Output-guard policy model: gpt-oss-20b, because the safeguard model is capped at 3 requests per minute on this account.
