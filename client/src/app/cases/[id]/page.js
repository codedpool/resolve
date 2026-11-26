"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { api } from "@/components/StepUpDialog";
import { ApprovalList } from "@/components/ApprovalList";
import { MandateCard } from "@/components/MandateCard";
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
  }, [params.id]);

  async function upload(file) {
    const saved = await api.upload(`/cases/${params.id}/evidence`, file);
    rememberEvidenceName(saved.id, file.name);
    setEvidence((current) => [...current, saved]);
  }

  async function accept(fact) {
    const saved = await api.request(`/cases/${params.id}/facts/${fact.id}/confirm`, { method: "POST" });
    setDetail((current) => ({
      ...current,
      facts: current.facts.map((item) =>
        item.id === fact.id ? { ...item, confirmation_state: "confirmed", version: saved.confirmed_version } : item,
      ),
    }));
  }

  async function edit(fact, value) {
    const saved = await api.request(`/cases/${params.id}/facts`, {
      method: "POST",
      body: { field: fact.field, value, certainty: fact.certainty, phrase: fact.phrase || "" },
    });
    setDetail((current) => ({ ...current, facts: applyCorrection(current.facts, fact, saved, value) }));
  }

  if (error) return <p className="form-error">{error}</p>;
  if (!detail) return <p>Loading the case.</p>;

  return (
    <section className="case-form wide">
      <h1>Case {String(detail.id).slice(0, 8)}</h1>
      <StatusBadge status={detail.status} simulated={detail.simulated} />
      {(detail.facts || [])
        .filter((fact) => CRITICAL_FIELDS.includes(fact.field))
        .map((fact) => (
          <ConfirmationCard key={fact.id} fact={fact} onAccept={accept} onEdit={edit} />
        ))}
      <FactList facts={detail.facts || []} />
      <Timeline events={detail.timeline || []} />
      <MandateCard caseId={String(params.id)} />
      <h2>Approvals</h2>
      <ApprovalList caseId={String(params.id)} />
      <IntakeChat caseId={String(params.id)} />
      <EvidenceUploader onFile={upload} />
      <ul>
        {evidence.map((item) => (
          <li key={item.id}>Uploaded {item.type}</li>
        ))}
      </ul>
    </section>
  );
}
