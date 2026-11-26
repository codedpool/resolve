# Eval report: intake_extraction

Models: qwen/qwen3.8-27b. Prompt: extract_facts@1:f85bb0ab0ff2. Runs: 60. Cost: $0.161.

| Measure | Result | Threshold |
|---|---|---|
| Critical-field accuracy | 81.7% | at least 90% |
| Fabricated values on not_stated fields | 8.0% | at most 2% |
| Accuracy on scenarios with approximate values | 87.5% | reported |

## Failures

- in01 order_id: expected `OD1234567890`, got `[NUM_1]` (stated)
- in02 order_id: expected `302-1112223-4445556`, got `[NUM_1]` (stated)
- in02 order_date: expected `2026-11-05`, got `2026-10-19` (approximate)
- in03 order_id: expected `SW44556677`, got `[NUM_1]` (stated)
- in04 order_id: expected `MY9876543`, got `[NUM_1]` (stated)
- in06 order_id: expected `TXN555666777`, got `[NUM_1]` (stated)
- in07 order_id: expected `CR220011`, got `[NUM_1]` (stated)
- in08 order_id: expected `MMT9988`, got `[NUM_1]` (stated)
- in08 promised_date: expected ``, got `2027-02-24` (approximate)
- in09 order_id: expected `NY778899`, got `[NUM_1]` (stated)
- in10 order_id: expected `BB1357924`, got `[NUM_1]` (stated)
- in10 promised_date: expected ``, got `2026-11-14` (approximate)
- in12 order_id: expected `AJ556677`, got `[NUM_1]` (stated)
- in12 order_date: expected `2026-11-19`, got `2026-11-16` (approximate)
- in13 order_id: expected `OD2020202020`, got `[NUM_1]` (stated)
- in13 promised_date: expected `2026-12-06`, got `2026-12-04` (inferred)
- in14 order_id: expected `RD123456`, got `[NUM_1]` (stated)
- in14 desired_remedy: expected `installation or refund`, got `` (not_stated)
- in15 order_id: expected `ME44221`, got `[NUM_1]` (stated)
- in17 order_id: expected `T2611261234567`, got `[NUM_1]` (stated)
- in18 order_id: expected `GB778899`, got `[NUM_1]` (stated)
- in20 order_id: expected `SD90909`, got `[NUM_1]` (stated)
