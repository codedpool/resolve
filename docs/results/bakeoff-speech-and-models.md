# Speech and model bake-off

Run on 26 Nov 2026 with `scripts/make_audio.py`, `bake_stt.py` and `bake_llm.py` in the server repo. Raw numbers are in `s0.3-stt.json` and `s0.3-llm.json`.

## What was measured, and its limits

No human recordings exist yet, so the speech set is synthetic: ten Hinglish complaint scripts read by Rumik TTS (one frame per sentence), each in a quiet version and a version with noise mixed in at about 12 dB, plus 20 noise clips (6 silence, 8 room noise, 6 quiet background speech). Synthetic audio is cleaner than real calls, but it also carries the TTS's own mistakes: it reads some ids oddly (for example "MY" came out as "LAS I"). The accuracy figures below are therefore a rough indication, and a floor for ids. They do not replace real voices. Real recordings are still needed for the final voice check.

## Speech to text

Critical fields are merchant, amount and order id, scored after the same Qwen extraction prompt. Each row covers 10 scripts, quiet and noisy together.

| Model | Language setting | Critical-field accuracy |
|---|---|---|
| whisper-large-v3 | en | 55% |
| whisper-large-v3 | auto | 52% |
| whisper-large-v3 | hi | 52% |
| whisper-large-v3-turbo | en | 43% |
| whisper-large-v3-turbo | auto | 43% |
| whisper-large-v3-turbo | hi | 38% |

Per field, large-v3: amount 44/60, merchant 39/60, order id 12/60. Turbo: amount 39/60, merchant 26/60, order id 10/60. Order ids are the weak point. Forcing `en` raises the score only because it drops the Hindi words and keeps Latin ids and brand names; it loses Hindi content, so it is not used. Large-v3 beats turbo on every field.

Choice: `whisper-large-v3` with the language unset, for narration and for turns. Turbo is only about 60 ms faster in the latency run, and time to first audio has plenty of margin. Order ids, amounts and dates are always confirmed one by one by the user (the confirmation cards), so low id accuracy is caught there and does not become a wrong claim.

## Invented text

All 14 silence and room-noise clips produced text from Whisper: "Thank you for watching", "Takk for watching!", "Kansai International Airport", "you", lone full stops. The segment statistics do not separate this from real speech:

| | no_speech_prob (2%, median, 98%) | avg_logprob | compression_ratio |
|---|---|---|---|
| real speech segments (953) | 0, 0.0, 0.33 | -1.5, -0.28, -0.07 | 0.77, 1.45, 2.28 |
| noise segments (58) | 0, 0.12, 0.7 | -1.14, -0.46, -0.21 | 0.2, 0.53, 1.91 |

Any threshold that removes most of the noise text also removes 30 to 40% of real segments (for example `avg_logprob < -0.5` passes 52% of the noise and drops 38% of speech). The earlier default thresholds (no_speech 0.6, logprob -1.0, compression 2.4) let 93% of noise segments through. So thresholds are not the defence.

What works is a gate before transcription (`app/voice/gate.py`). Speech alternates loud and quiet 30 ms frames; steady noise and silence do not. On this set the gate passes all 20 narrations (quiet and noisy) and rejects all 14 silence and room clips. It passes five of six quiet background-speech clips, which is correct, since that is speech. A phrase list drops known hallucinations that slip through. A trained VAD (Silero ONNX) can replace it behind the same `looks_like_speech` call once real room recordings exist.

## Language models (Groq)

Extraction on the clean scripts, same prompt and strict schema: all three models got 30/30 critical fields. Mean call time: Qwen 3.8 0.20 s, gpt-oss-20b 0.42 s, gpt-oss-120b 0.58 s.

Turn classification on 30 labelled sentences (English and Hindi, seven labels):

| Model | Correct | Mean time |
|---|---|---|
| qwen/qwen3.8-27b (instruct) | 26/30 (87%) | 0.2 s |
| openai/gpt-oss-120b | 22/30 | 0.58 s |
| openai/gpt-oss-20b | 21/30 | 0.42 s |

Most misses are overlap in my own labels ("can you tell me the order number again?" is a question and also a data request); all four of Qwen's misses are of that kind. Injection sentences are also screened separately by Prompt Guard. Choice: `classify` moves from gpt-oss-20b to Qwen instruct. 87% is under the 90% bar on this small set, so the labels need tightening and the set needs to grow when the turn classifier is built, which is where the bar is tested.

## Groq account limits found

Response headers on this account show 1000 requests per day and 8000 tokens per minute on Qwen 3.8, gpt-oss-20b and gpt-oss-120b. The safeguard model shows 2000 tokens per minute and **3 requests per minute**. That looks like the free tier, not the Developer tier the docs describe. Consequences:
- The safeguard model cannot sit on every spoken sentence. The output-guard policy check uses gpt-oss-20b instead (`config/models.yaml`).
- A large evaluation run will hit the daily and per-minute caps. The paid tier has to be switched on in the Groq console before large evaluation runs. Only the account owner can do that.
