"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApprovalList } from "@/components/ApprovalList";
import { api } from "@/components/StepUpDialog";

export default function ApprovalsPage() {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .request("/cases")
      .then((payload) => setCases(payload.cases))
      .catch((err) => {
        setCases([]);
        setError(`Could not load your cases. ${err.message}. Sign in again if this keeps happening.`);
      });
  }, []);

  return (
    <section className="case-form wide">
      <h1>Approvals</h1>
      <p>The assistant asks before it does anything that needs your say. Nothing happens until you decide.</p>
      {error ? (
        <p role="alert" className="form-error">
          {error}
        </p>
      ) : null}
      {cases === null ? <p>Loading your cases.</p> : null}
      {cases && cases.length === 0 && !error ? <p>You have no cases yet, so nothing is waiting.</p> : null}
      {(cases || []).map((item) => (
        <div key={item.id} className="stack">
          <h2>
            <Link href={`/cases/${item.id}`}>Case {item.id.slice(0, 8)}</Link>
          </h2>
          <ApprovalList caseId={item.id} />
        </div>
      ))}
    </section>
  );
}
