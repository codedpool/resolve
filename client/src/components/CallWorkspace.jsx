"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { api as defaultApi } from "@/components/StepUpDialog";
import { CallPanel } from "@/components/CallPanel";
import { ConfirmationCard } from "@/components/ConfirmationCard";
import { applyCorrection } from "@/components/facts";

/**
 * The call beside the confirmation cards. A card message from the call only makes a card appear.
 * A detail is confirmed when the person presses Accept on the card, through the usual confirm
 * request, and never any other way.
 */
export function CallWorkspace({ caseId, client, api = defaultApi }) {
  const [facts, setFacts] = useState([]);
  const [fields, setFields] = useState([]);
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    api
      .request(`/cases/${caseId}`)
      .then((detail) => live.current && setFacts(detail.facts || []))
      .catch((err) => live.current && setLoadError(err.message));
    return () => {
      live.current = false;
    };
  }, [api, caseId]);

  const showCard = useCallback(
    async ({ factId }) => {
      try {
        const detail = await api.request(`/cases/${caseId}`);
        if (!live.current) return;
        const latest = detail.facts || [];
        setFacts(latest);
        const fact = latest.find((item) => item.id === factId);
        if (fact) setFields((current) => (current.includes(fact.field) ? current : [...current, fact.field]));
        setNotice("");
      } catch (err) {
        if (live.current) setNotice(`We could not load the detail to check. ${err.message}`);
      }
    },
    [api, caseId],
  );

  async function accept(fact) {
    let saved;
    try {
      saved = await api.request(`/cases/${caseId}/facts/${fact.id}/confirm`, { method: "POST" });
    } catch (err) {
      setNotice(`We could not accept that detail. ${err.message}`);
      return;
    }
    setNotice("");
    setFacts((current) =>
      current.map((item) =>
        item.id === fact.id ? { ...item, confirmation_state: "confirmed", version: saved.confirmed_version } : item,
      ),
    );
  }

  async function edit(fact, value) {
    let saved;
    try {
      saved = await api.request(`/cases/${caseId}/facts`, {
        method: "POST",
        body: { field: fact.field, value, certainty: fact.certainty, phrase: fact.phrase || "" },
      });
    } catch (err) {
      setNotice(`We could not save that correction. ${err.message}`);
      return;
    }
    setNotice("");
    setFacts((current) => applyCorrection(current, fact, saved, value));
  }

  const cards = fields.map((field) => facts.find((fact) => fact.field === field)).filter(Boolean);

  return (
    <section className="case-form wide call-page">
      <h1>Voice call</h1>
      <p>
        <Link href={`/cases/${caseId}`}>Back to the case</Link>
      </p>
      <div className="call-layout">
        <CallPanel client={client} caseId={caseId} onCard={showCard} />
        <aside className="call-cards" aria-label="Details to check">
          <h2>Details to check</h2>
          {loadError ? <p className="form-error">{loadError}</p> : null}
          {notice ? (
            <p className="form-error" role="alert">
              {notice}
            </p>
          ) : null}
          {cards.length === 0 ? (
            <p className="hint">Each detail we need you to check will appear here during the call. Accept it or correct it.</p>
          ) : null}
          {cards.map((fact) => (
            <ConfirmationCard key={fact.field} fact={fact} onAccept={accept} onEdit={edit} />
          ))}
        </aside>
      </div>
    </section>
  );
}
