"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { applyCaption } from "@/lib/audio/captions";

const PHASE_TEXT = {
  narration: "Tell your story in your own words. Choose Done when you have said it all.",
  gap_filling: "We are asking about anything that is missing.",
  confirming: "Check each detail on the right. Nothing is confirmed until you accept it.",
  mandate: "We are explaining what we may do for you.",
  provider_call: "We are speaking with the company for you.",
  summary: "Here is a summary of what happened.",
};

const CONNECTION_TEXT = {
  idle: "Not connected",
  connecting: "Connecting",
  live: "Connected",
  ended: "Call ended",
  error: "Not connected",
};

/**
 * The call controls and live captions. It only listens to `client` and calls its methods; the
 * page decides what to do with cards. A card or a caption never confirms anything here.
 */
export function CallPanel({ client, caseId, onCard, onEnded }) {
  const [state, setState] = useState(client.state);
  const [captions, setCaptions] = useState([]);
  const [muted, setMuted] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [phase, setPhase] = useState(null);
  const [doneSent, setDoneSent] = useState(false);
  const [error, setError] = useState("");
  const [ended, setEnded] = useState("");
  const [progress, setProgress] = useState("");
  const [approval, setApproval] = useState(false);
  const counter = useRef(0);
  const log = useRef(null);
  const cardHandler = useRef(onCard);
  const endedHandler = useRef(onEnded);

  useEffect(() => {
    cardHandler.current = onCard;
    endedHandler.current = onEnded;
  });

  useEffect(() => {
    const stops = [
      client.on("state", (next) => {
        setState(next);
        if (next === "connecting") {
          setCaptions([]);
          setError("");
          setEnded("");
          setProgress("");
          setApproval(false);
          setPhase(null);
          setDoneSent(false);
          setMuted(false);
          setSpeaking(false);
        }
      }),
      client.on("caption", (caption) => {
        counter.current += 1;
        const id = counter.current;
        setCaptions((current) => applyCaption(current, caption, id));
      }),
      client.on("muted", setMuted),
      client.on("speaking", setSpeaking),
      client.on("phase", ({ phase: next }) => setPhase(next)),
      client.on("done", () => setDoneSent(true)),
      client.on("error", (failure) => setError(failure.message)),
      client.on("ended", (info) => {
        setEnded(info.message);
        if (endedHandler.current) endedHandler.current(info);
      }),
      client.on("progress", ({ text }) => setProgress(text || "")),
      client.on("approval", () => setApproval(true)),
      client.on("card", (card) => cardHandler.current && cardHandler.current(card)),
    ];
    return () => stops.forEach((stop) => stop());
  }, [client]);

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [captions]);

  const busy = state === "connecting";
  const live = state === "live";
  const inCall = busy || live;
  const showDone = inCall && (!phase || phase === "narration");

  let listening = "Ready when you are";
  if (busy) listening = "Setting up the microphone";
  else if (live && muted) listening = "Your microphone is muted";
  else if (live && speaking) listening = "Resolve is speaking";
  else if (live) listening = "Listening";

  return (
    <section className="call" aria-label="Voice call">
      <h2>Talk it through</h2>
      <p className="hint">
        Speak in English, Hindi or both. Headphones help, because then the microphone does not pick up our voice. We do
        not keep the audio. Captions hide personal details such as phone numbers, so they can differ from your words.
      </p>

      <div className="call-status" role="status">
        <span className={`dot dot-${state}`} aria-hidden="true" />
        <span className="call-connection">{CONNECTION_TEXT[state]}</span>
        <span className={`call-speaking ${live && speaking ? "on" : ""}`} data-testid="speaking">
          {listening}
        </span>
      </div>

      {live && phase && PHASE_TEXT[phase] ? <p className="call-phase">{PHASE_TEXT[phase]}</p> : null}

      <p className="actions call-controls">
        {inCall ? (
          <button type="button" className="stamp" onClick={() => client.end()}>
            End call
          </button>
        ) : (
          <button type="button" onClick={() => client.start(caseId)}>
            Start the call
          </button>
        )}
        <button type="button" className="quiet" aria-pressed={muted} disabled={!inCall} onClick={() => client.setMuted(!muted)}>
          {muted ? "Unmute microphone" : "Mute microphone"}
        </button>
        {showDone ? (
          <button type="button" className="quiet" disabled={!live || doneSent} onClick={() => client.done()}>
            Done
          </button>
        ) : null}
      </p>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {ended && !error ? <p className="notice">{ended}</p> : null}
      {progress ? <p className="call-progress">{progress}</p> : null}
      {approval ? (
        <p className="notice">
          Something needs your decision. <Link href={`/cases/${caseId}`}>Open the case to review it</Link>.
        </p>
      ) : null}

      <div className="chat-log call-captions" ref={log} role="log" aria-live="polite" aria-label="Captions" tabIndex={0}>
        {captions.map((caption) => (
          <p key={caption.id} className={`bubble ${caption.who === "agent" ? "bubble-assistant" : "bubble-you"} ${caption.final ? "" : "bubble-live"}`}>
            <span className="bubble-who">{caption.who === "agent" ? "Resolve" : "You"}</span>
            <span className="bubble-text" dir="auto">
              {caption.text}
            </span>
          </p>
        ))}
      </div>
    </section>
  );
}
