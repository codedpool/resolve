# Resolve client

The web app for Resolve, a tool that helps people in India chase a refund or fix a bad online purchase. Next.js (App Router), plain JavaScript and JSX, zod for validating API replies.

## Set up and run (PowerShell)

```powershell
cd client
npm install
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"   # the server; set NEXT_PUBLIC_WS_URL too if the socket host differs
npm run dev                                          # http://localhost:3000
```

Start the server first (see `../server/README.md`).

## Test

```powershell
npm test                  # Vitest and React Testing Library, no server needed
npx eslint .
npx playwright install chromium     # once
npm run test:e2e          # browser tests; they need the server running and skip themselves when it is not reachable
npm run test:e2e:full-text   # the whole product in text, with scripted vendors (see below)
```

## What is here

- `src/app` pages: sign in, cases, a case (facts, intake chat, evidence, permission card, approvals), the voice call page, approvals, inbox.
- `src/components` the screens' parts. A fact is confirmed only by pressing Accept on its card; no timer, no silence and no spoken "yes" confirms anything.
- `src/lib/api.js` the API client (token handling, step-up password prompt and retry). `src/lib/audio` microphone capture, the 16 kHz resampler, the 24 kHz playback queue with an instant flush, and the voice client. `public/audio/capture-worklet.js` is the microphone worklet.

## Practice call in text

A case with a current permission shows a **Practice call** section. You play the company: press Start practice call, read the assistant's opening line, type what a customer-care person might say, and press End call when you are done. A sentence the safety check stopped appears as a plain holding message. Details the company asks for that are not on the permission, and the summary of the call, appear in Approvals on the same page; the owner decides them with a password. Nothing reaches a real company, and the case keeps the "Simulated resolution" label.

## Full text walk-through (Playwright, no vendors)

`tests/e2e/full-text.spec.js` signs up, opens a case, narrates in text, answers the follow-up questions, accepts each detail, gives permission with the password, plays the company in a practice call (a false refund claim, a request for details outside the permission, a part-payment offer), ends the call and approves the summary. It checks that nothing outside the permission is said and that no settlement is accepted.

Needs: the Postgres container `resolve-db` on port 5434 (`docker compose up -d` in `server`), the server's virtual environment (`server\.venv`, see `../server/README.md`), and `npx playwright install chromium` once.

```powershell
cd client
npm run test:e2e:full-text      # about 20 seconds once the servers are up (the first start compiles the pages)
```

`playwright.full-text.config.js` starts both servers itself on spare ports, so a server you already run is not touched:

- the API on port 8010 through `server/scripts/run_e2e_server.py`. It drops and creates the database `resolve_e2e`, runs `alembic upgrade head`, makes a fresh `MASTER_KEY` and `JWT_SECRET` for that run only (the real `.env` keys are never used), blanks the vendor keys, and sets `RESOLVE_FAKE_VENDORS=1`. The switch is honoured only when `APP_ENV` is `dev` or `test`.
- the web app on port 3010 (`next dev`, writing to `.next-e2e`), pointed at that API.

The scripted stand-ins (fixed Hinglish story, keyword rules, scripted OCR, speech and drafting) are documented at the top of `server/app/devfakes.py`. Environment knobs: `E2E_PYTHON`, `E2E_API_PORT`, `E2E_WEB_PORT`, `E2E_DB_NAME`.

## Voice

The call page needs a microphone and works best with headphones, because the browser's echo cancellation is not perfect. Everything runs as a practice call: the person the agent talks to is played by a developer or a script, and the case shows "Simulated resolution".
