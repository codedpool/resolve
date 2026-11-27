# Barge-in on the real voice path

Run on 27 Nov 2026 with `server/tests/integration/test_barge_in_live.py` (marked `live`), 30 trials. Rows are in `barge-in-live.json`.

**30 of 30 trials stopped within 500 ms (threshold: 90%).** Median 22 ms, slowest 30 ms. In no trial did any audio arrive after the flush frame (checked for 300 ms).

Each trial opens a provider call against real Rumik synthesis, waits until the assistant's opening line is audible (a caption and two audio chunks received), then sends speech-like audio. The time measured is from the frame that completes 100 ms of speech to the `flush` frame the server sends to tell the browser to empty its playback queue.

## What this does and does not measure

- **Server side only.** The 100 ms of speech the endpointer needs to report a start is real time that comes before this clock starts (the endpointer's own threshold is 90 ms). The browser's flush of its playback queue, the network and the audio already buffered in the browser are not included, so what a person would experience is longer than 22 ms: about 100 ms of speech plus the network plus whatever the browser had queued.
- **Audio is sent faster than real time**, as a burst, so the clock includes the server also reading the rest of the burst.
- **Speech-like tone, not a voice.** The interrupting audio is a synthetic modulated tone that the endpointer treats as speech; a real person's onset and a noisy room would behave differently.
- The assistant's cancel is a message to Rumik (`cancel`); that it is acknowledged is checked by the absence of stray audio, not by timing Rumik's side separately.
- Cost: about 100 characters of Rumik synthesis per trial.
