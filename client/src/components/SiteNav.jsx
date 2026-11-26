"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/components/StepUpDialog";
import { UNREAD_EVENT, unreadCount } from "@/lib/notifications";

export function SiteNav() {
  const pathname = usePathname();
  const [count, setCount] = useState(null);

  useEffect(() => {
    let live = true;
    if (api.accessToken()) {
      api
        .request("/notifications")
        .then((payload) => live && setCount(unreadCount(payload.notifications)))
        .catch(() => {});
    }
    return () => {
      live = false;
    };
  }, [pathname]);

  useEffect(() => {
    const listen = (event) => setCount(event.detail.count);
    window.addEventListener(UNREAD_EVENT, listen);
    return () => window.removeEventListener(UNREAD_EVENT, listen);
  }, []);

  const signedIn = count !== null;

  return (
    <nav className="site-nav" aria-label="Main">
      <Link href="/" className="brand">
        Resolve
      </Link>
      {signedIn ? (
        <>
          <Link href="/cases">Cases</Link>
          <Link href="/approvals">Approvals</Link>
          <Link href="/inbox">
            Messages
            {count > 0 ? (
              <span className="count" aria-label={`${count} unread`}>
                {count}
              </span>
            ) : null}
          </Link>
        </>
      ) : null}
    </nav>
  );
}
