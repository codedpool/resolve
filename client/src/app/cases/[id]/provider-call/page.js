"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { api } from "@/components/StepUpDialog";
import { CallPanel } from "@/components/CallPanel";
import { createBrowserVoiceClient } from "@/lib/audio/browserVoice";

/**
 * A practice call by voice where you play the company. The assistant speaks for the person who gave permission,
 * says it is an AI, and stays inside that permission. Nothing here reaches a real company.
 */
export default function ProviderCallPage() {
  const params = useParams();
  const [client] = useState(() => createBrowserVoiceClient(api, "provider_human"));

  useEffect(
    () => () => {
      client.end();
      client.dispose();
    },
    [client],
  );

  return (
    <main className="page">
      <p>
        <Link href={`/cases/${params.id}`}>Back to the case</Link>
      </p>
      <h1>Practice call: you play the company</h1>
      <p>
        Press Start and speak as a customer-care person would. The assistant answers for the person who gave permission.
        It needs a current permission on the case. Try a false claim that a refund was sent, or ask for a code, and see
        what it will and will not say. Wearing headphones avoids echo. This is only a practice.
      </p>
      <CallPanel client={client} caseId={String(params.id)} />
    </main>
  );
}
