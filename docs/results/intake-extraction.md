# Eval report: intake_extraction

Models: qwen/qwen3.8-27b. Prompt: extract_facts@2:a900e0ba9583. Runs: 20. Cost: $0.056.

| Measure | Result | Threshold |
|---|---|---|
| Critical-field accuracy | 97.5% | at least 90% |
| Fabricated values on not_stated fields | 0.0% | at most 2% |
| Accuracy on scenarios with approximate values | 95.8% | reported |

## Failures

- in02 order_date: expected `2026-11-05`, got `2026-10-19` (approximate)
- in13 order_date: expected `2026-11-24`, got `2026-11-17` (approximate)
- in13 desired_remedy: expected `replacement`, got `` (not_stated)
