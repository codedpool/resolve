"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/components/StepUpDialog";
import { HandoffForm, fieldLabel } from "@/components/HandoffForm";

export const IDLE_MS = 25000;

const defaultTimers = {
  set: (callback, ms) => setTimeout(callback, ms),
  clear: (id) => clearTimeout(id),
};

const defaultSend = (path, options) => api.request(path, options);

function describe(action, err) {
  return `${action} ${err?.message || "Check your connection and try again."}`;
}

/**
 * The intake conversation. While the person narrates the assistant stays silent, so only
 * non-null assistant text becomes a bubble. Nothing here ever calls a confirm endpoint.
 *
 * `timers` ({ set, clear }) and `idleMs` exist so tests can control the silence timer.
 */
export function IntakeChat({
  caseId,
  send = defaultSend,
  onFactsChanged,
  onEditDetails,
  idleMs = IDLE_MS,
  timers = defaultTimers,
}) {
  const [text, setText] = useState("");
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState("narrating");
  const [handoff, setHandoff] = useState([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const doneSent = useRef(false);
  const silenceSent = useRef(false);
  const log = useRef(null);

  const base = `/cases/${caseId}`;
  const closed = phase === "confirming" || phase === "closed";
  const hasPerson = messages.some((message) => message.who === "you");

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages]);

  const apply = useCallback(
    async (reply, spoken) => {
      const added = [];
      if (spoken) added.push({ who: "you", text: spoken });
      if (reply && typeof reply.text === "string" && reply.text) added.push({ who: "assistant", text: reply.text });
      if (added.length) setMessages((current) => [...current, ...added]);
      if (reply?.phase) setPhase(reply.phase);
      setHandoff(Array.isArray(reply?.handoff_fields) ? reply.handoff_fields : []);
      if (onFactsChanged) await onFactsChanged(reply);
    },
    [onFactsChanged],
  );

  async function submit(event) {
    event.preventDefault();
    const spoken = text.trim();
    if (!spoken || busy || closed) return;
    setBusy(true);
    setError("");
    try {
      const reply = await send(`${base}/intake/messages`, { method: "POST", body: { text: spoken } });
      setText("");
      await apply(reply, spoken);
    } catch (err) {
      setError(describe("We could not send your message. Your words are still in the box.", err));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (doneSent.current || closed) return;
    doneSent.current = true;
    setDone(true);
    setBusy(true);
    setError("");
    try {
      const pending = text.trim();
      if (pending) {
        const first = await send(`${base}/intake/messages`, { method: "POST", body: { text: pending } });
        setText("");
        await apply(first, pending);
      }
      const reply = await send(`${base}/narration-done`, { method: "POST" });
      await apply(reply);
    } catch (err) {
      // The request failed, so allow one more try.
      doneSent.current = false;
      setDone(false);
      setError(describe("We could not finish this step.", err));
    } finally {
      setBusy(false);
    }
  }

  // After a quiet spell, ask once whether to go ahead. Typing, new messages or a phase change reset or cancel it.
  useEffect(() => {
    if (phase !== "narrating" || !hasPerson || busy || silenceSent.current) return undefined;
    const id = timers.set(async () => {
      if (silenceSent.current) return;
      silenceSent.current = true;
      try {
        const reply = await send(`${base}/intake/silence`, { method: "POST" });
        await apply(reply);
      } catch (err) {
        setError(describe("We could not check in with you.", err));
      }
    }, idleMs);
    return () => timers.clear(id);
  }, [phase, hasPerson, busy, text, messages, idleMs, timers, send, base, apply]);

  function onKeyDown(event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent?.isComposing) {
      submit(event);
    }
  }

  const boxLabel = phase === "asking" ? "Your answer" : "What happened";

  return (
    <section className="intake" aria-label="Tell us what happened">
      <h2>Tell us what happened</h2>
      <p className="hint">
        Write in English, Hindi or both, in your own words. Add as much as you like, then choose Done and we will ask
        about anything missing.
      </p>

      <div className="chat-log" ref={log} role="log" aria-live="polite" aria-label="Conversation" tabIndex={0}>
        {messages.map((message, index) => (
          <p key={`${message.who}-${index}`} className={`bubble bubble-${message.who}`}>
            <span className="bubble-who">{message.who === "you" ? "You" : "Resolve"}</span>
            <span className="bubble-text" dir="auto">
              {message.text}
            </span>
          </p>
        ))}
      </div>

      {closed ? (
        <div className="intake-closed">
          <p className="notice">We have what we need from the chat. Check each detail below and accept it or correct it.</p>
          {handoff.length ? (
            <div className="handoff">
              <p className="notice" data-testid="handoff-line">
                We could not get these from the chat: {handoff.map(fieldLabel).join(", ")}. Please type them into the form
                below.
              </p>
              <HandoffForm caseId={caseId} fields={handoff} send={send} onSaved={onFactsChanged} />
            </div>
          ) : null}
          <p className="actions">
            <button type="button" className="quiet" onClick={() => onEditDetails && onEditDetails()}>
              Add or correct a detail
            </button>
          </p>
        </div>
      ) : null}

      <form className="composer" onSubmit={submit}>
        <label>
          {boxLabel}
          <textarea
            dir="auto"
            rows={4}
            value={text}
            disabled={closed}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
          />
        </label>
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        <p className="actions">
          <button type="submit" disabled={closed || busy || !text.trim()}>
            Send
          </button>
          {phase === "narrating" ? (
            <button type="button" className="quiet" onClick={finish} disabled={done}>
              Done
            </button>
          ) : null}
        </p>
      </form>
    </section>
  );
}
