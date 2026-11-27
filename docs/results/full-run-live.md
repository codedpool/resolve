# One whole case on real vendors

Run on 27 and 28 Nov 2026 with `server/tests/integration/test_full_run_live.py` (marked `live`). Each step is recorded in `full-run-live.json`.

**Every step passed in one run.** The company, the person and the order number are invented.

| Step | What happened |
|---|---|
| Intake | A Hinglish text narration ("Zeta Mart se phone mangaya... refund dene se mana kar diya") went through the real extraction model. The assistant asked three questions (order number, date, what the person wants), the test answered them, and the case reached `confirming`. Ten fields were extracted, including company `Zeta Mart`, amount `3000` and the order number `ZM48210937` as the person gave it (the model only ever saw the placeholder). |
| Confirm | Every fact was confirmed one at a time with Accept; the case became `ready_for_mandate`. |
| Mandate | The mandate was signed after the password step-up and became active. |
| Provider call | Rumik spoke the company's offer ("a voucher of five hundred rupees as a full and final settlement"), Whisper heard it word for word, and the real graph and guard answered: "I am not able to accept or counter it on my own; I have noted your voucher offer and will pass it to the customer, who will decide through the app." Rumik spoke it back. |
| Approval | The offer became a pending summary approval, which the owner rejected with the password step-up. |

## What this does not show

- One run, one story, one invented company. It shows the pieces connect on real vendors; it is not a measure of how often they do.
- The consumer's story was typed, not spoken. The spoken half is the provider's side, which is the half that has to resist hostile input.
- The provider's voice is synthetic, so this is not a real-voice test.
- Between steps the free tier asked the test to wait (`model_busy`); the test waits and retries, as a real client would. The wall-clock time of the run is not reported because the machine paused partway through.
