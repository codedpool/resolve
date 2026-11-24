"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/components/StepUpDialog";
import { StatusBadge } from "@/components/StatusBadge";

export default function CasesPage() {
  const router = useRouter();
  const [cases, setCases] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .request("/cases")
      .then((payload) => setCases(payload.cases))
      .catch((err) => setError(err.message));
  }, []);

  async function openCase() {
    const created = await api.request("/cases", { method: "POST" });
    router.push(`/cases/${created.id}`);
  }

  return (
    <section className="case-form">
      <h1>Cases</h1>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="button" onClick={openCase}>
        Open a case
      </button>
      {cases.length === 0 ? <p>No cases yet.</p> : null}
      <ul>
        {cases.map((item) => (
          <li key={item.id}>
            <Link href={`/cases/${item.id}`}>Case {item.id.slice(0, 8)}</Link>
            <StatusBadge status={item.status} simulated={item.simulated} />
          </li>
        ))}
      </ul>
    </section>
  );
}
