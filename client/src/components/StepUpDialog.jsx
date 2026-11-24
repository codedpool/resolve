"use client";

import { useEffect, useState } from "react";

import { createApi } from "@/lib/api";

export const api = createApi();

export function StepUpDialog() {
  const [pending, setPending] = useState(null);
  const [password, setPassword] = useState("");

  useEffect(() => {
    api.setStepUp(
      () =>
        new Promise((resolve) => {
          setPending(() => resolve);
        }),
    );
  }, []);

  if (!pending) return null;

  return (
    <form
      className="step-up"
      onSubmit={(event) => {
        event.preventDefault();
        const resolve = pending;
        setPending(null);
        resolve(password);
        setPassword("");
      }}
    >
      <p>Enter your password to continue.</p>
      <input
        type="password"
        value={password}
        autoFocus
        onChange={(event) => setPassword(event.target.value)}
        aria-label="Password"
      />
      <button type="submit">Continue</button>
    </form>
  );
}
