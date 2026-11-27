# Resolve

Resolve helps someone in India chase a refund or fix a bad online purchase. The person describes what happened, in Hindi, English or a mix, by typing or by voice. Resolve works out the facts, checks each one with them, and, only inside limits the person sets, practises a conversation with the company on their behalf.

**Everything here is a simulation.** No real company is contacted. The "company" on a practice call is a developer or a script, the demo companies are fictional, and the case shows "Simulated resolution". This is a research build, not legal advice, and not a service.

## How it works

1. **Tell the story.** The person narrates; the assistant stays quiet until they press Done (or say they are finished), then asks for one missing detail at a time, at most five questions.
2. **Confirm every detail.** Company, amount, order number, order date and what they want each appear on a card, with the person's own words beside it. Only a tap on Accept confirms a fact. A spoken "yes", a timer or silence never does.
3. **Check the evidence.** Receipts and screenshots are read on this machine with Tesseract. A picture goes to a vision model only if the person approves that one picture.
4. **Give permission.** A mandate lists what the assistant may say, what it must never say, how long a call may last and when the permission expires. Saving it needs the password again.
5. **Practise the call.** The assistant states it is an AI, answers claims by checking them against the person's evidence in code, cites rules from the official texts it retrieved, records offers instead of accepting them, refuses to share codes or card numbers whatever the mandate says, and asks the owner before sharing anything outside the list.
6. **Approve the summary.** What was said, promised or offered comes back as an approval the owner decides.

## Run it

You need Docker, and Groq and Rumik keys in `.env` (copy `.env.example`; `server/scripts/init_env.py` creates the local secret keys).

```powershell
docker compose up --build        # database, API on :8000, web app on :3000
```

For development without Docker, see `server/README.md`, `client/README.md` and `workflows/README.md`.

## Layout

| Folder | What is in it |
|---|---|
| `client/` | The web app: sign in, cases, intake chat, cards, permission screen, approvals, inbox, voice call page, practice call. |
| `server/` | The API, the voice gateway, redaction and encryption, the legal corpus and retrieval, persistence. |
| `workflows/` | The graphs (intake, evidence, discovery, outreach, follow-up), prompts, the output guard, datasets and evaluation runners. |
| `docs/` | Decisions and measured results. Every number below links to a file here. |

## What was measured

All of this is on **simulated** data and, unless noted, with scripted stand-ins for the model. Real people, real companies and real phone calls have not been tested.

| Area | Result | Where |
|---|---|---|
| Fact extraction from text (Qwen 3.8) | 97.5% of critical fields right, 0% invented values (20 runs, one repeat) | `docs/results/intake-extraction.md` |
| Spoken-number normaliser | 60 of 60 authored cases | `server/tests/test_numbers.py` |
| Redaction (150 strings) | no card, code, identity, address, phone or email survived; held-out probe found and fixed six gaps | `docs/results/redaction.md` |
| Speech to text on synthetic Hinglish | 55% of critical fields (order ids 20%); not a real-voice measurement | `docs/results/bakeoff-speech-and-models.md` |
| Time to first audio (prototype, 12 turns each) | median 0.8 s without the output guard; median 1.2 s and 95th percentile 1.3 s with it | `docs/decisions/gate-a.md` |
| OCR on 30 drawn documents | 90% of fields (Hindi pages 71%) | `docs/results/ocr-bakeoff.md` |
| Legal retrieval, 40 questions | right chunk in top 3 for 37 of 40; held-out Hindi subset one question short of the bar | `docs/results/retrieval.md` |
| Legal tag check vs author labels | 80% agreement; labels written by an AI, not a lawyer | `docs/results/legal-check.md` |
| Output guard, deterministic layer | 61 of 61 bad replies blocked, 0 of 50 ordinary sentences blocked; optimistic, rules and tests written together | `docs/results/safety-core.md` |
| Turn labels (live) | 48 of 52 right; Devanagari 3 of 6 | `docs/results/turn-understanding.md` |
| Practice call, scripted model, 15 behaviours x 5 runs | 75 of 75 pass; zero leaks or accepted settlements (95% bound about 4% for those inputs) | `docs/results/outreach.md` |
| Practice call, live Groq sample | 7 of 7 runs on three behaviours (a sample, not the suite) | `docs/results/outreach.md` |

## Limits you should know about

- The legal check is a language model checking another model's tags against retrieved text. It is not a lawyer, and no legal professional has reviewed the corpus. Every rule the assistant cites carries "AI-checked, not legal advice".
- Hinglish speech recognition accuracy is only as measured above, on synthetic audio. Order numbers are the weak point, which is why every critical detail is confirmed on a card.
- Several Groq models in use are previews and can be withdrawn; the role-to-model map in `server/config/models.yaml` has fallbacks.
- No company has accepted an AI representative in a test. A real OTP check by a real company would defeat any such assistant by design, and this one refuses to read codes out.
- One complaint type (a refund for an online purchase). All demo companies are fictional.
- Rumik does not state how long it keeps synthesis text; treat spoken text as sent to a vendor.
- The Groq account used for the measurements is on the free tier, so large evaluation runs were not possible and the full behaviour suite has not been run against a live model.
