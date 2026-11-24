# Voice defaults

Chosen on 24 Nov 2026 from the smoke calls, not from a listening session.

Speech synthesis uses Rumik `mulberry` with language `hinglish`. That model lists Hindi, Hinglish and English, and the Hinglish clip returned audio in about 300 ms. `muga` is the fallback if `mulberry` is withdrawn. No named speaker is set; the socket call in the smoke test worked without one.

Narration transcription uses `whisper-large-v3`. Short turns use `whisper-large-v3-turbo`. The language parameter is left unset so a Hindi-English mix is not forced into one code. These are the published role defaults. They should be replaced if a later recording set shows a better setting.

Hallucination drops, until a recording set is available to tune them: `no_speech_prob` above 0.6, `avg_logprob` below -1.0, or `compression_ratio` above 2.4. Those are Whisper's usual quality flags, not a measured threshold on our clips.

Qwen roles send `reasoning_effort=none`. gpt-oss classify, judge, review and simulator roles send `low`.
