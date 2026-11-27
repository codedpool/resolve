"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { api } from "@/components/StepUpDialog";
import { CallWorkspace } from "@/components/CallWorkspace";
import { createBrowserVoiceClient } from "@/lib/audio/browserVoice";

export default function CallPage() {
  const params = useParams();
  const [client] = useState(() => createBrowserVoiceClient(api));

  // Leaving the page closes the call.
  useEffect(
    () => () => {
      client.end();
      client.dispose();
    },
    [client],
  );

  return <CallWorkspace caseId={String(params.id)} client={client} />;
}
