"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "@/components/StepUpDialog";

export default function HomePage() {
  const [signedIn, setSignedIn] = useState(Boolean(api.accessToken()));

  function logout() {
    api.logout();
    setSignedIn(false);
  }

  return (
    <section className="case-form">
      <h1>Your refund, in your words.</h1>
      <p>Tell the story once. Resolve keeps the case and talks to the company for you. The company call is simulated.</p>
      {signedIn ? (
        <p className="actions">
          <Link href="/cases">Cases</Link>
          <button type="button" onClick={logout}>
            Sign out
          </button>
        </p>
      ) : (
        <p className="actions">
          <Link href="/signup">Create account</Link>
          <Link href="/login">Sign in</Link>
        </p>
      )}
    </section>
  );
}
