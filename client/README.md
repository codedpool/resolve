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
```

## What is here

- `src/app` pages: sign in, cases, a case (facts, intake chat, evidence, permission card, approvals), the voice call page, approvals, inbox.
- `src/components` the screens' parts. A fact is confirmed only by pressing Accept on its card; no timer, no silence and no spoken "yes" confirms anything.
- `src/lib/api.js` the API client (token handling, step-up password prompt and retry). `src/lib/audio` microphone capture, the 16 kHz resampler, the 24 kHz playback queue with an instant flush, and the voice client. `public/audio/capture-worklet.js` is the microphone worklet.

## Voice

The call page needs a microphone and works best with headphones, because the browser's echo cancellation is not perfect. Everything runs as a practice call: the person the agent talks to is played by a developer or a script, and the case shows "Simulated resolution".
