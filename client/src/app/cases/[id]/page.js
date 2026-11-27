"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { api } from "@/components/StepUpDialog";
import { ApprovalList } from "@/components/ApprovalList";
import { MandateCard } from "@/components/MandateCard";
import { PracticeCall } from "@/components/PracticeCall";
import { EvidenceUploader } from "@/components/EvidenceUploader";
import { ConfirmationCard } from "@/components/ConfirmationCard";
import { applyCorrection, CRITICAL_FIELDS } from "@/components/facts";
import { FactList } from "@/components/FactList";
import { IntakeChat } from "@/components/IntakeChat";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";
import { rememberEvidenceName } from "@/lib/approvals";

export default function CasePage() {
  const params = useParams();
  const [detail, setDetail] = useState(null);
  const [evidence, setEvidence] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mandateActive, setMandateActive] = useState(false);
  const [approvalsVersion, setApprovalsVersion] = useState(0);
  const details = useRef(null);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++latest.current;
    try {
      const fresh = await api.request(`/cases/${params.id}`);
      if (mine === latest.current) setDetail(fresh); // an older answer never overwrites a newer one
      setNotice("");
    } catch (err) {
      setNotice(`We could not refresh the details. ${err.message}`);
    }
  }, [params.id]);

  useEffect(() => {
    const id = params.id;
    api
      .request(`/cases/${id}`)
      .then(setDetail)
      .catch((err) => setError(err.message));
    api
      .request(`/cases/${id}/evidence`)
      .then((payload) => setEvidence(payload.evidence))
      .catch(() => {});
    api
      .request(`/cases/${id}/mandate`)
      .then((payload) => setMandateActive(Boolean(payload.mandate?.active)))
      .catch(() => {});
  }, [params.id]);

  async function upload(file) {
    const saved = await api.upload(`/cases/${params.id}/evidence`, file);
    rememberEvidenceName(saved.id, file.name);
    setEvidence((current) => [...current, saved]);
  }

  async function afterCallStep() {
    await reload();
    setApprovalsVersion((current) => current + 1);
  }

  function showDetails() {
    const region = details.current;
    if (!region) return;
    region.scrollIntoView?.({ block: "start" });
    region.focus();
  }

  async function accept(fact) {
    let saved;
    try {
      saved = await api.request(`/cases/${params.id}/facts/${fact.id}/confirm`, { method: "POST" });
    } catch (err) {
      setNotice(`We could not accept that detail. ${err.message}`);
      return;
    }
    setNotice("");
    setDetail((current) => ({
      ...current,
      facts: current.facts.map((item) =>
        item.id === fact.id ? { ...item, confirmation_state: "confirmed", version: saved.confirmed_version } : item,
      ),
    }));
    await reload(); // accepting the last critical detail changes the case status
  }

  async function edit(fact, value) {
    let saved;
    try {
      saved = await api.request(`/cases/${params.id}/facts`, {
        method: "POST",
        body: { field: fact.field, value, certainty: fact.certainty, phrase: fact.phrase || "" },
      });
    } catch (err) {
      setNotice(`We could not save that correction. ${err.message}`);
      return;
    }
    setNotice("");
    setDetail((current) => ({ ...current, facts: applyCorrection(current.facts, fact, saved, value) }));
  }

  if (error) return <p className="form-error">{error}</p>;
  if (!detail) return <p>Loading the case.</p>;

  return (
    <section className="case-form wide">
      <h1>Case {String(detail.id).slice(0, 8)}</h1>
      <StatusBadge status={detail.status} simulated={detail.simulated} />
      <p className="actions">
        <Link href={`/cases/${params.id}/call`}>Tell us by voice instead</Link>
        {" · "}
        <Link href={`/cases/${params.id}/provider-call`}>Practise a voice call as the company</Link>
      </p>
      <IntakeChat caseId={String(params.id)} onFactsChanged={reload} onEditDetails={showDetails} />
      {notice ? (
        <p className="form-error" role="alert">
          {notice}
        </p>
      ) : null}
      <div className="details" ref={details} tabIndex={-1} aria-label="Details to check">
        {(detail.facts || [])
          .filter((fact) => CRITICAL_FIELDS.includes(fact.field))
          .map((fact) => (
            <ConfirmationCard key={fact.id} fact={fact} onAccept={accept} onEdit={edit} />
          ))}
      </div>
      <FactList facts={detail.facts || []} />
      <Timeline events={detail.timeline || []} />
      <MandateCard caseId={String(params.id)} onChange={(mandate) => setMandateActive(Boolean(mandate?.active))} />
      <PracticeCall caseId={String(params.id)} mandateActive={mandateActive} onChange={afterCallStep} />
      <h2 id="approvals">Approvals</h2>
      <ApprovalList caseId={String(params.id)} version={approvalsVersion} />
      <EvidenceUploader onFile={upload} />
      <ul>
        {evidence.map((item) => (
          <li key={item.id}>Uploaded {item.type}</li>
        ))}
      </ul>
    </section>
  );
}
