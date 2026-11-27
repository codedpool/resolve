"use client";

import { useEffect, useState } from "react";

import { ApprovalCard } from "@/components/ApprovalCard";
import { api } from "@/components/StepUpDialog";
import { evidenceNames } from "@/lib/approvals";

export function ApprovalList({ caseId, version = 0, send = (path, options) => api.request(path, options) }) {
  const [approvals, setApprovals] = useState(null);
  const [evidence, setEvidence] = useState([]);
  const [error, setError] = useState("");
  const [names, setNames] = useState({});

  async function fetchAll() {
    try {
      const [list, files] = await Promise.all([
        send(`/approvals?case=${caseId}`),
        send(`/cases/${caseId}/evidence`).catch(() => ({ evidence: [] })),
      ]);
      return { list: list.approvals, files: files.evidence || [] };
    } catch (err) {
      return { failure: err };
    }
  }

  function apply(result) {
    if (result.failure) {
      setApprovals((current) => current || []);
      setError(`Could not load your approvals. ${result.failure.message}. Refresh the page to try again.`);
      return;
    }
    setNames(evidenceNames());
    setApprovals(result.list);
    setEvidence(result.files);
    setError("");
  }

  useEffect(() => {
    let live = true;
    fetchAll().then((result) => live && apply(result));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, version]);

  async function decide(approval, decision) {
    try {
      const saved = await send(`/approvals/${approval.id}/decision`, { method: "POST", body: { decision } });
      setApprovals((current) => current.map((item) => (item.id === approval.id ? { ...item, status: saved.status } : item)));
    } catch (err) {
      if (err.code === "already_decided") {
        apply(await fetchAll());
        return;
      }
      throw err;
    }
  }

  if (!approvals) return <p>Loading your approvals.</p>;

  const waiting = approvals.filter((item) => item.status === "pending");
  const done = approvals.filter((item) => item.status !== "pending");

  return (
    <div className="stack">
      {error ? (
        <p role="alert" className="form-error">
          {error}
        </p>
      ) : null}
      {waiting.length === 0 && !error ? <p>Nothing is waiting for your approval.</p> : null}
      {waiting.map((item) => (
        <ApprovalCard key={item.id} approval={item} evidence={evidence} names={names} onDecide={decide} />
      ))}
      {done.length ? <p className="subhead">Already decided</p> : null}
      {done.map((item) => (
        <ApprovalCard key={item.id} approval={item} evidence={evidence} names={names} onDecide={decide} />
      ))}
    </div>
  );
}
