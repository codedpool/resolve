"use client";

import { useRef, useState } from "react";

import { imageFor, parsePayload } from "@/lib/approvals";

const STATUS_TEXT = {
  approved: "You approved this.",
  rejected: "You said no to this.",
  expired: "This request ran out of time. Nothing was done.",
};

function Detail({ payload, keys }) {
  const rows = keys.filter((key) => payload[key]);
  if (!rows.length) return null;
  return (
    <dl className="readback">
      {rows.map((key) => (
        <div key={key}>
          <dt>{key.replace(/_/g, " ")}</dt>
          <dd>{Array.isArray(payload[key]) ? payload[key].join(", ") : String(payload[key])}</dd>
        </div>
      ))}
    </dl>
  );
}

function Body({ approval, payload, evidence, names }) {
  if (approval.kind === "send_image_to_llm") {
    const image = imageFor(approval, payload, evidence, names);
    return (
      <>
        <h3>Send this image to a vision model?</h3>
        <p className="image-name">
          Image: <strong>{image.label}</strong>
        </p>
        <p>
          If you approve, this image will be sent to a vision model, an AI service run by an outside company, so it can read the text on it.
          Nothing is sent unless you approve.
        </p>
        <p>If you say no, the image stays here and you can type the details yourself.</p>
      </>
    );
  }
  if (approval.kind === "contact") {
    return (
      <>
        <h3>Use this contact for the company?</h3>
        <p>The assistant found a way to reach the company. It will use this contact only if you approve.</p>
        <Detail payload={payload} keys={["company", "name", "phone", "email", "url", "source"]} />
      </>
    );
  }
  if (approval.kind === "disclosure") {
    return (
      <>
        <h3>The company asked for more details</h3>
        <p>This is not on your mandate. The assistant has not shared it. Approve only if you want it shared this one time.</p>
        <Detail payload={payload} keys={["requested", "fields", "reason"]} />
      </>
    );
  }
  if (approval.kind === "summary") {
    return (
      <>
        <h3>Check the call summary</h3>
        <p>This is what the assistant says happened. Approve it if it is right. Reject it if something is wrong.</p>
        {payload.summary ? <p className="quote">{String(payload.summary)}</p> : null}
      </>
    );
  }
  return <h3>A request needs your decision</h3>;
}

export function ApprovalCard({ approval, evidence = [], names = {}, onDecide }) {
  const payload = parsePayload(approval.payload);
  const pending = approval.status === "pending";
  const image = approval.kind === "send_image_to_llm";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);

  async function decide(decision) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await onDecide(approval, decision);
    } catch (err) {
      locked.current = false;
      setError(`${err.message}. Your answer was not saved. Try again.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`card approval approval-${approval.kind}`} aria-label={`Approval: ${approval.kind.replace(/_/g, " ")}`}>
      <Body approval={approval} payload={payload} evidence={evidence} names={names} />
      {pending ? (
        <>
          <p className="hint">You will be asked for your password.</p>
          {error ? (
            <p role="alert" className="form-error">
              {error}
            </p>
          ) : null}
          <p className="actions">
            <button type="button" onClick={() => decide("approve")} disabled={busy}>
              {image ? "Send the image" : "Approve"}
            </button>
            <button type="button" className="quiet" onClick={() => decide("reject")} disabled={busy}>
              {image ? "Do not send" : "Reject"}
            </button>
          </p>
        </>
      ) : (
        <p role="status" className="notice">
          {STATUS_TEXT[approval.status] || approval.status}
        </p>
      )}
    </article>
  );
}
