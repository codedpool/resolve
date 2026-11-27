"use client";

import { useState } from "react";

export function fieldLabel(field) {
  const words = String(field).replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A small form for the critical details the chat could not get. It only proposes facts. It never confirms them. */
export function HandoffForm({ caseId, fields, send, onSaved }) {
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const filled = fields.filter((field) => (values[field] || "").trim());
    if (!filled.length) {
      setError("Type at least one of these details, then save.");
      return;
    }
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      for (const field of filled) {
        await send(`/cases/${caseId}/facts`, {
          method: "POST",
          body: { field, value: values[field].trim(), certainty: "stated", phrase: "" },
        });
      }
      setSaved(true);
      setValues({});
      if (onSaved) await onSaved();
    } catch (err) {
      setError(`We could not save those details. ${err?.message || "Try again."}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="handoff-form" onSubmit={submit} aria-label="Details to type in">
      {fields.map((field) => (
        <label key={field}>
          {fieldLabel(field)}
          <input
            type="text"
            dir="auto"
            value={values[field] || ""}
            onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
          />
        </label>
      ))}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p className="notice" role="status">
          Saved. Check the details below and accept each one.
        </p>
      ) : null}
      <p className="actions">
        <button type="submit" disabled={saving}>
          Save details
        </button>
      </p>
    </form>
  );
}
