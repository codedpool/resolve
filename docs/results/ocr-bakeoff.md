# OCR bake-off and evidence reading

Thirty fictional documents (receipts, invoices and payment screenshots: 18 clean English, 3 English-Hindi mixed, 5 clean Hindi, and 4 noisy, slightly rotated pages, 2 English and 2 Hindi) drawn by `server/scripts/make_evidence_docs.py` from `workflows/evals/datasets/evidence.json`. Four fields per document: company, order id, amount, order date. Raw results: `ocr-bakeoff.json`. Script: `server/scripts/bake_ocr.py`.

| Engine | Field accuracy (120 fields) | English | Hindi | Mixed | Time for 30 |
|---|---|---|---|---|---|
| Tesseract 5.4, English plus Hindi data | 90% | 95% | 71% | 100% | 7 s |
| RapidOCR (a PaddleOCR-family engine, English and Chinese models) | 72% | 86% | 25% | 83% | 122 s |
| EasyOCR | not run: needs a large PyTorch install, and the Tesseract result already passes the bar | | | | |
| Cactus Mirage | not run: the plan's reasons still hold (no Hindi) | | | | |

Choice: Tesseract with English and Hindi data. It is installed with `winget install UB-Mannheim.TesseractOCR`, and the Hindi data file is downloaded into `server/data/tessdata` (git-ignored; the server's OCR adapter reads it from there). The engine runs three passes (English plus Hindi, English only, Hindi only) and the field finder takes the first value it can place across the passes.

## What the finder does about Tesseract's mistakes

Raw Tesseract plus a simple label parser scored 77.5%. The mistakes were consistent, so the finder handles them:
- The rupee sign is read as a stray `2`, `7`, `%` or a Devanagari digit. Amounts take the number after the sign, and when a labelled number starts with `7` the version without the `7` is kept as a second candidate. The check against a confirmed amount accepts either candidate. About 2 of 30 amounts still come out with the extra `7` as the first candidate.
- Hindi labels come out garbled ("रार्शा" for "राशि") and Hindi month names can be unreadable. The label match is loose; an unreadable month leaves the date empty, and the consumer types it.
- Letters at the start of an order id can be read as digits in the Hindi documents (`TC595343955` became `10595343955`). That cannot be repaired; the value goes to the consumer for confirmation, and a mismatch with a confirmed fact is flagged.

Twelve of the 120 fields are still wrong: 4 dates (unreadable Hindi month names), 3 order ids (prefix letters read as digits or a garbled label), 3 company names (noise characters on the first line of noisy pages) and 2 amounts (the stray `7`). All but the two amounts are in the Hindi or noisy pages. Strict first-candidate accuracy is 90%, above the 85% bar; the Hindi subset alone is 71%, which is why the vision path (with the owner's approval for that one image) and typing are always available.

## Limits of this test

The documents are drawn by me in two fonts with clean layouts, so real phone screenshots, photos of paper bills and handwriting will do worse. Treat 90% as an upper estimate for clean prints. Real documents from real consumers (with their consent) are needed to know more.
