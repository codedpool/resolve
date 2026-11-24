"use client";

import { useRef, useState } from "react";

import { api } from "@/components/StepUpDialog";

export function IntakeChat({ caseId, send = (path, options) => api.request(path, options) }) {
  const [text, setText] = useState("");
  const [messages, setMessages] = useState([]);
  const [done, setDone] = useState(false);
  const sent = useRef(false);

  async function submit(event) {
    event.preventDefault();
    const spoken = text.trim();
    if (!spoken) return;
    const reply = await send(`/cases/${caseId}/intake/messages`, { method: "POST", body: { text: spoken } });
    setMessages((current) => [...current, { who: "you", text: spoken }, { who: "agent", text: reply.text }]);
    setText("");
  }

  function finish() {
    if (sent.current) return;
    sent.current = true;
    setDone(true);
    send(`/cases/${caseId}/narration-done`, { method: "POST" });
  }

  return (
    <form className="intake" onSubmit={submit}>
      <label>
        Narration
        <textarea aria-label="Narration" value={text} onChange={(event) => setText(event.target.value)} />
      </label>
      <p className="actions">
        <button type="submit">Send</button>
        <button type="button" onClick={finish} disabled={done}>
          Done
        </button>
      </p>
      <ol>
        {messages.map((message, index) => (
          <li key={`${message.who}-${index}`}>
            {message.who}: {message.text}
          </li>
        ))}
      </ol>
    </form>
  );
}
