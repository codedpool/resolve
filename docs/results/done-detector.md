# Narration done detector

Run on 27 Nov 2026 with `server/scripts/eval_done_detector.py` (live, the `classify` role, prompt `classify_done` version 1). Rows: `done-detector-v1.json`. Data: `workflows/evals/datasets/done_sentences.json`.

**39 of 40 right (97.5%); target at least 90%.** 19 messages that mean "I'm finished" and 21 that do not. A message counts as done only when the model says `done` with confidence at least 0.8, exactly as the intake graph decides. Messages longer than 10 words never reach the detector (they are treated as more narration), and the Done button always works.

- **Wrongly treated as done: 0 of 21.** This includes traps that contain words like "that's all", "enough" and "finished" but mean the opposite ("That's not all, there's more", "Is that enough detail?", "No, not yet, I'm not finished") and Hinglish and Devanagari continuations.
- **Done missed: 1 of 19.** "मुझे और कुछ नहीं कहना।" (Hindi, "I have nothing more to say") was read as more, with confidence 0.95. A missed done only means the person taps Done or says it again.

Limits: 40 short authored sentences (English, Hinglish and Devanagari), written for this check and not tuned on, spoken by nobody. It measures the text classifier, not speech: a real "that's all" has to be transcribed first, and Whisper may drop or change a very short utterance.
