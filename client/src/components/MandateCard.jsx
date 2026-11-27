"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/components/StepUpDialog";
import {
  BOUNDARIES,
  CALL_LIMITS,
  DISCLOSURE_FIELDS,
  EXPIRY_CHOICES,
  GOALS,
  NEVER_SHARED,
  draftFromMandate,
  formatDate,
  goalLabel,
  labelFor,
  mandateBody,
  minutesLabel,
  newDraft,
  readBack,
} from "@/lib/mandate";

export function MandateCard({ caseId, send = (path, options) => api.request(path, options), onChange }) {
  const [mandate, setMandate] = useState(undefined);
  const [step, setStep] = useState("view");
  const [draft, setDraft] = useState(newDraft());
  const [confirmed, setConfirmed] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);

  useEffect(() => {
    let live = true;
    send(`/cases/${caseId}/mandate`)
      .then((payload) => live && setMandate(payload.mandate))
      .catch((err) => {
        if (!live) return;
        setMandate(null);
        setError(`Could not load your mandate. ${err.message}. Refresh the page to try again.`);
      });
    return () => {
      live = false;
    };
    // The loader is a stable default; reloading on a new function identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  const items = readBack(draft);
  const allConfirmed = items.every((item) => confirmed.includes(item.key));
  const active = Boolean(mandate && mandate.active);

  function begin() {
    setDraft(draftFromMandate(mandate));
    setConfirmed([]);
    setError("");
    setNotice("");
    setStep("edit");
  }

  function change(next) {
    setDraft(next);
    setConfirmed([]);
  }

  function toggleField(key) {
    const has = draft.disclosure.includes(key);
    change({ ...draft, disclosure: has ? draft.disclosure.filter((item) => item !== key) : [...draft.disclosure, key] });
  }

  function toggleConfirmed(key) {
    setConfirmed((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }

  async function run(body, done) {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      const payload = await send(`/cases/${caseId}/mandate`, { method: "POST", body });
      setMandate(payload.mandate);
      setStep("view");
      setNotice(done);
      if (onChange) onChange(payload.mandate);
    } catch (err) {
      setError(`${err.message}. Your mandate was not changed. Check your password and try again.`);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  const save = () => run(mandateBody(draft), "Mandate saved. The assistant may now act for you within these limits.");
  const revoke = () => run({ action: "revoke" }, "Mandate cancelled. The assistant can no longer act for you.");

  if (mandate === undefined && !error) return <p>Loading your mandate.</p>;

  return (
    <section className="card mandate" aria-labelledby="mandate-title">
      <h2 id="mandate-title">Mandate: permission for the assistant</h2>

      {step === "view" ? (
        <>
          {active ? (
            <dl className="readback">
              <div>
                <dt>What you want</dt>
                <dd>{goalLabel(mandate.goal)}</dd>
              </div>
              <div>
                <dt>It may share</dt>
                <dd>{mandate.disclosure.map(labelFor).join(", ") || "Nothing"}</dd>
              </div>
              <div>
                <dt>Call length</dt>
                <dd>{minutesLabel(mandate.call_limit_seconds)}</dd>
              </div>
              <div>
                <dt>Ends on</dt>
                <dd>{formatDate(mandate.expires_at)}</dd>
              </div>
            </dl>
          ) : (
            <p>
              {mandate
                ? "Your last permission has ended. Give a new one so the assistant can act for you."
                : "The assistant cannot contact the company until you give it permission. You choose what it may say, and for how long."}
            </p>
          )}
          {notice ? (
            <p role="status" className="notice">
              {notice}
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="form-error">
              {error}
            </p>
          ) : null}
          <p className="actions">
            <button type="button" onClick={begin} disabled={busy}>
              {active ? "Change permission" : "Set up permission"}
            </button>
            {active ? (
              <button type="button" className="quiet" onClick={revoke} disabled={busy}>
                Cancel permission
              </button>
            ) : null}
          </p>
        </>
      ) : null}

      {step === "edit" ? (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            setStep("readback");
          }}
        >
          <label>
            What do you want?
            <select value={draft.goal} onChange={(event) => change({ ...draft, goal: event.target.value })}>
              {GOALS.some((goal) => goal.value === draft.goal) ? null : <option value={draft.goal}>{draft.goal}</option>}
              {GOALS.map((goal) => (
                <option key={goal.value} value={goal.value}>
                  {goal.label}
                </option>
              ))}
            </select>
          </label>

          <fieldset>
            <legend>What may it tell the company?</legend>
            <p className="hint">The first five are ticked for you. Untick any you want kept private.</p>
            {DISCLOSURE_FIELDS.map((field) => (
              <label key={field.key} className="check">
                <input type="checkbox" checked={draft.disclosure.includes(field.key)} onChange={() => toggleField(field.key)} />
                {field.label}
              </label>
            ))}
            <p className="hint">{NEVER_SHARED}</p>
          </fieldset>

          <div>
            <p className="subhead">What it will not do</p>
            <ul className="plain">
              {BOUNDARIES.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>

          <label>
            How long may a call last?
            <select value={draft.callLimitSeconds} onChange={(event) => change({ ...draft, callLimitSeconds: Number(event.target.value) })}>
              {CALL_LIMITS.map((choice) => (
                <option key={choice.seconds} value={choice.seconds}>
                  {choice.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            When should this permission end?
            <select value={draft.expiresInDays} onChange={(event) => change({ ...draft, expiresInDays: Number(event.target.value) })}>
              {EXPIRY_CHOICES.map((choice) => (
                <option key={choice.days} value={choice.days}>
                  In {choice.label}
                </option>
              ))}
            </select>
          </label>

          <p className="actions">
            <button type="submit">Read it back</button>
            <button type="button" className="quiet" onClick={() => setStep("view")}>
              Cancel
            </button>
          </p>
        </form>
      ) : null}

      {step === "readback" ? (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (allConfirmed) save();
          }}
        >
          <p>Check each line. Tick it when it is right. You can save once every line is ticked.</p>
          <ul className="readback-list">
            {items.map((item) => (
              <li key={item.key}>
                <div>
                  <p className="subhead">{item.title}</p>
                  <p>{item.text}</p>
                  {item.note ? <p>{item.note}</p> : null}
                </div>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={confirmed.includes(item.key)}
                    onChange={() => toggleConfirmed(item.key)}
                    aria-label={`${item.title} is right`}
                  />
                  This is right
                </label>
              </li>
            ))}
          </ul>
          {error ? (
            <p role="alert" className="form-error">
              {error}
            </p>
          ) : null}
          <p className="hint">You will be asked for your password when you save.</p>
          <p className="actions">
            <button type="submit" disabled={!allConfirmed || busy}>
              {busy ? "Saving" : "Save permission"}
            </button>
            <button type="button" className="quiet" onClick={() => setStep("edit")} disabled={busy}>
              Change something
            </button>
          </p>
        </form>
      ) : null}
    </section>
  );
}
