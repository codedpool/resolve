"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { api } from "@/components/StepUpDialog";
import { EvidenceUploader } from "@/components/EvidenceUploader";
import { FactList } from "@/components/FactList";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";

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
    setEvidence((current) => [...current, saved]);
  }

  if (error) return <p className="form-error">{error}</p>;
  if (!detail) return <p>Loading the case.</p>;

  return (
    <section className="case-form">
      <h1>Case {String(detail.id).slice(0, 8)}</h1>
      <StatusBadge status={detail.status} simulated={detail.simulated} />
      <FactList facts={detail.facts || []} />
      <Timeline events={detail.timeline || []} />
      <EvidenceUploader onFile={upload} />
      <ul>
        {evidence.map((item) => (
          <li key={item.id}>Uploaded {item.type}</li>
        ))}
      </ul>
    </section>
  );
}
