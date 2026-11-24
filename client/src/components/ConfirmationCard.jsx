"use client";

import { useState } from "react";

export function ConfirmationCard({ fact, onAccept, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact.value);

  return (
    <article className="confirm-card">
      <h2>{fact.field}</h2>
      <p>{fact.value}</p>
      {fact.phrase ? <p>You said “{fact.phrase}”.</p> : null}
      <p>{fact.confirmation_state}</p>
      <p>Version {fact.version}</p>
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onEdit(fact, draft);
            setEditing(false);
          }}
        >
          <input aria-label={`Edit ${fact.field}`} value={draft} onChange={(event) => setDraft(event.target.value)} />
          <button type="submit">Save correction</button>
        </form>
      ) : (
        <p className="actions">
          <button type="button" onClick={() => onAccept(fact)}>
            Accept
          </button>
          <button type="button" onClick={() => setEditing(true)}>
            Edit
          </button>
        </p>
      )}
    </article>
  );
}
