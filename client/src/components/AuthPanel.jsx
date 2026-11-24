"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api";
import { api } from "@/components/StepUpDialog";

export function AuthPanel({ mode }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      const body = { email, password, language: "en" };
      if (mode === "signup") await api.signup(body);
      else await api.login({ email, password });
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server");
    }
  }

  return (
    <form className="case-form" onSubmit={submit}>
      <h1>{mode === "signup" ? "Open a case file" : "Return to your cases"}</h1>
      <label>
        Email
        <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
      </label>
      <label>
        Password
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
      </label>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit">{mode === "signup" ? "Create account" : "Sign in"}</button>
    </form>
  );
}
