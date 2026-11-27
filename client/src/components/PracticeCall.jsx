"use client";

import { useEffect, useId, useRef, useState } from "react";

import { api } from "@/components/StepUpDialog";

const defaultSend = (path, options) => api.request(path, options);

/** What the assistant says in place of a sentence the safety check stopped. Shown as a plain holding message. */
const HOLDING_LINES = new Set([
  "I will need to check that with the customer.",
  "मुझे यह ग्राहक से पूछकर देखना होगा।",
  "Mujhe yeh customer se check karna hoga.",
]);

export const END_REASONS = {
  promise_secured: "The company gave a dated promise with a reference number.",
  offer_outside_mandate: "The company made an offer outside what you allowed. The assistant did not accept it. You decide.",
  escalate_after_stalls: "The company kept stalling and gave no date.",
  repeated_refusal: "The company refused again and again.",
  repeated_data_requests: "The company kept asking for details that are not on your permission.",
  no_response: "Nobody answered.",
  time_limit: "The call reached its time limit.",
  turn_limit: "The call reached its turn limit.",
  ended_by_consumer: "You ended the call.",
  mandate_blocked: "Your permission is no longer valid, so the call stopped.",
};

const IDEAS = [
  { label: "Say the refund was sent", text: "Your refund has already been processed to your account." },
  { label: "Offer a part payment", text: "We can offer a voucher of 2000 rupees as a final settlement." },
  { label: "Ask for the phone number", text: "Please give the customer's phone number and email." },
  { label: "Stall", text: "Please hold, we are checking." },
];

function describe(action, err) {
  return `${action} ${err?.message || "Check your connection and try again."}`;
}

function toLines(who, sentences) {
  return (Array.isArray(sentences) ? sentences : []).map((text) => ({
    who,
    text,
    held: who === "agent" && HOLDING_LINES.has(String(text).trim()),
  }));
}

/**
 * A practice call in text. The person plays the company: they type what a customer-care agent might say, and the
 * assistant answers inside the permission the owner gave. Nothing here decides an approval. When the call ends, the
 * summary appears in the Approvals section, which the owner decides with a password.
 *
 * `onChange` runs after each step so the case page can refresh its status and its approvals.
 */
export function PracticeCall({ caseId, mandateActive, send = defaultSend, onChange }) {
  const [call, setCall] = useState(null); // { id, ended, reason, blocked }
  const [lines, setLines] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [waiting, setWaiting] = useState({ summary: 0, disclosure: 0 });
  const log = useRef(null);
  const titleId = useId();

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [lines]);

  async function refresh() {
    try {
      const list = await send(`/approvals?case=${caseId}`);
      const pending = (list.approvals || []).filter((item) => item.status === "pending");
      setWaiting({
        summary: pending.filter((item) => item.kind === "summary").length,
        disclosure: pending.filter((item) => item.kind === "disclosure").length,
      });
    } catch {
      // The notice is a convenience. The Approvals section below is the source of truth.
    }
    if (onChange) await onChange();
  }

  function absorb(reply, spoken) {
    const added = [];
    if (spoken) added.push({ who: "you", text: spoken });
    added.push(...toLines("agent", reply.sentences));
    if (added.length) setLines((current) => [...current, ...added]);
    const blocked = reply.phase === "blocked";
    setCall((current) =>
      current ? { ...current, ended: Boolean(reply.ended) || blocked, reason: reply.end_reason || (blocked ? "mandate_blocked" : current.reason), blocked } : current,
    );
  }

  async function start() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const reply = await send(`/cases/${caseId}/outreach/calls`, { method: "POST" });
      setLines([]);
      setWaiting({ summary: 0, disclosure: 0 });
      setCall({ id: reply.call_id, ended: Boolean(reply.ended), reason: reply.end_reason || "", blocked: false });
      setLines(toLines("agent", reply.sentences));
      await refresh();
    } catch (err) {
      setError(describe("We could not start the practice call.", err));
    } finally {
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    const spoken = text.trim();
    if (!spoken || busy || !call || call.ended) return;
    setBusy(true);
    setError("");
    try {
      const reply = await send(`/calls/${call.id}/provider-turn`, { method: "POST", body: { text: spoken } });
      setText("");
      absorb(reply, spoken);
      await refresh();
    } catch (err) {
      setError(describe("We could not send that. Your words are still in the box.", err));
    } finally {
      setBusy(false);
    }
  }

  async function end() {
    if (busy || !call || call.ended) return;
    setBusy(true);
    setError("");
    try {
      const reply = await send(`/calls/${call.id}/end`, { method: "POST" });
      absorb({ ...reply, ended: true }, "");
      await refresh();
    } catch (err) {
      setError(describe("We could not end the call.", err));
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent?.isComposing) submit(event);
  }

  const live = Boolean(call && !call.ended);
  const waitingNote = [];
  if (waiting.disclosure) waitingNote.push("The company asked for details that are not on your permission. The assistant did not share them. You can decide in Approvals below.");
  if (waiting.summary) waitingNote.push("The summary of the call is waiting for your approval in Approvals below.");

  return (
    <section className="call practice" aria-labelledby={titleId}>
      <h2 id={titleId}>Practice call</h2>
      <p className="hint">
        You play the company. Type what a customer-care person might say and see how the assistant answers. Nothing reaches a
        real company.
      </p>

      {!call ? (
        <>
          {mandateActive ? null : <p className="notice">Give the assistant permission above first. Then you can start a practice call.</p>}
          <p className="actions">
            <button type="button" onClick={start} disabled={!mandateActive || busy}>
              Start practice call
            </button>
          </p>
        </>
      ) : (
        <>
          <p className="call-status" role="status">
            <span className={`dot ${live ? "dot-live" : "dot-ended"}`} aria-hidden="true" />
            <span className="call-connection">{live ? "Practice call in progress" : "The call has ended"}</span>
          </p>
          {call.ended && call.reason ? <p className="notice">{END_REASONS[call.reason] || "The call has ended."}</p> : null}

          <div className="chat-log" ref={log} role="log" aria-live="polite" aria-label="The call" tabIndex={0}>
            {lines.map((line, index) => (
              <p key={`${line.who}-${index}`} className={`bubble bubble-${line.who === "you" ? "you" : "assistant"}${line.held ? " bubble-held" : ""}`}>
                <span className="bubble-who">{line.who === "you" ? "You, as the company" : line.held ? "Assistant, holding" : "Assistant"}</span>
                <span className="bubble-text" dir="auto">
                  {line.text}
                </span>
              </p>
            ))}
          </div>

          {waitingNote.map((note) => (
            <p key={note} className="notice" role="status">
              {note} <a href="#approvals">Go to Approvals</a>
            </p>
          ))}

          {live ? (
            <form className="composer" onSubmit={submit}>
              <label>
                What the company says
                <textarea dir="auto" rows={3} value={text} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown} />
              </label>
              <div className="ideas" role="group" aria-label="Ideas for what to say">
                <span className="hint">Ideas:</span>
                {IDEAS.map((idea) => (
                  <button key={idea.label} type="button" className="quiet" onClick={() => setText(idea.text)}>
                    {idea.label}
                  </button>
                ))}
              </div>
              {error ? (
                <p className="form-error" role="alert">
                  {error}
                </p>
              ) : null}
              <p className="actions call-controls">
                <button type="submit" disabled={busy || !text.trim()}>
                  Send
                </button>
                <button type="button" className="stamp" onClick={end} disabled={busy}>
                  End call
                </button>
              </p>
            </form>
          ) : (
            <>
              {error ? (
                <p className="form-error" role="alert">
                  {error}
                </p>
              ) : null}
              <p className="actions">
                <button type="button" onClick={start} disabled={!mandateActive || busy}>
                  Start a new practice call
                </button>
              </p>
            </>
          )}
        </>
      )}
      {!call && error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
